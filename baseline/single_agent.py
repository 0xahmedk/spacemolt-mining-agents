"""Baseline for the comparison: ONE process, NO A2A, NO LLM.

    python -m baseline.single_agent --pilot Prac-Ahmed1 --minutes 20

A fixed script that a single bot would run: if a mission is finished, claim it; else if a
mining mission is active, mine for it; else accept the first mining mission from the board;
else mine anything. It reuses the same game skills (same MCP gateway, parsers and safety rules)
so the comparison isolates what the multi-agent design adds: LLM planning over a menu of
options, separate worker processes over A2A, and recovery across processes.

Prints its start/end time; feed them to `python -m mas.report` for the comparison table.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time
from datetime import datetime, timezone

from mas import resource_skills, trading_skills
from mas.a2a_protocol import TaskRequest
from mas.coordinator import OBJ_MINE, tally_from_db
from mas.store import Store
from mas.worker import build_app

BELT = 'commerce_fields'


async def run(pilot: str, minutes: float, max_cycles: int):
    store = Store(agent='baseline')
    # Same skill code as the workers, but called in-process (no A2A, no second process).
    _, resource = build_app('resource', 0, store, resource_skills.SKILLS)
    _, trading = build_app('trading', 0, store, trading_skills.SKILLS)
    mid = store.missions.create('baseline: fixed single-agent script', decided_by='rule', pilot=pilot,
                                rationale='baseline for comparison (no LLM, no A2A)')
    n = 0

    async def do(executor, skill, params=None, constraints=None):
        nonlocal n
        n += 1
        req = TaskRequest(task_id=f'{mid}:{skill}:{n}', mission_id=mid, skill=skill, pilot=pilot,
                          params=params or {}, constraints=constraints or {}, issued_by='baseline')
        r = await executor.run(req)
        print(f'[baseline] {skill}: {r.status} - {r.summary}')
        return r

    start = time.time()
    print(f'[baseline] START {datetime.now(timezone.utc).isoformat()} ({start:.0f})')
    while time.time() - start < minutes * 60:
        active = await do(trading, 'active_missions')
        missions = active.data.get('missions', []) if active.ok else []
        ready = [m for m in missions if m['progress'] and all(d >= t for d, t in m['progress'])]
        if ready:
            await do(trading, 'complete_mission', {'instance_id': ready[0]['id']})
            continue
        mining = [(m, o, p) for m in missions for o, p in zip(
            [o for o in m['objectives'] if re.search(r': \d+/\d+$', o)], m['progress']) if OBJ_MINE.match(o)]
        if mining:
            m, obj, (done, total) = mining[0]
            r = await do(resource, 'mine', {'poi': BELT, 'target_item': OBJ_MINE.match(obj).group(2),
                                            'target_qty': total - done}, {'max_cycles': max_cycles})
            if r.ok and r.data.get('stop_reason') == 'belt_depleted':
                await do(resource, 'return_to_station')
                await asyncio.sleep(120)
            continue
        board = await do(trading, 'missions_board')
        offer = next((m for m in board.data.get('missions', []) if m.get('safe')
                      and any(OBJ_MINE.match(o) for o in m['objectives'])), None) if board.ok else None
        if offer:
            await do(trading, 'accept_mission', {'template_id': offer['id']})
            continue
        r = await do(resource, 'mine', {'poi': BELT}, {'max_cycles': max_cycles})
        if not r.ok or r.data.get('total', 0) == 0:
            await asyncio.sleep(120)     # nothing to do: wait for the belt to regenerate
    await do(resource, 'return_to_station')
    end = time.time()
    store.missions.transition(mid, 'assigned')
    store.missions.transition(mid, 'in_progress')
    store.missions.transition(mid, 'verifying')
    store.missions.transition(mid, 'done', result={'tally': tally_from_db(store.db, pilot, start, end)})
    print(f'[baseline] END {datetime.now(timezone.utc).isoformat()} ({end:.0f})')
    print(f'[baseline] tally this run: {tally_from_db(store.db, pilot, start, end)}')
    print(f'[baseline] report: python -m mas.report --pilot {pilot} --since {start:.0f} --until {end:.0f}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pilot', required=True)
    p.add_argument('--minutes', type=float, default=20)
    p.add_argument('--max-cycles', type=int, default=20)
    a = p.parse_args()
    asyncio.run(run(a.pilot, a.minutes, a.max_cycles))
