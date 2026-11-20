"""Offline tests for mas.mcp_gateway against a fake game (no network)."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from mas.mcp_gateway import AmbiguousOutcome, GameError, GameGateway, GatewayError, InvalidParams
from mas.parsers import parse_status
from mas.store import connect
from tests.fake_mcp import FakeGame, make_connector


def sells(game) -> int:
    """Number of sales the fake server actually executed (rejected requests don't count)."""
    return game.sales_applied


async def scenario(tmp: Path):
    db = connect(tmp / 'state.sqlite3')
    log = str(tmp / 'events.jsonl')
    game = FakeGame()
    waits: list[float] = []

    async def fake_sleep(s):
        waits.append(s)

    def gw_factory(agent='trading'):
        return GameGateway('Pilot-X', agent=agent, db=db, connector=make_connector(game),
                           password_provider=lambda u: 'pw-secret', sleep=fake_sleep, log_path=log)

    async with gw_factory() as gw:
        # 1. login + authenticated query; session_id injected by gateway
        r = await gw.query('spacemolt', 'get_status', task_id='t-1')
        assert parse_status(r.text)['credits'] == 250
        assert game.calls[-1][1]['session_id'] == game.valid_session
        print('[PASS] login + authenticated query')

        # 2. schema validation happens before anything is sent
        n = len(game.calls)
        for bad in ({'nonsense': 1}, {'quantity': 'ten'}, {'quantity': True}, {'session_id': 'x'}):
            try:
                await gw.act('spacemolt', 'sell', bad, idempotency_key=f'bad-{bad}')
                raise AssertionError(f'expected InvalidParams for {bad}')
            except InvalidParams:
                pass
        try:
            await gw.query('spacemolt_catalog', None, {'type': 'planets'})
            raise AssertionError('enum not checked')
        except InvalidParams:
            pass
        try:
            await gw.query('spacemolt', 'get_map', {'id': 'market_prime'})
            raise AssertionError('get_map must reject id (server wants system_id)')
        except InvalidParams:
            pass
        assert len(game.calls) == n, 'invalid params must never reach the server'
        await gw.query('spacemolt', 'get_map', {'system_id': 'market_prime'})
        assert game.calls[-1][1]['system_id'] == 'market_prime'
        print('[PASS] schema validation blocks bad params; per-action extras allowed')

        # 3. query() refuses state-changing actions
        try:
            await gw.query('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 1})
            raise AssertionError('query allowed a mutation')
        except GatewayError:
            pass
        print('[PASS] query() rejects mutations')

        # 4. idempotent act: second call with same key does not hit the game
        await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 5}, idempotency_key='m1:sell', task_id='t-2')
        again = await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 5}, idempotency_key='m1:sell')
        assert sells(game) == 1 and game.cargo == 15 and 'Sold 5x' in again.text
        print('[PASS] duplicate act() skipped (no double sale)')

        # 5. expired session -> re-login -> retry (server had rejected, so retry is safe)
        game.expire_session_once = True
        before = game.session_counter
        await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 1}, idempotency_key='m2:sell')
        assert game.session_counter == before + 1 and game.cargo == 14 and sells(game) == 2
        game.expire_session_once, game.expire_code = True, 'not_authenticated'   # what the live server sends
        before = game.session_counter
        await gw.query('spacemolt', 'get_status')
        assert game.session_counter == before + 1
        print('[PASS] expired session recovered by re-login (session_invalid and not_authenticated)')

        # 6. rate limit -> wait retry_after -> retry
        game.rate_limit_once = True
        await gw.query('spacemolt', 'get_status')
        assert waits[-1] == 3, waits
        print('[PASS] rate limit waits retry_after')

        # 7. game error -> failed, nothing applied; same key may be retried later
        try:
            await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 999}, idempotency_key='m3:sell')
            raise AssertionError('expected GameError')
        except GameError as e:
            assert e.code == 'insufficient_cargo'
        assert gw.ledger.get('m3:sell').status == 'failed'
        await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 4}, idempotency_key='m3:sell')
        assert gw.ledger.get('m3:sell').status == 'confirmed' and game.cargo == 10
        print('[PASS] rejected action marked failed, retry allowed')

        # 8. timeout AFTER server applied it -> unknown, never blindly retried
        game.timeout_next_mutation = True
        try:
            await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 2}, idempotency_key='m4:sell')
            raise AssertionError('expected AmbiguousOutcome')
        except AmbiguousOutcome:
            pass
        assert game.cargo == 8 and gw.ledger.get('m4:sell').status == 'unknown'
        n = sells(game)
        try:
            await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 2}, idempotency_key='m4:sell')
            raise AssertionError('ambiguous key must block re-execution')
        except AmbiguousOutcome:
            pass
        assert sells(game) == n and [r['idempotency_key'] for r in gw.ledger.unsettled()] == ['m4:sell']
        # caller re-observes: cargo dropped 10 -> 8, so the sale happened
        cargo_now = parse_status((await gw.query('spacemolt', 'get_status')).text)['cargo_used']
        assert cargo_now == 8
        gw.ledger.resolve('m4:sell', 'confirmed', 'cargo dropped by 2 on re-observation')
        print('[PASS] ambiguous timeout -> unknown -> re-observe -> resolved')

    # 9. "restart": a brand-new gateway process with the same DB does not replay
    async with gw_factory(agent='trading-restarted') as gw2:
        n = sells(game)
        await gw2.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 5}, idempotency_key='m1:sell')
        await gw2.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 2}, idempotency_key='m4:sell')
        assert sells(game) == n and game.cargo == 8
    print('[PASS] restart with same DB: completed actions not replayed')

    text = Path(log).read_text()
    assert 'pw-secret' not in text and 'sess-0000' not in text, 'secrets leaked into log'
    print('[PASS] no password/session id in events log')


def run():
    with TemporaryDirectory() as tmp:
        asyncio.run(scenario(Path(tmp)))


if __name__ == '__main__':
    run()
