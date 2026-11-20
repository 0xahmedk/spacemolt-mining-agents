"""The task format exchanged over A2A between the coordinator and the workers.

A2A carries messages made of "parts". We send ONE text part whose body is a
JSON object (media type application/json), so every handoff is explicit,
validated and logged:

    coordinator -> worker   (A2A message)
    {
      "protocol": "spacemolt-mas/1",
      "task_id": "M-20261120-101500-ab12cd:mine:1",   # our id; deterministic -> safe to resend
      "mission_id": "M-20261120-101500-ab12cd",
      "skill": "mine",
      "pilot": "Prac-Ahmed1",
      "params": {"poi": "commerce_fields", "target_qty": 15, "target_item": "Copper Ore"},
      "constraints": {"max_cycles": 40, "max_spend": 0},
      "issued_by": "coordinator",
      "rationale": "copper deposit has 8 left; mission first_cargo pays 1,000 cr"
    }

    worker -> coordinator   (A2A artifact on the completed/failed task)
    {
      "protocol": "spacemolt-mas/1",
      "task_id": "...", "skill": "mine", "pilot": "...",
      "status": "completed" | "failed" | "needs_reconcile",
      "summary": "mined 6 units (Copper Ore x4, Iron Ore x2); stopped: belt_depleted",
      "data": {...skill-specific...},
      "evidence": {"before": {...status...}, "after": {...status...}, "actions": [idempotency keys]},
      "error": null | {"code": "...", "message": "..."}
    }
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL = 'spacemolt-mas/1'
MEDIA_TYPE = 'application/json'

# Skills each worker role offers (also published in its A2A Agent Card).
ROLE_SKILLS: dict[str, dict[str, str]] = {
    'resource': {
        'status':  'Observe a pilot: credits, fuel, cargo, location, POI resources.',
        'survey':  'Read the deposits at a POI (travels there first if asked).',
        'mine':    'Mine at a POI until a target quantity, a cycle cap, a full hold, or an empty belt.',
        'go_to':   'Fly to a POI in the current system (no-op if already there).',
        'return_to_station': 'Fly back to the station and dock.',
    },
    'trading': {
        'status':          'Observe a pilot: credits, fuel, cargo, location.',
        'market':          'Read the station order book (best bid/ask per item).',
        'sell':            'Instant-sell cargo into existing bids, respecting a minimum price.',
        'list_sell_order': 'Place a sell order on the exchange (1% fee).',
        'buy_order':       'Place a buy order within a spending cap.',
        'missions_board':  'Read the station mission board.',
        'active_missions': 'Read active missions with progress.',
        'accept_mission':  'Accept a mission by template id (refuses unsafe types).',
        'complete_mission': 'Complete an active mission and report the reward.',
        'refuel':          'Refuel at the station within a spending cap.',
    },
}


class ProtocolError(ValueError):
    """Malformed task request."""


@dataclass
class TaskRequest:
    task_id: str
    mission_id: str
    skill: str
    pilot: str
    params: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    issued_by: str = 'coordinator'
    rationale: str = ''
    protocol: str = PROTOCOL

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str, *, role: str | None = None) -> 'TaskRequest':
        try:
            raw = json.loads(text)
        except (TypeError, ValueError) as e:
            raise ProtocolError(f'task body is not JSON: {e}') from None
        if not isinstance(raw, dict):
            raise ProtocolError('task body must be a JSON object')
        if raw.get('protocol') != PROTOCOL:
            raise ProtocolError(f'unsupported protocol {raw.get("protocol")!r}; expected {PROTOCOL}')
        for key in ('task_id', 'mission_id', 'skill', 'pilot'):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ProtocolError(f'missing or empty field {key!r}')
        for key in ('params', 'constraints'):
            if not isinstance(raw.get(key, {}), dict):
                raise ProtocolError(f'{key!r} must be an object')
        if role and raw['skill'] not in ROLE_SKILLS[role]:
            raise ProtocolError(f'{role} worker has no skill {raw["skill"]!r}; offers {sorted(ROLE_SKILLS[role])}')
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class TaskResult:
    task_id: str
    skill: str
    pilot: str
    status: str                      # completed | failed | needs_reconcile
    summary: str = ''
    data: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    error: dict | None = None
    protocol: str = PROTOCOL

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)

    @classmethod
    def from_json(cls, text: str) -> 'TaskResult':
        raw = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    @property
    def ok(self) -> bool:
        return self.status == 'completed'


def error(code: str, message: str, **extra: Any) -> dict:
    return {'code': code, 'message': message, **extra}
