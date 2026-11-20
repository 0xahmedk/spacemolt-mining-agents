"""A small fake SpaceMolt world for offline tests of the workers.

Replies imitate the real server's TEXT formats observed on 2026-11-20 (see docs/game_notes.md),
so the same parsers are exercised. One pilot ('Pilot-X'), home system Haven, one station
(grand_exchange) and one belt (commerce_fields).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from tests.fake_mcp import _result

NAMES = {'iron_ore': 'Iron Ore', 'copper_ore': 'Copper Ore', 'silicon_ore': 'Silicon Ore',
         'trade_crystal': 'Trade Crystal'}

BOARD = [
    {'id': 'first_cargo', 'title': 'First Cargo', 'type': 'mining', 'reward': 1000,
     'item': 'Copper Ore', 'qty': 15},
    {'id': 'market_participation_selling', 'title': 'Market Participation: Selling', 'type': 'trading',
     'reward': 1000, 'item': None, 'qty': 10},
    {'id': 'smuggling_courier_x~abc', 'title': 'Off the Books: Red Mist', 'type': 'smuggling',
     'reward': 300, 'item': None, 'qty': 5},
]


def err(code: str, msg: str):
    return _result(f'Error: {code}: {msg}', True)


@dataclass
class FakeWorld:
    credits: int = 250
    fuel: int = 130
    poi: str = 'grand_exchange'
    docked: bool = True
    cargo: dict = field(default_factory=dict)                 # item_id -> qty
    deposits: dict = field(default_factory=lambda: {'Copper Ore': 8, 'Iron Ore': 3, 'Silicon Ore': 2})
    bids: dict = field(default_factory=lambda: {'silicon_ore': 10})   # item_id -> best bid
    active: dict = field(default_factory=dict)                # instance id -> mission dict
    calls: list = field(default_factory=list)
    valid_session: str | None = None
    session_counter: int = 0
    timeout_next_mutation: bool = False
    timeout_action: str | None = None
    connections: int = 0

    # ------------------------------------------------------------- helpers
    def _cargo_used(self):
        return sum(self.cargo.values())

    def _status_text(self):
        lines = [f'Pilot-X [nebula] | {self.credits}cr | Haven',
                 'Ship: Prospect (prospect) | Hull: 95/95 | Shield: 50/50 (+1/tick) | Armor: 4 | Speed: 1',
                 f'Fuel: {self.fuel}/130 | Cargo: {self._cargo_used()}/110 | CPU: 4/13 | Power: 10/26']
        if self.docked:
            lines.append('Docked at: grand_exchange_station')
        if self.cargo:
            lines += [f'Cargo ({len(self.cargo)} items):', 'item\tqty\tsize']
            lines += [f'{NAMES[i]}\t{q}\t1' for i, q in self.cargo.items() if q]
        if self.active:
            lines += [f'Active missions ({len(self.active)}/5):'] + [f"- {m['title']} ({m['type']})"
                                                                    for m in self.active.values()]
        return '\n'.join(lines) + '\n'

    def _poi_text(self):
        if self.poi == 'grand_exchange':
            return ('POI: Grand Exchange (grand_exchange) | Type: station\nThe largest market.\n'
                    'Station: Grand Exchange Station (grand_exchange_station)\n'
                    'Services: market, missions, refuel\nFuel: 16 cr/unit (11 fuel + 5 empire tax)\n')
        rows = '\n'.join(f'{name}\t60\t{left}\t1\tyes' for name, left in self.deposits.items())
        return ('POI: Commerce Fields (commerce_fields) | Type: asteroid_belt (metallic)\nRock.\n'
                f'Resources ({len(self.deposits)}):\nresource\trichness\tremaining\tsupports_power\tworkable\n'
                f'{rows}\n')

    # ------------------------------------------------------------- dispatcher
    def handle(self, tool: str, args: dict):
        self.calls.append((tool, dict(args)))
        action = args.get('action')
        if tool == 'spacemolt_auth' and action == 'login':
            self.session_counter += 1
            self.valid_session = f'sess-{self.session_counter:06d}'
            return _result(f'Welcome back! Session ID: {self.valid_session}')
        if args.get('session_id') != self.valid_session:
            return err('session_invalid', 'Your session has expired.')
        fn = getattr(self, f'_{tool}__{action}', None)
        if fn is None:
            return err('unknown_action', f'{tool}.{action}')
        return fn(args)

    # ------------------------------------------------------------- spacemolt
    def _spacemolt__get_status(self, a):
        return _result(self._status_text())

    def _spacemolt__get_poi(self, a):
        return _result(self._poi_text())

    def _spacemolt__undock(self, a):
        if not self.docked:
            return err('not_docked', 'You are not docked')
        self.docked = False
        return _result('Undocked from station.')

    def _spacemolt__dock(self, a):
        if self.poi != 'grand_exchange':
            return err('no_base', 'No station at this location')
        self.docked = True
        return _result('Docked at Grand Exchange Station.')

    def _spacemolt__travel(self, a):
        if self.docked:
            return err('docked', 'You must undock first')
        if a.get('id') not in ('grand_exchange', 'commerce_fields'):
            return err('invalid_poi', 'Unknown destination')
        self.poi, self.fuel = a['id'], self.fuel - 1
        return _result(f"Arrived at {a['id']}.")

    def _spacemolt__mine(self, a):
        if self.docked or self.poi != 'commerce_fields':
            return err('no_resources', 'Nothing to mine here')
        if self._cargo_used() >= 110:
            return err('cargo_full', 'Cargo hold is full')
        name = max(self.deposits, key=lambda k: self.deposits[k])
        if self.deposits[name] <= 0:
            return err('depleted', 'Every deposit here is depleted')
        self.deposits[name] -= 1
        item = next(i for i, n in NAMES.items() if n == name)
        self.cargo[item] = self.cargo.get(item, 0) + 1
        for m in self.active.values():
            if m['item'] == name:
                m['done'] = min(m['qty'], m['done'] + 1)
        return _result(f'Mined 1 {name}.\nDeposit: {self.deposits[name]} units (10% depleted)\nXP: mining +1')

    def _spacemolt__sell(self, a):
        item, qty = a.get('id'), a.get('quantity', 0)
        if not self.docked:
            return err('not_docked', 'Must be docked')
        if self.cargo.get(item, 0) < qty:
            return err('insufficient_cargo', 'Not enough items')
        bid = self.bids.get(item)
        if not bid:
            return err('no_buyers', 'No buy orders for this item')
        self.cargo[item] -= qty
        self.credits += qty * bid
        return _result(f'Sold {qty}x {NAMES[item]} for {qty * bid}cr.')

    def _spacemolt__get_missions(self, a):
        if not self.docked:
            return err('not_docked', 'Must be docked')
        blocks = []
        for m in BOARD:
            obj = f"Mine {m['qty']} units of {m['item']}" if m['item'] else f"Do {m['qty']} things"
            blocks.append(f"--- {m['title']} [{m['id']}] ({m['type']}, difficulty 1) ---\nText.\n"
                          f"Rewards: {m['reward']:,}cr, +15 mining XP\nObjectives:\n  - {obj}")
        return _result(f'Missions at Grand Exchange Station ({len(BOARD)}):\n' + '\n'.join(blocks))

    def _spacemolt__accept_mission(self, a):
        m = next((x for x in BOARD if x['id'] == a.get('id')), None)
        if m is None:
            return err('mission_not_available', 'No such mission')
        iid = uuid.uuid4().hex
        self.active[iid] = {**m, 'done': 0}
        return _result(f"Welcome aboard. Template: {m['id']}. Expires: 2026-11-23T06:15:58Z.")

    def _spacemolt__get_active_missions(self, a):
        blocks = []
        for iid, m in self.active.items():
            obj = f"Mine {m['qty']} units of {m['item']}" if m['item'] else f"Do {m['qty']} things"
            blocks.append(f"--- {m['title']} [{iid}] ({m['type']}, difficulty 1) ---\nObjectives:\n"
                          f"  - {obj}: {m['done']}/{m['qty']}\nRewards: {m['reward']:,}cr\nExpires in: 100 ticks")
        return _result(f'Active missions ({len(self.active)}/5):\n' + '\n'.join(blocks))

    def _spacemolt__complete_mission(self, a):
        m = self.active.get(a.get('id'))
        if m is None:
            return err('mission_not_found', 'No such active mission')
        if m['done'] < m['qty']:
            return err('objectives_incomplete', 'Objectives not met')
        del self.active[a['id']]
        self.credits += m['reward']
        return _result(f"Mission complete! Rewards: {m['reward']}cr")

    def _spacemolt__refuel(self, a):
        if not self.docked:
            return err('not_docked', 'Must be docked')
        need = 130 - self.fuel
        self.credits -= need * 16
        self.fuel = 130
        return _result(f'Refuelled {need} units for {need * 16}cr.')

    # ------------------------------------------------------------- market
    def _spacemolt_market__view_market(self, a):
        rows = []
        for item, name in NAMES.items():
            bid = self.bids.get(item)
            rows.append(f"ore\t{item}\t{name}\t5cr\t{f'{bid}cr' if bid else ''}\t\t100\t{9000 if bid else 0}")
        return _result(f'Market summary at Grand Exchange Station ({len(rows)} items):\n'
                       'category\titem_id\titem_name\tbest_sell\tbest_buy\tspread\tsell_qty\tbuy_qty\n'
                       + '\n'.join(rows) + '\nCategories: ore\n')

    def _spacemolt_market__create_sell_order(self, a):
        item, qty = a.get('item_id'), a.get('quantity', 0)
        if self.cargo.get(item, 0) < qty:
            return err('insufficient_cargo', 'Not enough items')
        self.cargo[item] -= qty
        self.credits -= 1
        return _result(f"Sell order: {qty} {NAMES[item]} ({item}) at {a.get('price_each')}cr each (fee: 1cr). "
                       f'Order ID: {uuid.uuid4().hex}.')

    def _spacemolt_market__create_buy_order(self, a):
        cost = a.get('quantity', 0) * a.get('price_each', 0)
        if cost > self.credits:
            return err('insufficient_credits', 'Not enough credits')
        self.credits -= cost
        return _result(f"Buy order: {a.get('quantity')} {a.get('item_id')} at {a.get('price_each')}cr each. "
                       f'Order ID: {uuid.uuid4().hex}.')
