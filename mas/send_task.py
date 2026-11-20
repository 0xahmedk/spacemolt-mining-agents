"""Send ONE task to a running worker over A2A and print the result (manual test tool).

This is a stand-in for the coordinator while testing Phase 4; it records the mission
and task in the shared store exactly like the coordinator will.

    python -m mas.send_task --url http://127.0.0.1:9101 --pilot Prac-Ahmed1 --skill status
    python -m mas.send_task --url http://127.0.0.1:9101 --pilot Prac-Ahmed1 --skill mine \
        --params '{"poi":"commerce_fields"}' --constraints '{"max_cycles":3}'

Resend a task (e.g. after killing a worker) with --task-id <the id printed earlier>.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from mas.a2a_client import WorkerClient, WorkerUnavailable
from mas.a2a_protocol import TaskRequest
from mas.store import IllegalTransition, Store


def _mark(store, task_id, status, **kw):
    try:
        store.tasks.mark(task_id, status, **kw)
    except IllegalTransition:
        pass  # the worker already finished it; the worker's record wins


async def main(a):
    store = Store(agent='manual-sender')
    mission_id = a.mission_id or store.missions.create(
        f'manual test: {a.skill}', decided_by='human-config', pilot=a.pilot, rationale='Phase 4 manual test')
    task_id = a.task_id or f'{mission_id}:{a.skill}:{int(time.time())}'
    req = TaskRequest(task_id=task_id, mission_id=mission_id, skill=a.skill, pilot=a.pilot,
                      params=json.loads(a.params), constraints=json.loads(a.constraints),
                      issued_by='manual-sender', rationale='manual Phase 4 test')
    role = 'resource' if a.url.endswith(str(a.resource_port)) else 'trading'
    store.tasks.create(mission_id, assignee=role, skill=a.skill, pilot=a.pilot,
                       payload={'params': req.params, 'constraints': req.constraints}, task_id=task_id)
    print(f'task_id = {task_id}')
    try:
        async with WorkerClient(a.url, poll_seconds=2) as client:
            print(f'worker  = {client.card.name} ({len(client.card.skills)} skills)')
            _mark(store, task_id, 'submitted')
            result, a2a_id = await client.run_task(
                req, timeout=a.timeout, on_update=lambda tid, state: print(f'  a2a task {tid}: {state}'))
    except WorkerUnavailable as e:
        _mark(store, task_id, 'unknown', error=str(e)[:300])
        print(f'[WORKER UNAVAILABLE] {e}\nResend later with: --task-id {task_id}')
        return
    print(f'\nstatus  = {result.status}\nsummary = {result.summary}')
    if result.error:
        print(f'error   = {result.error}')
    print('data    =', json.dumps(result.data, indent=2, default=str)[:3000])
    print('evidence=', json.dumps(result.evidence, indent=2, default=str)[:2000])
    store.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--url', required=True)
    p.add_argument('--pilot', required=True)
    p.add_argument('--skill', required=True)
    p.add_argument('--params', default='{}')
    p.add_argument('--constraints', default='{}')
    p.add_argument('--task-id')
    p.add_argument('--mission-id')
    p.add_argument('--timeout', type=float, default=900)
    p.add_argument('--resource-port', type=int, default=9101)
    asyncio.run(main(p.parse_args()))
