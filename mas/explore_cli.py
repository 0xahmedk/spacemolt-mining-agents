"""Manual SpaceMolt MCP explorer (Phase 1: learn the game).

FOR PRACTICE PILOTS ONLY. Never use this to play assessed pilots: manual
gameplay must not be presented as autonomous.

Interactive:
    python -m mas.explore_cli
One-shot (each -c runs a command, then exits):
    python -m mas.explore_cli -c "help spacemolt mine"
    python -m mas.explore_cli -c "login MyPractice1" -c "call spacemolt get_status"

Commands:
    tools                              list MCP tools
    help <tool> [topic]                server help (no login needed)
    dumphelp                           save full help for every tool to docs/mcp_help/
    register <username> [empire]       create a pilot (prompts hidden for registration code)
    claim                              link logged-in pilot to your website account (hidden prompt)
    login <username>                   log in using the stored password
    savepw <username>                  store an existing pilot's password (hidden prompt)
    whoami                             show the logged-in pilot
    call <tool> <action> [json-args]   call any action; session_id is added automatically
    raw <tool> <json-args>             call a tool with exact args (e.g. spacemolt_catalog)
    json on|off                        also print structured content
    quit
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import re
import shlex
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mas import secrets_store
from mas.mcp_session import MCP_URL, ToolResult, call, extract, redact
from scripts.evidence import record

ROOT = Path(__file__).resolve().parents[1]
LOG = str(ROOT / 'logs' / 'explore.jsonl')
EMPIRES = ('solarian', 'voidborn', 'crimson', 'nebula', 'outerrim')


class Explorer:
    def __init__(self, session: ClientSession):
        self.s = session
        self.username: str | None = None
        self.session_id: str | None = None
        self.show_json = False
        self.tools: dict = {}

    async def load_tools(self):
        self.tools = {t.name: t for t in (await self.s.list_tools()).tools}

    # ---- output -------------------------------------------------------
    def show(self, r: ToolResult):
        flag = 'ERROR' if r.is_error else 'OK'
        print(f'--- {r.tool}.{r.action or ""} [{flag}]')
        print(redact(r.text))
        if self.show_json and r.structured is not None:
            print(json.dumps(redact(r.structured), indent=2)[:8000])

    def log(self, r: ToolResult, args: dict):
        record('explore.call', agent='human-explore', path=LOG, data={
            'pilot': self.username, 'tool': r.tool, 'action': r.action, 'args': redact(args),
            'is_error': r.is_error, 'text': redact(r.text)[:2000]})

    async def invoke(self, tool: str, args: dict, *, quiet=False, log=True) -> ToolResult:
        if tool not in self.tools:
            raise ValueError(f'unknown tool {tool!r}; try: tools')
        if 'session_id' in (self.tools[tool].input_schema or {}).get('properties', {}) \
                and 'session_id' not in args and self.session_id:
            args = {**args, 'session_id': self.session_id}
        r = await call(self.s, tool, args)
        if log:
            self.log(r, args)
        if not quiet:
            self.show(r)
        return r

    # ---- commands -----------------------------------------------------
    async def cmd_tools(self, *_):
        for name, t in self.tools.items():
            print(f'{name:20} {(t.description or "").splitlines()[0][:90]}')

    async def cmd_help(self, tool='spacemolt', topic=None, *_):
        args = {'action': 'help'} if tool != 'spacemolt_catalog' else {'type': 'items', 'topic': 'help'}
        if topic:
            args['topic'] = topic
        if 'session_id' in (self.tools[tool].input_schema or {}).get('properties', {}):
            args.setdefault('session_id', self.session_id or 'none')
        await self.invoke(tool, args, log=False)

    async def cmd_dumphelp(self, *_):
        out = ROOT / 'docs' / 'mcp_help'
        out.mkdir(parents=True, exist_ok=True)
        for name, t in self.tools.items():
            schema = t.input_schema or {}
            args = {'action': 'help'}
            if name == 'spacemolt_catalog':
                args = {'type': 'items', 'topic': 'help'}
            if 'session_id' in schema.get('properties', {}):
                args['session_id'] = 'none'
            r = await call(self.s, name, args)
            body = (f'# {name}\n\n## Description\n{t.description}\n\n## Input schema\n'
                    f'{json.dumps(schema, indent=2)}\n\n## help output\n{redact(r.text)}\n')
            (out / f'{name}.md').write_text(body, encoding='utf-8')
            print(f'saved {out / (name + ".md")} ({len(body)} chars)')

    async def cmd_register(self, username=None, empire='nebula', *_):
        if not username:
            raise ValueError('usage: register <username> [empire]')
        if empire not in EMPIRES:
            raise ValueError(f'empire must be one of {EMPIRES}')
        if secrets_store.get_password(username):
            raise ValueError(f'a password for {username} is already stored; refusing to re-register')
        print(f'About to CREATE a permanent pilot {username!r} in {empire}. This cannot be undone.')
        ok = (await asyncio.to_thread(input, 'Type the username again to confirm: ')).strip()
        if ok != username:
            print('Cancelled.')
            return
        code = (await asyncio.to_thread(getpass.getpass, 'Registration code (hidden): ')).strip().strip('`')
        if not code:
            raise ValueError('registration code required')
        r = await call(self.s, 'spacemolt_auth',
                       {'action': 'register', 'username': username, 'empire': empire, 'registration_code': code})
        code = ''
        password = extract(r, 'password')
        if r.is_error:
            print('Registration returned an error (nothing stored):')
            self.show(r)
            return
        if not password:
            path = secrets_store.save_raw_private(f'register_{username}.txt', r.text)
            print(f'Registration may have succeeded but no password was parsed. Raw response saved privately to {path}. '
                  'Do NOT register again; read that file and run savepw.')
            return
        where = secrets_store.set_password(username, password)
        password = ''
        self.username, self.session_id = username, extract(r, 'session_id')
        record('explore.register', agent='human-explore', path=LOG, data={'pilot': username, 'empire': empire,
                                                                             'stored_in': where})
        print(f'[PASS] Registered {username} ({empire}); password stored in {where}.')
        self.show(r)

    async def cmd_claim(self, *_):
        if not self.session_id:
            raise ValueError('login first')
        code = (await asyncio.to_thread(getpass.getpass, 'Registration code (hidden): ')).strip().strip('`')
        r = await call(self.s, 'spacemolt_auth', {'action': 'claim', 'registration_code': code,
                                                  'session_id': self.session_id})
        self.show(r)

    async def cmd_savepw(self, username=None, *_):
        if not username:
            raise ValueError('usage: savepw <username>')
        pw = await asyncio.to_thread(getpass.getpass, f'Password for {username} (hidden): ')
        print('stored in', secrets_store.set_password(username, pw))

    async def cmd_login(self, username=None, *_):
        if not username:
            raise ValueError('usage: login <username>')
        pw = secrets_store.get_password(username)
        if not pw:
            raise ValueError(f'no stored password for {username}; use savepw first')
        r = await call(self.s, 'spacemolt_auth', {'action': 'login', 'username': username, 'password': pw})
        pw = ''
        sid = extract(r, 'session_id')
        if r.is_error or not sid:
            self.show(r)
            raise RuntimeError('login failed')
        self.username, self.session_id = username, sid
        record('explore.login', agent='human-explore', path=LOG, data={'pilot': username})
        print(f'[PASS] Logged in as {username}')
        self.show(r)

    async def cmd_whoami(self, *_):
        print(self.username or '(not logged in)')

    @staticmethod
    def _json_args(rest) -> dict:
        text = ' '.join(rest).strip()
        if not text:
            return {}
        if re.search(r'\b(call|raw|login|help)\s+\S', text):
            raise ValueError('this line contains a second command (pasted lines got merged). '
                             'Nothing was sent. Enter one command per line.')
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f'arguments are not valid JSON ({e.msg}). Nothing was sent. '
                             'Example: {"id":"commerce_fields"}') from None

    async def cmd_call(self, tool=None, action=None, *rest):
        if not tool or not action:
            raise ValueError('usage: call <tool> <action> [json-args]')
        await self.invoke(tool, {'action': action, **self._json_args(rest)})

    async def cmd_raw(self, tool=None, *rest):
        if not tool:
            raise ValueError('usage: raw <tool> <json-args>')
        await self.invoke(tool, self._json_args(rest))

    async def cmd_json(self, mode='on', *_):
        self.show_json = mode == 'on'

    async def run(self, line: str) -> bool:
        if not line.strip():
            return True
        first = line.split(None, 1)[0].lower()
        if first in ('call', 'raw'):
            # keep the JSON tail verbatim (shlex would strip its quotes)
            parts = line.split(None, 3 if first == 'call' else 2)
        else:
            parts = shlex.split(line)
        name, args = parts[0].lower(), parts[1:]
        if name in ('quit', 'exit'):
            return False
        handler = getattr(self, f'cmd_{name}', None)
        if not handler:
            print('unknown command; see module docstring:', __doc__)
            return True
        try:
            await handler(*args)
        except Exception as e:  # keep the REPL alive; never print secrets
            print(f'[error] {type(e).__name__}: {redact(str(e))}')
        return True


async def main(commands: list[str]):
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ex = Explorer(session)
            await ex.load_tools()
            if commands:
                for c in commands:
                    print(f'>>> {c}')
                    if not await ex.run(c):
                        break
                return
            print('SpaceMolt MCP explorer. PRACTICE PILOTS ONLY. Type "quit" to exit.')
            while True:
                try:
                    line = await asyncio.to_thread(input, f'[{ex.username or "-"}]> ')
                except EOFError:
                    break
                if not await ex.run(line):
                    break


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('-c', action='append', default=[], help='run command then exit (repeatable)')
    a = p.parse_args()
    try:
        asyncio.run(main(a.c))
    except KeyboardInterrupt:
        sys.exit(130)
