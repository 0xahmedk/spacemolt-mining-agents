"""Thin helpers around an MCP ClientSession for SpaceMolt v2.

Phase 1 building block; Phase 2 grows this into the full gateway
(schema validation, idempotency keys, re-login, persistence).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MCP_URL = 'https://game.spacemolt.com/mcp/v2'

SECRET_KEYS = ('password', 'session_id', 'registration_code', 'token', 'api_key', 'secret')
_TEXT_SECRET = re.compile(
    r'(?i)("?(?:password|session_id|session id|registration_code|token)"?\s*[:=]\s*"?)([^\s",}]+)')


@dataclass
class ToolResult:
    tool: str
    action: str | None
    is_error: bool
    text: str
    structured: Any

    def data(self) -> Any:
        """Best-effort machine-readable payload: structured content, else JSON text, else None."""
        if self.structured is not None:
            return self.structured
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return None


def redact(value: Any) -> Any:
    """Remove secrets from dicts/lists/strings before printing or logging."""
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if any(s in str(k).lower() for s in SECRET_KEYS) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _TEXT_SECRET.sub(r'\1[REDACTED]', value)
    return value


def find_field(obj: Any, names: set[str], depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in names and isinstance(v, str) and v:
                return v
        for v in obj.values():
            found = find_field(v, names, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_field(v, names, depth + 1)
            if found:
                return found
    return None


def extract(result: ToolResult, name: str) -> str | None:
    """Find a field (e.g. session_id, password) in structured data or in the text body."""
    found = find_field(result.data(), {name})
    if found:
        return found
    # Text replies look like "Session ID: abc..." or "session_id=abc": accept '_' or ' ' between words.
    label = re.escape(name).replace('_', '[ _]')
    m = re.search(r'(?i)"?' + label + r'"?\s*[:=]\s*"?([A-Za-z0-9_\-\.!@#$%^&*+/=]{6,})', result.text)
    return m.group(1) if m else None


async def call(session, tool: str, args: dict) -> ToolResult:
    res = await session.call_tool(tool, args)
    text = '\n'.join(getattr(c, 'text', '') or '' for c in res.content)
    structured = getattr(res, 'structured_content', None)
    return ToolResult(tool=tool, action=args.get('action'), is_error=bool(res.is_error),
                      text=text, structured=structured)
