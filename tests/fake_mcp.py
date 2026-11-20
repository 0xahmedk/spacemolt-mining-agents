"""A fake SpaceMolt MCP session for offline tests (no network, no game)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

SCHEMAS = {
    'spacemolt_auth': {'type': 'object', 'required': ['action'], 'properties': {
        'action': {'type': 'string', 'enum': ['register', 'login', 'logout', 'claim', 'help']},
        'username': {'type': 'string'}, 'password': {'type': 'string'}, 'session_id': {'type': 'string'}}},
    'spacemolt': {'type': 'object', 'required': ['session_id', 'action'], 'properties': {
        'action': {'type': 'string'}, 'id': {'type': 'string'}, 'quantity': {'type': 'integer'},
        'text': {'type': 'string'}, 'session_id': {'type': 'string'}}},
    'spacemolt_market': {'type': 'object', 'required': ['session_id', 'action'], 'properties': {
        'action': {'type': 'string'}, 'item_id': {'type': 'string'}, 'quantity': {'type': 'integer'},
        'price_each': {'type': 'integer'}, 'category': {'type': 'string'}, 'order_id': {'type': 'string'},
        'session_id': {'type': 'string'}}},
    'spacemolt_catalog': {'type': 'object', 'required': ['type'], 'properties': {
        'type': {'type': 'string', 'enum': ['ships', 'items']}, 'id': {'type': 'string'},
        'session_id': {'type': 'string'}}},
}

STATUS = ('Pilot-X [nebula] | {credits}cr | Haven\n'
          'Ship: Prospect (prospect) | Hull: 95/95 | Shield: 50/50 (+1/tick) | Armor: 4 | Speed: 1\n'
          'Fuel: 130/130 | Cargo: {cargo}/110 | CPU: 4/13 | Power: 10/26\n'
          'Docked at: grand_exchange_station\n')


def _result(text: str, is_error: bool = False):
    return SimpleNamespace(content=[SimpleNamespace(text=text)], is_error=is_error, structured_content=None)


@dataclass
class FakeGame:
    """Tiny game model plus switches to inject failures."""
    credits: int = 250
    cargo: int = 20
    session_counter: int = 0
    valid_session: str | None = None
    calls: list = field(default_factory=list)  # every request received (incl. rejected ones)
    sales_applied: int = 0                     # sells the server actually executed
    expire_session_once: bool = False
    expire_code: str = 'session_invalid'
    rate_limit_once: bool = False
    timeout_next_mutation: bool = False      # simulate network drop AFTER the server applied it
    connections: int = 0

    def handle(self, tool: str, args: dict):
        self.calls.append((tool, dict(args)))
        action = args.get('action')
        if tool == 'spacemolt_auth' and action == 'login':
            if args.get('password') != 'pw-secret':
                return _result('Error: invalid_credentials: wrong password', True)
            self.session_counter += 1
            self.valid_session = f'sess-{self.session_counter:06d}'
            return _result(f'Logged in.\nSession ID: {self.valid_session}')
        if tool == 'spacemolt_catalog':
            return _result('Catalog: items (page 1/1, 1 total)\nid\tname\ncopper_ore\tCopper Ore')
        if args.get('session_id') != self.valid_session:
            return _result('Error: session_invalid: Your session has expired.', True)
        if self.expire_session_once:
            self.expire_session_once = False
            self.valid_session = None
            return _result(f'Error: {self.expire_code}: Your session has expired.', True)
        if self.rate_limit_once:
            self.rate_limit_once = False
            return _result('Error: rate_limited: one action per tick. retry_after: 3', True)
        if action == 'get_status':
            return _result(STATUS.format(credits=self.credits, cargo=self.cargo))
        if action == 'sell':
            qty = args.get('quantity', 0)
            if qty > self.cargo:
                return _result('Error: insufficient_cargo: you only have %d' % self.cargo, True)
            self.cargo -= qty
            self.credits += qty * 10
            self.sales_applied += 1
            return _result(f'Sold {qty}x {args.get("id")} for {qty * 10}cr.')
        return _result(f'OK {action}')


class FakeSession:
    def __init__(self, game: FakeGame):
        self.game = game

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, input_schema=s, description=n)
                                      for n, s in SCHEMAS.items()])

    async def call_tool(self, name, args):
        await asyncio.sleep(0)
        timeout_action = getattr(self.game, 'timeout_action', None)
        if timeout_action and timeout_action == args.get('action'):
            self.game.timeout_action = None
            self.game.handle(name, args)          # server applied it...
            raise asyncio.TimeoutError()          # ...but we never saw the reply
        if self.game.timeout_next_mutation and args.get('action') not in ('login', 'get_status'):
            self.game.timeout_next_mutation = False
            self.game.handle(name, args)          # server applied it...
            raise asyncio.TimeoutError()          # ...but we never saw the reply
        return self.game.handle(name, args)


def make_connector(game: FakeGame):
    async def connector(stack):
        game.connections += 1
        return FakeSession(game)
    return connector
