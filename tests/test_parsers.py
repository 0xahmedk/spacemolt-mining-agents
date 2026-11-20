"""Offline tests for mas.parsers using real response text seen on 2026-11-14."""
from mas.mcp_session import ToolResult, extract
from mas.parsers import (parse_error, parse_mine, parse_mission_ids, parse_status, parse_table,
                         retry_after_seconds)

STATUS = """Prac-Ahmed1 [nebula] | 1,250cr | Haven
Ship: Prospect (prospect) | Hull: 95/95 | Shield: 51/50 (+1/tick) | Armor: 4 | Speed: 1
Fuel: 130/130 | Cargo: 0/110 | CPU: 4/13 | Power: 10/26
Docked at: grand_exchange_station
Security: Maximum Security (empire capital)
"""

SYSTEM = """System: Haven (haven) | Empire: nebula
POIs (7):
id\tname\ttype\tclass\tbase\tbase_type
haven_star\tHaven Star\tsun\tG5V\t\t
grand_exchange\tGrand Exchange\tstation\t\tGrand Exchange Station\tstation
commerce_fields\tCommerce Fields\tasteroid_belt\tmetallic\t\t

Connections (2):
system_id\tname\tdistance
market_prime\tMarket Prime\t407 GU
traders_rest\tTrader's Rest\t514 GU
"""

MISSIONS = """Missions at Grand Exchange Station (2):
--- Copper Requisition [copper_requisition] (mining, difficulty 1) ---
Copper ore is essential.
Rewards: 1,800cr, +15 mining XP
Objectives:
  - Mine 25 units of Copper Ore
--- Off the Books: Red Mist [smuggling_courier_x~abc123] (smuggling, difficulty 3) ---
Rewards: 300cr, +50 smuggling XP
Objectives:
  - Deliver 5 Red Mist to Frontier Station
"""


UNDOCKED_STATUS = """Prac-Ahmed1 [nebula] | 250cr | Haven
Ship: Prospect (prospect) | Hull: 95/95 | Shield: 50/50 (+1/tick) | Armor: 4 | Speed: 1
Fuel: 129/130 | Cargo: 4/110 | CPU: 4/13 | Power: 10/26
Security: Maximum Security (empire capital)
Connections: market_prime, traders_rest
Resources (5):
resource\trichness\tremaining\tsupports_power\tworkable
Iron Ore\t75\t0\t0\tyes
Copper Ore\t65\t0\t0\tyes
Trade Crystal\t20\t29\t1\tyes
Cargo (2 items):
item\tqty\tsize
Trade Crystal\t2\t1
Iron Ore\t2\t1
Active missions (1/5):
- First Cargo (mining)
"""

ACTIVE = """Active missions (1/5):
--- First Cargo [42d92dacb5f7c9d08ce8915aff151842] (mining, difficulty 1) ---
Objectives:
  - Mine 15 units of Copper Ore: 0/15
Rewards: 1,000cr, +20 mining XP
Expires in: 25900 ticks
"""


def run():
    u = parse_status(UNDOCKED_STATUS)
    assert not u['docked'] and u['docked_at'] is None and u['fuel'] == 129 and u['cargo_used'] == 4, u
    assert u['cargo'] == {'Trade Crystal': 2, 'Iron Ore': 2}, u['cargo']
    assert [r['remaining'] for r in u['poi_resources']] == [0, 0, 29], u['poi_resources']
    assert u['active_missions'] == 1 and u['max_missions'] == 5
    print('[PASS] parse_status (undocked, cargo, belt resources)')

    a = parse_mission_ids(ACTIVE)
    assert a[0]['id'] == '42d92dacb5f7c9d08ce8915aff151842' and a[0]['progress'] == [(0, 15)], a
    print('[PASS] active mission instance id + progress')

    assert parse_mine('Mined 1 Iron Ore.\nDeposit: 5 units (100% depleted)\nXP: mining +1') == \
        {'qty': 1, 'item': 'Iron Ore', 'deposit_left': 5}
    assert parse_mine('Mined 1 Iron Ore.\nDeposit: depleted (100% depleted)')['deposit_left'] == 0
    assert parse_mine('Error: deposit_too_sparse: ...') is None
    print('[PASS] parse_mine')

    s = parse_status(STATUS)
    assert s['username'] == 'Prac-Ahmed1' and s['empire'] == 'nebula', s
    assert s['credits'] == 1250 and s['system'] == 'Haven', s
    assert (s['fuel'], s['fuel_max'], s['cargo_used'], s['cargo_max']) == (130, 130, 0, 110), s
    assert s['docked'] and s['docked_at'] == 'grand_exchange_station' and s['ship_class'] == 'prospect'
    print('[PASS] parse_status')

    assert parse_error('Error: session_invalid: Your session has expired (sessions expire...)')[0] == 'session_invalid'
    assert parse_error('All good') is None
    assert retry_after_seconds('Error: rate_limited: slow down. retry_after: 7') == 7
    print('[PASS] parse_error / retry_after')

    pois = parse_table(SYSTEM, 'POIs (')
    assert [p['id'] for p in pois] == ['haven_star', 'grand_exchange', 'commerce_fields'], pois
    assert pois[2]['type'] == 'asteroid_belt'
    conns = parse_table(SYSTEM, 'Connections (')
    assert conns[0] == {'system_id': 'market_prime', 'name': 'Market Prime', 'distance': '407 GU'}, conns
    print('[PASS] parse_table')

    ms = parse_mission_ids(MISSIONS)
    assert [m['id'] for m in ms] == ['copper_requisition', 'smuggling_courier_x~abc123'], ms
    assert ms[0]['reward_credits'] == 1800 and ms[0]['objectives'] == ['Mine 25 units of Copper Ore'], ms[0]
    assert ms[1]['type'] == 'smuggling'
    print('[PASS] parse_mission_ids')

    r = ToolResult('spacemolt_auth', 'login', False, 'Logged in.\nSession ID: sess-abcdef12', None)
    assert extract(r, 'session_id') == 'sess-abcdef12'
    r = ToolResult('spacemolt_auth', 'register', False, 'Session ID: s-1234567\nPassword: Xy9-kLmn!', None)
    assert extract(r, 'password') == 'Xy9-kLmn!'
    print('[PASS] extract session_id / password from text')


if __name__ == '__main__':
    run()
