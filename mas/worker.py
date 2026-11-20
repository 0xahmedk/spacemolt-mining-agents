"""Generic A2A game worker: one OS process per role.

    python -m mas.worker --role resource --port 9101
    python -m mas.worker --role trading  --port 9102

What happens when a task arrives (see GameWorkerExecutor.execute):
  1. Parse + validate the JSON TaskRequest (mas/a2a_protocol.py). Bad input -> task FAILED.
  2. Task-level dedupe: if our store says this task_id is already completed/failed, return the
     stored result without touching the game.
  3. Take the pilot lease (one agent steers one pilot). Busy -> FAILED 'pilot_busy'.
  4. Run the skill with a SkillContext. Every game call goes through the MCP gateway.
  5. Store the result, release the lease, attach the JSON TaskResult as the A2A artifact.

Two kinds of game actions, two kinds of duplicate protection (see SkillContext):
  * goods/money actions (mine, sell, accept/complete mission, orders): deterministic
    idempotency keys `<task_id>:<step>` in the action ledger -> a resent task replays
    confirmed steps from the ledger instead of executing them again.
  * position actions (travel, dock, undock): converge on a target state -> observe first and
    only act if not already there, so repeating them is harmless.

On startup the worker marks tasks it was running when it died as 'unknown' and frees
its leases; the coordinator then resends them (same task_id) and they resume safely.
"""
from __future__ import annotations

import argparse
import uuid
from typing import Awaitable, Callable

from a2a.helpers import get_message_text, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from mas.a2a_protocol import (MEDIA_TYPE, ROLE_SKILLS, ProtocolError, TaskRequest, TaskResult,
                              error as err)
from mas.mcp_gateway import AmbiguousOutcome, GameError, GameGateway, GatewayError, InvalidParams
from mas.mcp_session import ToolResult
from mas.parsers import parse_poi, parse_status
from mas.store import IllegalTransition, Store

LEASE_TTL = 180.0          # seconds; renewed on every game action
STATION_POI = 'grand_exchange'


class SkillError(Exception):
    """A skill refuses or cannot do the task (not a crash). Reported as a failed result."""

    def __init__(self, code: str, message: str, **data):
        super().__init__(f'{code}: {message}')
        self.code, self.message, self.data = code, message, data


class NeedsReconcile(Exception):
    """An action's outcome is unknown and cannot be decided automatically."""


# ======================================================================  SkillContext
class SkillContext:
    """Everything a skill needs; keeps evidence of what it did."""

    def __init__(self, req: TaskRequest, gw: GameGateway, store: Store, role: str, holder: str,
                 progress: Callable[[str], Awaitable[None]] | None = None):
        self.req, self.gw, self.store, self.role, self.holder = req, gw, store, role, holder
        self.pilot, self.task_id = req.pilot, req.task_id
        self._progress = progress
        self.actions: list[str] = []          # idempotency keys used (evidence)
        self.last_status: dict | None = None

    # ------------------------------------------------------------ observe
    async def status(self) -> dict:
        r = await self.gw.query('spacemolt', 'get_status', task_id=self.task_id)
        st = parse_status(r.text)
        self.store.observations.record(self.pilot, 'status', st, 'spacemolt.get_status')
        self.last_status = st
        return st

    async def poi(self) -> dict:
        r = await self.gw.query('spacemolt', 'get_poi', task_id=self.task_id)
        p = parse_poi(r.text)
        self.store.observations.record(self.pilot, 'poi', p, 'spacemolt.get_poi')
        return p

    async def progress(self, text: str):
        self.store.leases.renew(self.pilot, self.holder, LEASE_TTL)
        if self._progress:
            await self._progress(text)

    # ------------------------------------------------------------ goods/money actions
    async def act(self, step: str, tool: str, action: str, args: dict | None = None, *,
                  verify: Callable[[dict, dict], bool] | None = None) -> ToolResult:
        """Run a state-changing action at most once for this task.

        `verify(before_status, after_status) -> bool` says whether the action took effect;
        it is used only if the outcome is unknown (timeout / crash mid-call).
        """
        key = f'{self.task_id}:{step}'
        self.actions.append(key)
        if not self.store.leases.renew(self.pilot, self.holder, LEASE_TTL):
            raise SkillError('lease_lost', f'lease on {self.pilot} expired or was taken over')
        rec = self.store.actions.get(key)
        if rec and rec.status in ('pending', 'unknown'):
            if await self._reconcile(key, verify):
                return await self.gw.act(tool, action, args, idempotency_key=key, task_id=self.task_id)
        if not (rec and rec.status == 'confirmed'):
            before = await self.status()      # checkpoint for later reconciliation
            self.store.observations.record(self.pilot, f'checkpoint:{key}', before, 'checkpoint')
        try:
            return await self.gw.act(tool, action, args, idempotency_key=key, task_id=self.task_id)
        except AmbiguousOutcome:
            applied = await self._reconcile(key, verify)
            # applied -> ledger now 'confirmed' -> act() returns the stored result without calling the game
            # not applied -> ledger 'failed' -> act() may execute once more
            return await self.gw.act(tool, action, args, idempotency_key=key, task_id=self.task_id)

    async def _reconcile(self, key: str, verify) -> bool:
        cp = self.store.observations.latest(self.pilot, f'checkpoint:{key}')
        if verify is None or cp is None:
            raise NeedsReconcile(f'{key}: outcome unknown and no automatic check available')
        now = await self.status()
        applied = bool(verify(cp['data'], now))
        self.store.actions.resolve(key, 'confirmed' if applied else 'failed',
                                   f'reconciled by {self.role}: applied={applied}')
        self.gw._log('action.reconciled', {'key': key, 'applied': applied}, self.task_id)
        return applied

    # ------------------------------------------------------------ position actions
    async def _converge(self, action: str, args: dict, done: Callable[[], Awaitable[bool]]) -> bool:
        """Act only if not already in the target state; on an unknown outcome, look again."""
        if await done():
            return False
        key = f'{self.task_id}:{action}:{uuid.uuid4().hex[:8]}'   # unique: dedupe is by observation
        self.actions.append(key)
        self.store.leases.renew(self.pilot, self.holder, LEASE_TTL)
        try:
            await self.gw.act('spacemolt', action, args, idempotency_key=key, task_id=self.task_id)
        except AmbiguousOutcome:
            ok = await done()
            self.store.actions.resolve(key, 'confirmed' if ok else 'failed', 'converge check')
            if not ok:
                raise SkillError('navigation_unknown', f'{action} {args} outcome unknown and not in target state')
        return True

    async def ensure_undocked(self):
        async def done():
            return not (await self.status())['docked']
        await self._converge('undock', {}, done)

    async def ensure_docked(self):
        async def done():
            return (await self.status())['docked']
        await self._converge('dock', {}, done)

    async def ensure_at(self, poi_id: str):
        if (await self.poi())['id'] == poi_id:
            return
        await self.ensure_undocked()

        async def done():
            return (await self.poi())['id'] == poi_id
        await self._converge('travel', {'id': poi_id}, done)
        await self.progress(f'arrived at {poi_id}')

    async def ensure_docked_at(self, station_poi: str = STATION_POI):
        await self.ensure_at(station_poi)
        await self.ensure_docked()

    def evidence(self, before: dict | None, after: dict | None) -> dict:
        keep = ('credits', 'fuel', 'cargo_used', 'cargo', 'docked_at', 'system')
        pick = (lambda s: {k: s.get(k) for k in keep} if s else None)
        return {'before': pick(before), 'after': pick(after), 'actions': self.actions}


Skill = Callable[[SkillContext, TaskRequest], Awaitable[TaskResult]]


# ======================================================================  executor
class GameWorkerExecutor(AgentExecutor):
    def __init__(self, role: str, store: Store, skills: dict[str, Skill],
                 gateway_factory: Callable[[str], Awaitable[GameGateway]]):
        self.role, self.store, self.skills = role, store, skills
        self._gateway_factory = gateway_factory
        self._gateways: dict[str, GameGateway] = {}

    async def gateway(self, pilot: str) -> GameGateway:
        if pilot not in self._gateways:
            self._gateways[pilot] = await self._gateway_factory(pilot)
        return self._gateways[pilot]

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)

        async def finish(result: TaskResult):
            await updater.add_artifact(parts=[new_text_part(result.to_json(), media_type=MEDIA_TYPE)],
                                       name='task_result')
            msg = new_text_message(result.summary or result.status)
            if result.ok:
                await updater.complete(msg)
            else:
                await updater.failed(msg)

        try:
            req = TaskRequest.from_json(get_message_text(context.message), role=self.role)
        except ProtocolError as e:
            await finish(TaskResult(task_id='?', skill='?', pilot='?', status='failed',
                                    summary=f'rejected: {e}', error=err('bad_request', str(e))))
            return

        await updater.start_work(new_text_message(f'{self.role} working on {req.skill} for {req.pilot}'))
        result = await self.run(req, a2a_task_id=task.id,
                                progress=lambda text: updater.update_status(
                                    state=TaskState.TASK_STATE_WORKING, message=new_text_message(text)))
        await finish(result)

    async def run(self, req: TaskRequest, *, a2a_task_id: str | None = None, progress=None) -> TaskResult:
        """Execute one task (also used directly by tests)."""
        tasks = self.store.tasks
        rec = tasks.get(req.task_id)
        if rec and rec['status'] in ('completed', 'failed', 'cancelled'):
            self.store.tasks._log('task.duplicate_returned', {'task_id': req.task_id, 'status': rec['status']})
            stored = rec.get('result') or {}
            return TaskResult(**{**{'task_id': req.task_id, 'skill': req.skill, 'pilot': req.pilot,
                                    'status': rec['status']}, **stored})
        if rec is None:
            tasks.create(req.mission_id, assignee=self.role, skill=req.skill, pilot=req.pilot,
                         payload={'params': req.params, 'constraints': req.constraints}, task_id=req.task_id)
        tasks.mark(req.task_id, 'working', a2a_task_id=a2a_task_id)

        holder = f'{self.role}:{req.task_id}'
        if rec and rec['status'] == 'working' and self.store.leases.holder(req.pilot) == holder:
            # The same task is still running (e.g. the coordinator restarted and resent it).
            # Never run two copies: tell the caller to come back later; the store is unchanged.
            return TaskResult(req.task_id, req.skill, req.pilot, 'needs_reconcile',
                              summary='task is already running in this worker',
                              error=err('task_in_progress', 'same task id is still executing'))
        if not self.store.leases.acquire(req.pilot, holder, LEASE_TTL, task_id=req.task_id):
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed',
                                summary=f'pilot {req.pilot} is busy ({self.store.leases.holder(req.pilot)})',
                                error=err('pilot_busy', 'another agent holds the pilot lease'))
            tasks.mark(req.task_id, 'failed', result=_as_dict(result), error='pilot_busy')
            return result

        ctx = None
        try:
            ctx = SkillContext(req, await self.gateway(req.pilot), self.store, self.role, holder, progress)
            result = await self.skills[req.skill](ctx, req)
        except SkillError as e:
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed', summary=e.message,
                                data=e.data, error=err(e.code, e.message))
        except GameError as e:
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed', summary=f'game refused: {e}',
                                error=err(e.code, e.message))
        except (AmbiguousOutcome, NeedsReconcile) as e:
            result = TaskResult(req.task_id, req.skill, req.pilot, 'needs_reconcile', summary=str(e),
                                error=err('needs_reconcile', str(e)))
        except InvalidParams as e:
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed', summary=str(e),
                                error=err('invalid_params', str(e)))
        except GatewayError as e:
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed', summary=str(e),
                                error=err('gateway_error', str(e)))
        except Exception as e:  # never crash the worker on one bad task
            result = TaskResult(req.task_id, req.skill, req.pilot, 'failed',
                                summary=f'internal error {type(e).__name__}', error=err('internal_error', repr(e)))
        finally:
            self.store.leases.release(req.pilot, holder)

        if ctx is not None and not result.evidence:
            result.evidence = ctx.evidence(None, ctx.last_status)
        store_status = {'completed': 'completed', 'failed': 'failed', 'needs_reconcile': 'unknown'}[result.status]
        try:
            tasks.mark(req.task_id, store_status, result=_as_dict(result),
                       error=(result.error or {}).get('code'))
        except IllegalTransition:
            pass
        return result

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return  # tasks are short-lived and idempotent; cancellation = let it finish

    def recover_after_restart(self) -> list[str]:
        """Mark tasks this role was running when the process died as 'unknown' and free leases."""
        orphaned = []
        for t in self.store.tasks.unfinished(self.role):
            if t['status'] in ('submitted', 'working'):
                self.store.tasks.mark(t['task_id'], 'unknown', error='worker restarted mid-task')
                orphaned.append(t['task_id'])
            if t.get('pilot'):
                self.store.leases.release(t['pilot'], f"{self.role}:{t['task_id']}")
        if orphaned:
            self.store.tasks._log('worker.recovered', {'role': self.role, 'orphaned_tasks': orphaned})
        return orphaned


def _as_dict(result: TaskResult) -> dict:
    import dataclasses
    return dataclasses.asdict(result)


# ======================================================================  server
def build_app(role: str, port: int, store: Store, skills: dict[str, Skill], host: str = '127.0.0.1',
              gateway_factory=None):
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from starlette.applications import Starlette

    async def default_factory(pilot: str) -> GameGateway:
        gw = GameGateway(pilot, agent=f'{role}-agent', db=store.db)
        await gw.connect()
        return gw

    executor = GameWorkerExecutor(role, store, skills, gateway_factory or default_factory)
    card = AgentCard(
        name=f'SpaceMolt {role.title()} Agent',
        description=f'{role} worker of the SpaceMolt multi-agent system; executes validated game tasks via MCP',
        version='1.0.0', default_input_modes=[MEDIA_TYPE], default_output_modes=[MEDIA_TYPE],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding='JSONRPC', url=f'http://{host}:{port}',
                                             protocol_version='1.0')],
        skills=[AgentSkill(id=name, name=name, description=desc, input_modes=[MEDIA_TYPE],
                           output_modes=[MEDIA_TYPE], tags=['spacemolt', role]) for name, desc in
                ROLE_SKILLS[role].items()])
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)
    app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, '/')])
    return app, executor


def main():
    import uvicorn

    from mas import resource_skills, trading_skills
    p = argparse.ArgumentParser(description='SpaceMolt A2A worker')
    p.add_argument('--role', choices=sorted(ROLE_SKILLS), required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--db', default=None, help='shared SQLite path (default logs/state.sqlite3)')
    a = p.parse_args()
    store = Store(a.db, agent=f'{a.role}-agent') if a.db else Store(agent=f'{a.role}-agent')
    skills = resource_skills.SKILLS if a.role == 'resource' else trading_skills.SKILLS
    app, executor = build_app(a.role, a.port, store, skills, host=a.host)
    orphaned = executor.recover_after_restart()
    print(f'[{a.role}] recovered {len(orphaned)} unfinished task(s) from a previous run: {orphaned}')
    print(f'[{a.role}] A2A agent card: http://{a.host}:{a.port}/.well-known/agent-card.json')
    uvicorn.run(app, host=a.host, port=a.port, log_level='warning')


if __name__ == '__main__':
    main()
