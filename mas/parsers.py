"""Parse SpaceMolt's human-readable text responses into small dicts.

The server answers in text (e.g. "Prac-Ahmed1 [nebula] | 250cr | Haven"), not JSON,
so agents need tolerant parsers. Every parser returns None for fields it cannot
find instead of guessing. Formats are based on real responses seen 2026-11-14;
extend them as new formats are observed (keep tests in tests/test_parsers.py).
"""
from __future__ import annotations

import re

_ERROR = re.compile(r'^\s*Error:\s*([A-Za-z0-9_]+)\s*:\s*(.*)', re.S)
_RETRY_AFTER = re.compile(r'retry_after\D{0,5}(\d+)', re.I)


def parse_error(text: str) -> tuple[str, str] | None:
    """'Error: session_invalid: Your session has expired...' -> ('session_invalid', 'Your session...')."""
    m = _ERROR.match(text or '')
    return (m.group(1).lower(), m.group(2).strip()) if m else None


def retry_after_seconds(text: str) -> int | None:
    m = _RETRY_AFTER.search(text or '')
    return int(m.group(1)) if m else None


def _int(s: str | None) -> int | None:
    return int(s.replace(',', '')) if s else None


def parse_status(text: str) -> dict:
    """Parse `spacemolt get_status` text.

    Example header lines:
      Prac-Ahmed1 [nebula] | 250cr | Haven
      Ship: Prospect (prospect) | Hull: 95/95 | Shield: 51/50 (+1/tick) | Armor: 4 | Speed: 1
      Fuel: 130/130 | Cargo: 0/110 | CPU: 4/13 | Power: 10/26
      Docked at: grand_exchange_station
    """
    out: dict = {'username': None, 'empire': None, 'credits': None, 'system': None,
                 'ship_class': None, 'hull': None, 'hull_max': None, 'fuel': None, 'fuel_max': None,
                 'cargo_used': None, 'cargo_max': None, 'docked_at': None, 'poi': None}
    m = re.search(r'^(?P<user>.+?) \[(?P<emp>[a-z_]+)\] \| (?P<cr>[\d,]+)cr \| (?P<sys>.+)$', text, re.M)
    if m:
        out.update(username=m['user'].strip(), empire=m['emp'], credits=_int(m['cr']), system=m['sys'].strip())
    if m := re.search(r'Ship: .*?\(([a-z0-9_]+)\)', text):
        out['ship_class'] = m.group(1)
    if m := re.search(r'Hull: (\d+)/(\d+)', text):
        out['hull'], out['hull_max'] = int(m.group(1)), int(m.group(2))
    if m := re.search(r'Fuel: (\d+)/(\d+)', text):
        out['fuel'], out['fuel_max'] = int(m.group(1)), int(m.group(2))
    if m := re.search(r'Cargo: (\d+)/(\d+)', text):
        out['cargo_used'], out['cargo_max'] = int(m.group(1)), int(m.group(2))
    if m := re.search(r'^Docked at: (\S+)', text, re.M):
        out['docked_at'] = m.group(1)
    # Undocked (seen 2026-11-20): no "Docked at" line and no POI id in get_status;
    # use get_location / get_poi for the POI. A "Resources (N):" table shows the current POI's deposits.
    out['docked'] = out['docked_at'] is not None
    out['cargo'] = {r['item']: int(r['qty']) for r in parse_table(text, 'Cargo (') if r.get('qty', '').isdigit()}
    out['poi_resources'] = parse_resources(text)
    if m := re.search(r'^Active missions \((\d+)/(\d+)\)', text, re.M):
        out['active_missions'], out['max_missions'] = int(m.group(1)), int(m.group(2))
    return out


def parse_resources(text: str) -> list[dict]:
    """'Resources (N):' table from get_poi / get_status at a belt.

    resource  richness  remaining  supports_power  workable
    Iron Ore  75        8          1               yes
    """
    rows = []
    for r in parse_table(text, 'Resources ('):
        try:
            rows.append({'resource': r['resource'], 'richness': int(r['richness']),
                         'remaining': int(r['remaining']), 'supports_power': int(r['supports_power']),
                         'workable': r.get('workable', '').strip() == 'yes'})
        except (KeyError, ValueError):
            continue
    return rows


def parse_mine(text: str) -> dict | None:
    """'Mined 1 Iron Ore.\\nDeposit: 5 units (100% depleted)' -> {'qty': 1, 'item': 'Iron Ore', ...}."""
    m = re.search(r'Mined (\d+) (.+?)\.', text or '')
    if not m:
        return None
    dep = re.search(r'Deposit: (?:(\d+) units|depleted)', text)
    return {'qty': int(m.group(1)), 'item': m.group(2),
            'deposit_left': (int(dep.group(1)) if dep and dep.group(1) else 0) if dep else None}


def parse_table(text: str, header_startswith: str) -> list[dict]:
    """Parse a tab-separated table that follows a header line starting with `header_startswith`.

    Used for e.g. get_system 'POIs (7):' / 'Connections (2):' and catalog listings.
    """
    lines = (text or '').splitlines()
    rows: list[dict] = []
    for i, line in enumerate(lines):
        if line.startswith(header_startswith) and i + 1 < len(lines):
            cols = lines[i + 1].split('\t')
            for row in lines[i + 2:]:
                if not row.strip() or '\t' not in row:
                    break
                vals = row.split('\t')
                rows.append(dict(zip(cols, vals + [''] * (len(cols) - len(vals)))))
            break
    return rows


def parse_mission_ids(text: str) -> list[dict]:
    """Extract '--- Title [mission_id] (type, difficulty N) ---' blocks.

    Works for get_missions (id = template id, e.g. 'first_cargo') and get_active_missions
    (id = instance id, e.g. '42d92dac...'). Active objectives carry progress
    ('Mine 15 units of Copper Ore: 0/15') -> 'progress': [(0, 15)].
    """
    pat = re.compile(r'^--- (?P<title>.+?) \[(?P<id>[^\]]+)\] \((?P<type>[a-z_]+), difficulty (?P<d>\d+)\) ---$', re.M)
    missions = []
    for m in pat.finditer(text or ''):
        nxt = text.find('\n--- ', m.end())
        block = text[m.end(): nxt if nxt != -1 else len(text)]
        reward = re.search(r'Rewards: ([\d,]+)cr', block)
        objectives = [o.strip()[2:] for o in block.splitlines() if o.strip().startswith('- ')]
        progress = [(int(p.group(1)), int(p.group(2)))
                    for o in objectives if (p := re.search(r': (\d+)/(\d+)$', o))]
        missions.append({'id': m['id'], 'title': m['title'], 'type': m['type'], 'difficulty': int(m['d']),
                         'reward_credits': _int(reward.group(1)) if reward else 0,
                         'objectives': objectives, 'progress': progress})
    return missions
