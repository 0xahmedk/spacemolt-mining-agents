"""LLM access for the coordinator, inside the assignment's shared inference budget.

Budget rules (group-wide, all processes): 300 requests, 250,000 tokens, 2 requests per rolling
minute. They are enforced by the starter's ledger `scripts/budget.py` (logs/budget.sqlite3):
we reserve() before every call and complete() after it, so failed calls are counted too.

Design choices:
  * The LLM never acts directly. It CHOOSES one option from a menu the coordinator built from
    validated game state, and explains why. Anything it returns that is not on the menu is
    rejected and a deterministic fallback is used instead.
  * JSON-only answers, compact prompts (~1-2k tokens) and a per-run call cap.
  * No API key / budget exhausted / provider error -> returns None and the caller falls back.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

from scripts import budget
from scripts.evidence import record

DEFAULT_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b')
BUDGET_DB = 'logs/budget.sqlite3'


class LLM:
    def __init__(self, *, model: str = DEFAULT_MODEL, api_key: str | None = None, max_calls: int = 60,
                 agent: str = 'coordinator', budget_db: str = BUDGET_DB, client=None,
                 max_completion_tokens: int = 900, log_path: str | None = None):
        self.model, self.max_calls, self.agent = model, max_calls, agent
        self.budget_db, self.max_completion_tokens = budget_db, max_completion_tokens
        self._log_kw = {'path': log_path} if log_path else {}
        self.calls = 0
        self._client = client
        key = api_key if api_key is not None else os.environ.get('GROQ_API_KEY')
        if self._client is None and key:
            from groq import Groq
            self._client = Groq(api_key=key)
        key = None  # never keep the key around longer than needed

    @property
    def available(self) -> bool:
        return self._client is not None and self.calls < self.max_calls

    def usage(self) -> dict:
        db = budget.connection(self.budget_db)
        try:
            return budget.usage(db)
        finally:
            db.close()

    async def _reserve(self) -> int | None:
        """Reserve one request in the shared ledger, waiting out the 2-per-minute window."""
        for _ in range(4):
            u = self.usage()
            if u['requests'] >= budget.CAP_REQUESTS or u['tokens'] >= budget.CAP_TOKENS:
                record('llm.budget_exhausted', agent=self.agent, data=u, **self._log_kw)
                return None
            try:
                return budget.reserve(self.model, db_path=self.budget_db)
            except RuntimeError:
                await asyncio.sleep(31)   # rolling-minute limit: wait and try again
        return None

    async def choose_json(self, system: str, payload: dict, *, purpose: str, task_id: str | None = None) -> dict | None:
        """Ask for a JSON object. Returns the parsed dict or None (caller must fall back)."""
        if not self.available:
            return None
        reservation = await self._reserve()
        if reservation is None:
            return None
        self.calls += 1
        user = json.dumps(payload, separators=(',', ':'), default=str)
        t0 = time.monotonic()
        tokens_in = tokens_out = 0
        try:
            resp = await asyncio.to_thread(self._call, system, user)
            use = getattr(resp, 'usage', None)
            tokens_in = getattr(use, 'prompt_tokens', 0) or 0
            tokens_out = getattr(use, 'completion_tokens', 0) or 0
            budget.complete(reservation, tokens_in, tokens_out, ok=True, db_path=self.budget_db)
            text = resp.choices[0].message.content or ''
        except Exception as e:
            budget.complete(reservation, tokens_in, tokens_out, ok=False, db_path=self.budget_db)
            record('llm.error', agent=self.agent, task_id=task_id,
                   data={'purpose': purpose, 'error': type(e).__name__, 'detail': str(e)[:200]}, **self._log_kw)
            return None
        parsed = _parse_json(text)
        record('llm.call', agent=self.agent, task_id=task_id, **self._log_kw, data={
            'purpose': purpose, 'model': self.model, 'tokens_in': tokens_in, 'tokens_out': tokens_out,
            'ms': int((time.monotonic() - t0) * 1000), 'parsed': parsed is not None,
            'response': (text or '')[:400], 'run_calls': self.calls})
        return parsed

    def _call(self, system: str, user: str):
        kwargs = dict(model=self.model, temperature=0.2, max_completion_tokens=self.max_completion_tokens,
                      messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                      response_format={'type': 'json_object'})
        if 'gpt-oss' in self.model:
            kwargs['reasoning_effort'] = 'low'
        # One reservation = one HTTP request: no silent retries here, so the ledger stays honest.
        # If a model rejects JSON mode, the error is logged and the coordinator falls back.
        return self._client.chat.completions.create(**kwargs)


def _parse_json(text: str) -> dict | None:
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except (TypeError, ValueError):
        m = re.search(r'\{.*\}', text or '', re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, dict) else None
            except ValueError:
                return None
    return None
