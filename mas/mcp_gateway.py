"""MCP gateway: the ONLY module that talks to the SpaceMolt game.

One `GameGateway` per pilot. Agents never call MCP directly; they call

    await gw.query('spacemolt', 'get_status')                       # read-only
    await gw.act('spacemolt', 'sell', {'id': 'copper_ore', 'quantity': 10},
                 idempotency_key='m17:sell:copper_ore', task_id='a2a-...')  # state-changing

What it guarantees
------------------
1. Authentication: logs in with the stored password, injects `session_id`
   into every call, and logs in again automatically on `session_invalid`.
2. Schema validation: arguments are checked against the tool's published
   `input_schema` (unknown keys, missing required keys, wrong types, enums)
   BEFORE anything is sent. Invalid params never reach the server.
3. Idempotency: `act()` records every state-changing call in the SQLite
   action ledger. A key that is already confirmed is never executed again.
4. Honest failure handling:
     - game error reply (`Error: code: msg`) -> the server rejected it, nothing happened
       -> ledger 'failed'; retried only for session/rate-limit/transit codes.
     - timeout / connection drop during act() -> we do NOT know if it happened
       -> ledger 'unknown' and AmbiguousOutcome is raised; the caller must re-observe
          the game (get_status / cargo) and call ledger.resolve(). Never blind-retry.
     - query() is read-only, so timeouts are retried with backoff.
5. Observability: every call is written to logs/events.jsonl with agent, task id,
   tool/action, redacted args, outcome, error code and duration.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable

from mas import secrets_store
from mas.action_params import extra_params, rejected_params
from mas.mcp_session import MCP_URL, ToolResult, call, extract, redact
from mas.parsers import parse_error, retry_after_seconds
from mas.store import ActionLedger, connect
from scripts.evidence import record

TICK_SECONDS = 10

# Read-only actions: safe to retry. Anything not listed here must go through act().
READ_ONLY_PREFIXES = ('get_', 'view_', 'list', 'analyze_', 'estimate_', 'find_', 'search_')
READ_ONLY_ACTIONS = {'help', 'inspect', 'completed_missions', 'view_completed_mission', 'info', 'status',
                     'quote', 'track', 'profile', 'active'}
TOOLS_WITHOUT_ACTION = {'spacemolt_catalog'}

# Error codes meaning "not applied, try again shortly".
RETRY_LATER_HINTS = ('rate', 'cooldown', 'retry', 'in_transit', 'busy', 'tick')
# 'not_authenticated' is what the live server returned after ~30 min idle (2026-11-20);
# the docs overview lists session_required / session_invalid / not_authenticated.
SESSION_CODES = {'session_invalid', 'session_required', 'session_expired', 'not_logged_in', 'not_authenticated'}
AUTH_PARAMS = {'session_id', 'password', 'registration_code', 'token'}

def _transport_errors() -> tuple[type[BaseException], ...]:
    """Exceptions meaning 'the connection failed', as opposed to a game reply."""
    errs: list[type[BaseException]] = [asyncio.TimeoutError, OSError, ConnectionError]
    try:
        import httpx
        errs.append(httpx.HTTPError)
    except ImportError:
        pass
    try:
        import anyio
        errs += [anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream]
    except ImportError:
        pass
    try:
        from mcp.shared.exceptions import McpError
        errs.append(McpError)
    except ImportError:
        pass
    return tuple(errs)


TRANSPORT_ERRORS = _transport_errors()

_JSON_TYPES = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool,
               'array': list, 'object': dict}


class GatewayError(Exception):
    """Base class for gateway failures."""


class InvalidParams(GatewayError):
    """Arguments do not match the tool's input_schema (never sent to the server)."""


class GameError(GatewayError):
    """The server replied with an error: the action was NOT applied."""

    def __init__(self, code: str, message: str, result: ToolResult):
        super().__init__(f'{code}: {message}')
        self.code, self.message, self.result = code, message, result


class AmbiguousOutcome(GatewayError):
    """A state-changing call may or may not have happened. Re-observe before continuing."""

    def __init__(self, key: str, cause: str):
        super().__init__(f'outcome unknown for {key}: {cause}')
        self.key, self.cause = key, cause


def is_read_only(tool: str, action: str | None) -> bool:
    if tool in TOOLS_WITHOUT_ACTION:
        return True
    a = (action or '').lower()
    return a in READ_ONLY_ACTIONS or a.startswith(READ_ONLY_PREFIXES)


def validate_args(schema: dict, args: dict, *, tool: str = '', action: str | None = None) -> None:
    """Minimal JSON-schema check: keys, required, primitive types, enums.

    Keys allowed = published schema properties + confirmed per-action extras
    (mas/action_params.py) - keys the server is known to reject for this action.
    """
    props: dict = dict(schema.get('properties', {}) or {})
    for name, typ in extra_params(tool, action).items():
        props.setdefault(name, {'type': typ})
    rejected = rejected_params(tool, action) & set(args)
    if rejected:
        raise InvalidParams(f'{tool}.{action} does not accept {sorted(rejected)}; '
                            f'use {sorted(extra_params(tool, action))}')
    unknown = set(args) - set(props)
    if unknown:
        raise InvalidParams(f'unknown parameter(s) {sorted(unknown)}; allowed: {sorted(props)}')
    missing = [r for r in schema.get('required', []) if r not in args and r != 'session_id']
    if missing:
        raise InvalidParams(f'missing required parameter(s) {missing}')
    for key, value in args.items():
        spec = props[key]
        expected = _JSON_TYPES.get(spec.get('type'))
        wrong_type = expected is not None and not isinstance(value, expected)
        bool_as_number = spec.get('type') in ('integer', 'number') and isinstance(value, bool)
        if wrong_type or bool_as_number:
            raise InvalidParams(f'{key} must be {spec.get("type")}, got {type(value).__name__}')
        if 'enum' in spec and value not in spec['enum']:
            raise InvalidParams(f'{key} must be one of {spec["enum"]}, got {value!r}')
        if spec.get('type') == 'integer' and 'minimum' in spec and value < spec['minimum']:
            raise InvalidParams(f'{key} must be >= {spec["minimum"]}')


Connector = Callable[[AsyncExitStack], Awaitable[Any]]


async def default_connector(stack: AsyncExitStack):
    """Open a real MCP v2 session (streamable HTTP)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    read, write = await stack.enter_async_context(streamable_http_client(MCP_URL))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


class GameGateway:
    def __init__(self, pilot: str, *, agent: str, db=None,
                 connector: Connector = default_connector,
                 password_provider: Callable[[str], str | None] = secrets_store.get_password,
                 call_timeout: float = 120.0, max_retries: int = 3,  # travel replies take ~40 s
                 min_mutation_interval: float = TICK_SECONDS + 0.5,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 log_path: str | None = None):
        self.pilot, self.agent = pilot, agent
        self.ledger = ActionLedger(db if db is not None else connect())
        self._connector, self._password = connector, password_provider
        self.call_timeout, self.max_retries, self._sleep = call_timeout, max_retries, sleep
        self._log_kwargs = {'path': log_path} if log_path else {}
        self._stack: AsyncExitStack | None = None
        self._session = None
        self.session_id: str | None = None
        self.schemas: dict[str, dict] = {}
        self._lock = asyncio.Lock()  # one game call at a time per pilot (game allows 1 action/tick)
        self.min_mutation_interval = min_mutation_interval
        self._last_mutation = 0.0     # monotonic time of the last state-changing call

    # ---------------------------------------------------------------- lifecycle
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def connect(self):
        await self.close()
        self._stack = AsyncExitStack()
        self._session = await self._connector(self._stack)
        tools = await self._session.list_tools()
        self.schemas = {t.name: (t.input_schema or {}) for t in tools.tools}
        self._log('mcp.connected', {'tools': sorted(self.schemas)})
        await self.login()

    async def close(self):
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:
                pass
        self._stack, self._session = None, None

    async def login(self):
        password = self._password(self.pilot)
        if not password:
            raise GatewayError(f'no stored password for pilot {self.pilot}')
        r = await asyncio.wait_for(call(self._session, 'spacemolt_auth',
                                        {'action': 'login', 'username': self.pilot, 'password': password}),
                                   self.call_timeout)
        password = None
        sid = extract(r, 'session_id')
        if r.is_error or not sid:
            err = parse_error(r.text) or ('login_failed', r.text[:200])
            self._log('mcp.login_failed', {'error_code': err[0]})
            raise GameError(err[0], err[1], r)
        self.session_id = sid
        self._log('mcp.login', {})

    # ---------------------------------------------------------------- public API
    async def query(self, tool: str, action: str | None = None, args: dict | None = None, *,
                    task_id: str | None = None) -> ToolResult:
        """Read-only call. Retries on timeouts, dropped connections, expired sessions, rate limits."""
        if not is_read_only(tool, action):
            raise GatewayError(f'{tool}.{action} changes game state; use act() with an idempotency key')
        payload = self._prepare(tool, action, args or {})
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._send(tool, action, payload, task_id=task_id, key=None)
            except GameError as e:
                if not await self._recover_from(e, attempt):
                    raise
                last = e
            except TRANSPORT_ERRORS as e:
                last = e
                self._log('mcp.retry', {'tool': tool, 'action': action, 'attempt': attempt,
                                        'cause': type(e).__name__}, task_id)
                await self._sleep(min(2 ** attempt, 30))
                await self._reconnect_quietly()
        raise GatewayError(f'{tool}.{action} failed after {self.max_retries} attempts: {last}')

    async def act(self, tool: str, action: str, args: dict | None = None, *,
                  idempotency_key: str, task_id: str | None = None) -> ToolResult:
        """State-changing call, executed at most once per idempotency key."""
        payload = self._prepare(tool, action, args or {})
        claimed, rec = self.ledger.begin(idempotency_key, pilot=self.pilot, agent=self.agent, task_id=task_id,
                                         tool=tool, action=action, args=redact(payload))
        if not claimed:
            if rec.status == 'confirmed':
                self._log('mcp.duplicate_skipped', {'tool': tool, 'action': action, 'key': idempotency_key},
                          task_id)
                return ToolResult(tool, action, False, rec.result_text or '', None)
            raise AmbiguousOutcome(idempotency_key, f'previous attempt is {rec.status}; re-observe and resolve')

        for attempt in range(1, self.max_retries + 1):
            # Pace mutations: the game accepts one per tick per pilot.
            gap = self.min_mutation_interval - (time.monotonic() - self._last_mutation)
            if gap > 0:
                await self._sleep(gap)
            # Measure the interval from when the call STARTS: the server itself holds a mutation
            # until the tick resolves (~10 s), so timing from the reply would double each cycle.
            self._last_mutation = time.monotonic()
            try:
                result = await self._send(tool, action, payload, task_id=task_id, key=idempotency_key)
                self.ledger.finish(idempotency_key, 'confirmed', result_text=result.text)
                return result
            except GameError as e:
                # Server said no -> nothing happened. Retry only transient reasons.
                if attempt < self.max_retries and await self._recover_from(e, attempt):
                    continue
                self.ledger.finish(idempotency_key, 'failed', result_text=e.result.text, error_code=e.code)
                raise
            except TRANSPORT_ERRORS as e:
                self.ledger.finish(idempotency_key, 'unknown', error_code=type(e).__name__)
                self._log('mcp.ambiguous', {'tool': tool, 'action': action, 'key': idempotency_key,
                                            'cause': type(e).__name__}, task_id)
                await self._reconnect_quietly()
                raise AmbiguousOutcome(idempotency_key, type(e).__name__) from e
        raise AssertionError('unreachable')

    # ---------------------------------------------------------------- internals
    def _prepare(self, tool: str, action: str | None, args: dict) -> dict:
        if tool not in self.schemas:
            raise InvalidParams(f'unknown tool {tool!r}')
        if AUTH_PARAMS & set(args):
            raise InvalidParams('do not pass session_id/password; the gateway handles auth')
        payload = dict(args)
        if tool not in TOOLS_WITHOUT_ACTION:
            payload['action'] = action
        validate_args(self.schemas[tool], payload, tool=tool, action=action)
        return payload

    async def _send(self, tool: str, action: str | None, payload: dict, *,
                    task_id: str | None, key: str | None) -> ToolResult:
        async with self._lock:
            if self._session is None:
                await self.connect()
            full = dict(payload)
            if 'session_id' in self.schemas[tool].get('properties', {}):
                full['session_id'] = self.session_id
            t0 = time.monotonic()
            result = await asyncio.wait_for(call(self._session, tool, full), self.call_timeout)
            ms = int((time.monotonic() - t0) * 1000)
        err = parse_error(result.text) if result.is_error or result.text.lstrip().startswith('Error:') else None
        self._log('mcp.call', {'tool': tool, 'action': action, 'args': redact(payload), 'key': key,
                               'ok': err is None, 'error_code': err[0] if err else None, 'ms': ms,
                               'response': redact(result.text)[:600]}, task_id)
        if err or result.is_error:
            code, msg = err or ('unknown_error', result.text[:300])
            raise GameError(code, msg, result)
        return result

    async def _recover_from(self, e: GameError, attempt: int) -> bool:
        """Return True if the error is transient and we fixed/waited for it."""
        if e.code in SESSION_CODES:
            self._log('mcp.relogin', {'reason': e.code})
            await self.login()
            return True
        if any(h in e.code for h in RETRY_LATER_HINTS):
            wait = retry_after_seconds(e.result.text) or TICK_SECONDS
            self._log('mcp.wait', {'reason': e.code, 'seconds': wait, 'attempt': attempt})
            await self._sleep(wait)
            return True
        return False

    async def _reconnect_quietly(self):
        try:
            await self.connect()
        except Exception as e:  # next call will try again
            self._log('mcp.reconnect_failed', {'cause': type(e).__name__})
            await self.close()

    def _log(self, event: str, data: dict, task_id: str | None = None):
        record(event, agent=self.agent, task_id=task_id, data={'pilot': self.pilot, **data}, **self._log_kwargs)
