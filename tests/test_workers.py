"""Offline tests for the Phase 4 workers against the fake world (no network, no real game).

Two Store connections to one SQLite file stand in for the two worker processes.
The last test runs a real A2A HTTP exchange through an in-memory ASGI transport.
"""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from mas import resource_skills, trading_skills
from mas.a2a_client import WorkerClient
from mas.a2a_protocol import TaskRequest
from mas.mcp_gateway import GameGateway
from mas.store import Store
from mas.worker import GameWorkerExecutor, build_app
from tests.fake_mcp import make_connector
from tests.fake_world import FakeWorld

PILOT = 'Pilot-X'


def count(world, action):
    return sum(1 for _, a in world.calls if a.get('action') == action)


async def nosleep(_):
    return None


def req(task_id, skill, params=None, constraints=None, mission='M-test'):
    return TaskRequest(task_id=task_id, mission_id=mission, skill=skill, pilot=PILOT,
                       params=params or {}, constraints=constraints or {})


async def scenario(tmp: Path):
    world = FakeWorld(deposits={'Copper Ore': 20, 'Iron Ore': 3, 'Silicon Ore': 2})
    db, log = tmp / 'state.sqlite3', str(tmp / 'events.jsonl')
    store_r = Store(db, agent='resource-agent', log_path=log)     # "process" 1
    store_t = Store(db, agent='trading-agent', log_path=log)      # "process" 2

    def factory_for(store, role):
        async def factory(pilot):
            gw = GameGateway(pilot, agent=f'{role}-agent', db=store.db, connector=make_connector(world),
                             password_provider=lambda u: 'pw', sleep=nosleep, log_path=log)
            await gw.connect()
            return gw
        return factory

    resource = GameWorkerExecutor('resource', store_r, resource_skills.SKILLS, factory_for(store_r, 'resource'))
    trading = GameWorkerExecutor('trading', store_t, trading_skills.SKILLS, factory_for(store_t, 'trading'))
    mid = store_t.missions.create('first_cargo for Pilot-X', decided_by='rule', pilot=PILOT)

    # 1. full mission flow: accept -> mine -> return -> complete ---------------------------
    r = await trading.run(req('t-accept', 'accept_mission', {'template_id': 'first_cargo'}, mission=mid))
    assert r.ok, r
    instance = r.data['instance_id']
    r = await resource.run(req('t-mine', 'mine', {'poi': 'commerce_fields', 'target_item': 'Copper Ore',
                                                  'target_qty': 15}, {'max_cycles': 30}, mission=mid))
    assert r.ok and r.data['stop_reason'] == 'target_reached' and r.data['mined']['Copper Ore'] == 15, r
    assert r.evidence['before']['cargo_used'] == 0 and r.evidence['after']['cargo_used'] == 15, r.evidence
    r = await resource.run(req('t-home', 'return_to_station', mission=mid))
    assert r.ok and world.docked and world.poi == 'grand_exchange', r
    r = await trading.run(req('t-complete', 'complete_mission', {'instance_id': instance}, mission=mid))
    assert r.ok and r.data['credits_gained'] == 1000 and world.credits == 1250, (r, world.credits)
    print('[PASS] mission flow across two workers: accept -> mine 15 copper -> dock -> complete (+1000 cr)')

    # 2. selling rules ----------------------------------------------------------------------
    world.cargo['silicon_ore'] = 5
    r = await trading.run(req('t-sell-si', 'sell', {'item_id': 'silicon_ore', 'quantity': 'all', 'min_price': 8}))
    assert r.ok and r.data['sold'] == 5 and world.credits == 1300, (r, world.credits)
    sells = count(world, 'sell')
    r = await trading.run(req('t-sell-cu', 'sell', {'item_id': 'copper_ore', 'quantity': 5, 'min_price': 1}))
    assert not r.ok and r.error['code'] == 'no_acceptable_bid' and count(world, 'sell') == sells, r
    print('[PASS] sell uses existing bids, refuses items without an acceptable bid (nothing sent)')

    # 3. safety refusals --------------------------------------------------------------------
    r = await trading.run(req('t-smuggle', 'accept_mission', {'template_id': 'smuggling_courier_x~abc'}))
    assert not r.ok and r.error['code'] == 'unsafe_mission' and count(world, 'accept_mission') == 1, r
    r = await trading.run(req('t-buy-big', 'buy_order', {'item_id': 'copper_ore', 'quantity': 10, 'price_each': 4},
                              {'max_spend': 10}))
    assert not r.ok and r.error['code'] == 'over_budget', r
    r = await trading.run(req('t-buy-nocap', 'buy_order', {'item_id': 'copper_ore', 'quantity': 1, 'price_each': 4}))
    assert not r.ok and r.error['code'] == 'bad_params', r
    print('[PASS] refuses smuggling missions and purchases over max_spend / without a cap')

    # 4. task-level dedupe: resending a finished task does not touch the game -----------------
    n = len(world.calls)
    r = await trading.run(req('t-sell-si', 'sell', {'item_id': 'silicon_ore', 'quantity': 'all', 'min_price': 8}))
    assert r.ok and r.data['sold'] == 5 and len(world.calls) == n, 'resend must return the stored result'
    print('[PASS] resent completed task returns stored result, zero game calls')

    # 5. pilot lease: a second agent cannot steer a busy pilot -------------------------------
    store_t.leases.acquire(PILOT, 'someone-else', ttl=60)
    r = await resource.run(req('t-busy', 'status'))
    assert not r.ok and r.error['code'] == 'pilot_busy', r
    store_t.leases.release(PILOT, 'someone-else')
    print('[PASS] pilot lease blocks a second agent')

    # 6. ambiguous mine (reply lost after the server applied it) -> reconciled, not repeated --
    cargo0, mines0 = world._cargo_used(), count(world, 'mine')
    world.timeout_action = 'mine'
    r = await resource.run(req('t-mine-amb', 'mine', {'poi': 'commerce_fields'}, {'max_cycles': 3}))
    assert r.ok, r
    assert count(world, 'mine') - mines0 == 3 and world._cargo_used() - cargo0 == 3, \
        (count(world, 'mine') - mines0, world._cargo_used() - cargo0)
    assert store_r.actions.get('t-mine-amb:mine:0').status == 'confirmed'
    print('[PASS] lost reply on mine: verified by cargo, ledger resolved, no extra mining')

    # 7. worker crash mid-task -> restart -> resend same task -> resumes without repeating ------
    tid = 't-mine-crash'
    store_r.tasks.create('M-test', assignee='resource', skill='mine', pilot=PILOT, payload={}, task_id=tid)
    store_r.tasks.mark(tid, 'working')
    gw = await resource.gateway(PILOT)
    await gw.act('spacemolt', 'mine', {}, idempotency_key=f'{tid}:mine:0', task_id=tid)  # done before the "crash"
    resource2 = GameWorkerExecutor('resource', Store(db, agent='resource-agent', log_path=log),
                                   resource_skills.SKILLS, factory_for(store_r, 'resource'))
    assert resource2.recover_after_restart() == [tid] and resource2.store.tasks.get(tid)['status'] == 'unknown'
    mines0 = count(world, 'mine')
    r = await resource2.run(req(tid, 'mine', {'poi': 'commerce_fields'}, {'max_cycles': 2}))
    assert r.ok and count(world, 'mine') - mines0 == 1, (r, count(world, 'mine') - mines0)
    assert resource2.store.tasks.get(tid)['status'] == 'completed'
    print('[PASS] restart: orphaned task marked unknown; resend replays cycle 0 from ledger, mines only cycle 1')

    # 8. real A2A HTTP exchange (in-memory transport) ----------------------------------------
    app, _ = build_app('trading', 9102, store_t, trading_skills.SKILLS, gateway_factory=factory_for(store_t, 'trading'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:9102',
                                 timeout=10) as http:
        async with WorkerClient('http://127.0.0.1:9102', http=http, poll_seconds=0.01) as client:
            assert client.card.name == 'SpaceMolt Trading Agent'
            assert {s.id for s in client.card.skills} == set(trading_skills.SKILLS)
            result, a2a_id = await client.run_task(req('t-a2a-status', 'status'), timeout=10)
            assert result.ok and 'cr' in result.summary and a2a_id, result
            bad, _ = await client.run_task(req('t-a2a-bad', 'mine'), timeout=10)   # trading has no 'mine'
            assert not bad.ok and bad.error['code'] == 'bad_request', bad
    assert store_t.tasks.get('t-a2a-status')['a2a_task_id'] == a2a_id
    print('[PASS] A2A over HTTP: agent card discovery, task -> JSON result artifact, bad skill rejected')

    text = Path(log).read_text()
    assert 'sess-0000' not in text and '"pw"' not in text
    print('[PASS] no session ids or passwords in the events log')
    store_r.close()
    store_t.close()


def run():
    with TemporaryDirectory() as tmp:
        asyncio.run(scenario(Path(tmp)))


if __name__ == '__main__':
    run()
