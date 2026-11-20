"""Per-action parameters that the published MCP input_schema does not list.

The `spacemolt` tool publishes ONE schema for ~60 actions (generic `id`, `quantity`, `text`),
but the server validates some actions against their own parameter names. Example seen
2026-11-20:

    get_map {"id": "market_prime"}
    -> Error: invalid_payload: Unknown parameter(s): id. Valid parameters: system_id.

So validation has two layers:
  1. the published schema (types, enums) for keys it knows, and
  2. this table of extra keys per (tool, action), filled in from real server replies.
The server remains the final authority: an `invalid_payload` reply means nothing happened.

Add entries ONLY after the server has confirmed them, and note the date.
"""
from __future__ import annotations

# (tool, action) -> {param_name: json_type}
EXTRA_PARAMS: dict[tuple[str, str], dict[str, str]] = {
    ('spacemolt', 'get_map'): {'system_id': 'string'},  # confirmed 2026-11-20
    ('spacemolt', 'get_guide'): {'guide': 'string'},    # confirmed 2026-11-20
    ('spacemolt', 'accept_mission'): {'template_id': 'string'},  # docs server contract 2026-11-20
    ('spacemolt', 'sell'): {'auto_list': 'boolean'},    # docs server contract 2026-11-20
}

# (tool, action) -> params the server rejects even though the shared schema lists them.
REJECTED_PARAMS: dict[tuple[str, str], set[str]] = {
    ('spacemolt', 'get_map'): {'id'},  # confirmed 2026-11-20
}


def extra_params(tool: str, action: str | None) -> dict[str, str]:
    return EXTRA_PARAMS.get((tool, action or ''), {})


def rejected_params(tool: str, action: str | None) -> set[str]:
    return REJECTED_PARAMS.get((tool, action or ''), set())
