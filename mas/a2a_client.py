"""Coordinator-side A2A client: discover a worker, send a task, poll until it finishes.

Long tasks (mining can take minutes) use the non-blocking A2A flow:
  1. send_message with return_immediately=True -> the worker answers at once with a Task id;
  2. poll get_task(id) every few seconds until the task reaches a terminal state;
  3. read our JSON TaskResult from the task's artifact.

If the worker process dies, polling fails -> WorkerUnavailable. The coordinator then marks
its own task record 'unknown' and can resend the SAME task_id later: the worker replays it
idempotently (confirmed game actions are not repeated).
"""
from __future__ import annotations

import asyncio
import time

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import GetTaskRequest, Role, SendMessageRequest, TaskState

from mas.a2a_protocol import MEDIA_TYPE, TaskRequest, TaskResult

TERMINAL = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED}


class WorkerUnavailable(Exception):
    """The worker could not be reached (not started, crashed, or lost the task)."""


class WorkerClient:
    def __init__(self, url: str, *, http: httpx.AsyncClient | None = None, poll_seconds: float = 3.0):
        self.url = url.rstrip('/')
        self._http = http
        self._own_http = http is None
        self.poll_seconds = poll_seconds
        self.card = None
        self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def connect(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        try:
            self.card = await A2ACardResolver(httpx_client=self._http, base_url=self.url).get_agent_card()
        except Exception as e:
            raise WorkerUnavailable(f'no agent card at {self.url}: {type(e).__name__}: {e}') from e
        self._client = await create_client(
            agent=self.card,
            client_config=ClientConfig(streaming=False, polling=True, httpx_client=self._http))
        return self.card

    async def close(self):
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
        if self._own_http and self._http is not None:
            await self._http.aclose()
        self._client = None

    async def run_task(self, request: TaskRequest, *, timeout: float = 900.0,
                       on_update=None) -> tuple[TaskResult, str]:
        """Send a task and wait for its result. Returns (TaskResult, a2a_task_id)."""
        if self._client is None:
            await self.connect()
        message = new_text_message(request.to_json(), media_type=MEDIA_TYPE, role=Role.ROLE_USER)
        try:
            task = None
            async for response in self._client.send_message(SendMessageRequest(message=message)):
                if response.HasField('task'):
                    task = response.task
                elif response.HasField('message'):  # a worker should always answer with a Task
                    raise WorkerUnavailable('worker replied with a message instead of a task: '
                                            + get_message_text(response.message)[:200])
        except WorkerUnavailable:
            raise
        except Exception as e:
            raise WorkerUnavailable(f'send failed: {type(e).__name__}: {e}') from e
        if task is None:
            raise WorkerUnavailable('worker returned no task')
        a2a_id = task.id
        if on_update:
            on_update(a2a_id, TaskState.Name(task.status.state))

        deadline = time.monotonic() + timeout
        last_state = task.status.state
        while task.status.state not in TERMINAL:
            if time.monotonic() > deadline:
                raise WorkerUnavailable(f'task {request.task_id} timed out after {timeout:.0f}s')
            await asyncio.sleep(self.poll_seconds)
            try:
                task = await self._client.get_task(GetTaskRequest(id=a2a_id))
            except Exception as e:
                raise WorkerUnavailable(f'lost task {a2a_id}: {type(e).__name__}: {e}') from e
            if on_update and task.status.state != last_state:
                on_update(a2a_id, TaskState.Name(task.status.state))
            last_state = task.status.state

        for artifact in reversed(list(task.artifacts)):
            text = get_artifact_text(artifact)
            if text.strip().startswith('{'):
                return TaskResult.from_json(text), a2a_id
        status_text = get_message_text(task.status.message) if task.status.HasField('message') else ''
        return TaskResult(task_id=request.task_id, skill=request.skill, pilot=request.pilot,
                          status='failed', summary='worker returned no result artifact',
                          error={'code': 'no_artifact', 'message': status_text[:300]}), a2a_id
