"""Offline end-to-end tests: coordinator -> (in-process) workers -> fake world, with a scripted LLM.

The dispatcher calls the worker executors directly instead of over HTTP (A2A over HTTP is
covered in test_workers.py); everything else is the real code.
"""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from mas import resource_skills, trading_skills
from mas.a2a_client import WorkerUnavailable
from mas.coordinator import Coordinator, load_config
from mas.mcp_gateway import GameGateway
from mas.store import Store
from mas.worker import GameWorkerExecutor
from tests.fake_mcp import make_connector
from tests.fake_world import FakeWorld

PILOT = 'Pilot-X'


async def nosleep(_):
    return None


class FakeLLM:
    """Scripted chooser: accept first_cargo, then mine for it; records every prompt."""
    available = True

    def __init__(self):
        self.prompts = []

    async def choose_json(self, system, payload, *, purpose, task_id=None):
        self.prompts.append(payload)
        ids = [o['id'] for o in payload['options']]
        for prefix in ('accept:first_cargo', 'mine_for:'):
            pick = next((i for i in ids if i.startswith(prefix)), None)
            if pick:
                return {'choice': pick, 'rationale': f'test plan picks {pick}'}
        return {'choice': 'not-an-option', 'rationale': 'invalid on purpose'}


class InProcessDispatcher:
    """Runs tasks on executor objects; can simulate an unreachable worker or a lost reply."""

    def __init__(self, executors):
        self.executors = executors
        self.unreachable_once: set[str] = set()     # skills: fail BEFORE the worker runs the task
        self.lose_reply_once: set[str] = set()      # skills: worker runs it, reply is lost

    async def run(self, role, req):
        if req.skill in self.unreachable_once:
            self.unreachable_once.discard(req.skill)
            raise WorkerUnavailable('simulated: worker down')
        result = await self.executors[role].run(req, a2a_task_id=f'local-{req.task_id}')
        if req.skill in self.lose_reply_once:
            self.lose_reply_once.discard(req.skill)
            raise WorkerUnavailable('simulated: reply lost after the worker finished')
        return result, f'local-{req.task_id}'


def setup(tmp: Path):
    world = FakeWorld(deposits={'Copper Ore': 20, 'Iron Ore': 3, 'Silicon Ore': 2})
    db, log = tmp / 'state.sqlite3', str(tmp / 'events.jsonl')
    stores = {r: Store(db, agent=f'{r}-agent', log_path=log) for r in ('resource', 'trading', 'coordinator')}

    def factory(role):
        async def make(pilot):
            gw = GameGateway(pilot, agent=f'{role}-agent', db=stores[role].db, connector=make_connector(world),
                             password_provider=lambda u: 'pw', sleep=nosleep, log_path=log)
            await gw.connect()
            return gw
        return make

    executors = {'resource': GameWorkerExecutor('resource', stores['resource'], resource_skills.SKILLS,
                                                factory('resource')),
                 'trading': GameWorkerExecutor('trading', stores['trading'], trading_skills.SKILLS,
                                               factory('trading'))}
    cfg = load_config(None)
    cfg['pilots'] = [PILOT]
    cfg['targets_per_pilot'] = {'credits_earned': 1000, 'ore_mined': 15, 'sales': 0}
    cfg['limits']['max_active_missions'] = 1
    return world, stores, executors, cfg, log


def mine_calls(world):
    return sum(1 for _, a in world.calls if a.get('action') == 'mine')


async def autonomous_run(tmp: Path):
    world, stores, executors, cfg, log = setup(tmp)
    llm = FakeLLM()
    coord = Coordinator(cfg, stores['coordinator'], InProcessDispatcher(executors), llm, sleep=nosleep, log_path=log)
    await coord.run(max_rounds=10)

    assert world.credits == 1250, world.credits
    assert coord.tally(PILOT)['ore_mined'] >= 15 and coord.tally(PILOT)['credits_earned'] == 1000, coord.tally(PILOT)
    missions = [m for m in stores['coordinator'].missions.recent(50) if (m.get('plan') or {}).get('option')]
    by = {m['plan']['option']['skill']: m for m in missions}
    assert by['accept_mission']['decided_by'] == 'llm' and 'first_cargo' in by['accept_mission']['rationale']
    assert by['mine']['decided_by'] == 'llm'
    assert by['complete_mission']['decided_by'] == 'rule' and 'forced' in by['complete_mission']['rationale']
    assert all(m['status'] == 'done' for m in missions), [(m['objective'], m['status']) for m in missions]
    assert world.docked
    first = llm.prompts[0]
    assert {'ship', 'progress_vs_target', 'options', 'belt'} <= set(first), first.keys()
    assert all({'id', 'action'} <= set(o) for o in first['options'])
    print('[PASS] autonomous run: LLM accepts first_cargo, LLM mines 15 copper, rule claims +1000 cr, stops at targets')
    print(f'       decisions={dict(coord.stats)} llm_prompts={len(llm.prompts)}')
    for s in stores.values():
        s.close()


class BadLLM:
    """Always answers with an option that is not on the menu."""
    available = True

    async def choose_json(self, system, payload, *, purpose, task_id=None):
        return {'choice': 'sell_everything_to_pirates', 'rationale': 'hallucinated'}


async def invalid_llm_answer(tmp: Path):
    world, stores, executors, cfg, log = setup(tmp)
    cfg['targets_per_pilot'] = {'credits_earned': 0, 'ore_mined': 3, 'sales': 0}
    world.deposits = {'Iron Ore': 9}

    coord = Coordinator(cfg, stores['coordinator'], InProcessDispatcher(executors), BadLLM(),
                        sleep=nosleep, log_path=log)
    await coord.run(max_rounds=6)
    assert coord.stats['fallback_decisions'] >= 1 and coord.tally(PILOT)['ore_mined'] >= 3, (coord.stats,
                                                                                         coord.tally(PILOT))
    print('[PASS] invalid LLM choice rejected -> deterministic fallback still makes progress')
    for s in stores.values():
        s.close()


async def crash_and_lost_reply(tmp: Path):
    world, stores, executors, cfg, log = setup(tmp)
    disp = InProcessDispatcher(executors)

    # (a) mine task cannot reach the worker -> task unknown, mission stays open
    disp.unreachable_once.add('mine')
    coord = Coordinator(cfg, stores['coordinator'], disp, FakeLLM(), sleep=nosleep, log_path=log)
    for _ in range(2):            # round 1: accept first_cargo; round 2: mine -> worker unreachable
        await coord.step(PILOT)
    open_ms = [m for m in stores['coordinator'].missions.open() if (m.get('plan') or {}).get('option')]
    assert len(open_ms) == 1 and open_ms[0]['plan']['option']['skill'] == 'mine', open_ms
    tid = stores['coordinator'].tasks.for_mission(open_ms[0]['mission_id'])[0]['task_id']
    assert stores['coordinator'].tasks.get(tid)['status'] == 'unknown'
    assert mine_calls(world) == 0

    # coordinator "crashes"; a new one starts and recovers: SAME task id resent, mined once
    coord2 = Coordinator(cfg, Store(tmp / 'state.sqlite3', agent='coordinator', log_path=log),
                         disp, FakeLLM(), sleep=nosleep, log_path=log)
    await coord2.recover()
    assert stores['coordinator'].tasks.get(tid)['status'] == 'completed'
    assert stores['coordinator'].missions.get(open_ms[0]['mission_id'])['status'] == 'done'
    mined_once = mine_calls(world)
    assert 0 < mined_once <= 20, mined_once
    print('[PASS] worker unreachable -> task unknown -> coordinator restart resends same task id, mission done')

    # (b) lost reply: worker completes, coordinator never hears back -> adopts stored result, no re-mining
    disp.lose_reply_once.add('complete_mission')
    for _ in range(3):
        await coord2.step(PILOT)
    credits_after = world.credits
    assert credits_after == 1250, credits_after
    await coord2.recover()
    done_completes = [m for m in stores['coordinator'].missions.recent(50)
                      if (m.get('plan') or {}).get('option', {}).get('skill') == 'complete_mission']
    assert done_completes and done_completes[0]['status'] == 'done', done_completes
    assert world.credits == 1250 and mine_calls(world) == mined_once
    print('[PASS] lost reply -> stored worker result adopted at recovery, reward claimed exactly once')
    for s in stores.values():
        s.close()


def run():
    for fn in (autonomous_run, invalid_llm_answer, crash_and_lost_reply):
        with TemporaryDirectory() as tmp:
            asyncio.run(fn(Path(tmp)))


if __name__ == '__main__':
    run()
