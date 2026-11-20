"""Trading/logistics agent skills: market reads, sales, orders, missions, refuelling.

Safety rules enforced here (not left to the LLM):
  * never accept smuggling / combat / courier-with-fixer-debt missions;
  * never sell below params.min_price; never spend above constraints.max_spend;
  * every money/goods action is idempotent per task (see SkillContext.act).
"""
from __future__ import annotations

import re

from mas.a2a_protocol import TaskRequest, TaskResult
from mas.parsers import item_id_from_name, parse_market, parse_mission_ids, parse_order_id
from mas.worker import SkillContext, SkillError

UNSAFE_MISSION_TYPES = {'smuggling', 'combat', 'bounty', 'raiding'}
UNSAFE_ID_HINTS = ('smuggling', 'black_market', 'off_the_books', 'hunt', 'bounty')


def _cargo_ids(st: dict) -> dict[str, int]:
    return {item_id_from_name(name): qty for name, qty in (st.get('cargo') or {}).items()}


async def _market(ctx: SkillContext, **filters) -> list[dict]:
    r = await ctx.gw.query('spacemolt_market', 'view_market', filters or None, task_id=ctx.task_id)
    rows = parse_market(r.text)
    ctx.store.observations.record(ctx.pilot, 'market', {'filters': filters, 'rows': rows},
                                  'spacemolt_market.view_market')
    return rows


def _max_spend(req: TaskRequest) -> int:
    v = req.constraints.get('max_spend')
    if v is None:
        raise SkillError('bad_params', 'constraints.max_spend is required for actions that spend credits')
    return int(v)


# ------------------------------------------------------------------ reads
async def status(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    st = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"{st['credits']} cr, fuel {st['fuel']}/{st['fuel_max']}, "
                              f"cargo {st['cargo_used']}/{st['cargo_max']}, docked={st['docked']}",
                      data={'status': st}, evidence=ctx.evidence(st, st))


async def market(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    filters = {k: req.params[k] for k in ('category', 'item_id') if req.params.get(k)}
    rows = await _market(ctx, **filters)
    with_bids = [r for r in rows if r['best_buy']]
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f'{len(rows)} items, {len(with_bids)} with bids',
                      data={'rows': rows}, evidence=ctx.evidence(None, ctx.last_status))


async def missions_board(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    r = await ctx.gw.query('spacemolt', 'get_missions', task_id=ctx.task_id)
    board = parse_mission_ids(r.text)
    for m in board:
        m['safe'] = _is_safe(m)
    ctx.store.observations.record(ctx.pilot, 'missions_board', {'missions': board}, 'spacemolt.get_missions')
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f'{len(board)} missions, {sum(m["safe"] for m in board)} allowed by safety rules',
                      data={'missions': board}, evidence=ctx.evidence(None, ctx.last_status))


async def _active(ctx: SkillContext) -> list[dict]:
    r = await ctx.gw.query('spacemolt', 'get_active_missions', task_id=ctx.task_id)
    active = parse_mission_ids(r.text)
    ctx.store.observations.record(ctx.pilot, 'active_missions', {'missions': active},
                                  'spacemolt.get_active_missions')
    return active


async def active_missions(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    active = await _active(ctx)
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary='; '.join(f"{m['title']} {m['progress']}" for m in active) or 'no active missions',
                      data={'missions': active}, evidence=ctx.evidence(None, ctx.last_status))


def _is_safe(m: dict) -> bool:
    return m['type'] not in UNSAFE_MISSION_TYPES and not any(h in m['id'] for h in UNSAFE_ID_HINTS)


# ------------------------------------------------------------------ missions
async def accept_mission(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    template = req.params.get('template_id')
    if not template:
        raise SkillError('bad_params', 'accept_mission needs params.template_id')
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    before = await ctx.status()
    board = parse_mission_ids((await ctx.gw.query('spacemolt', 'get_missions', task_id=ctx.task_id)).text)
    offer = next((m for m in board if m['id'] == template), None)
    active = await _active(ctx)
    if offer is None:
        already = [m for m in active if template.replace('_', ' ') in m['title'].lower()]
        if already:
            return _accepted(req, already[0], before, before, ctx, note='already active')
        raise SkillError('mission_not_offered', f'{template} is not on the board', board=[m['id'] for m in board])
    if not _is_safe(offer):
        raise SkillError('unsafe_mission', f"refusing {offer['type']} mission {template}")
    existing = next((m for m in active if m['title'] == offer['title']), None)
    if existing:
        return _accepted(req, existing, before, before, ctx, note='already active')
    if len(active) >= 5:
        raise SkillError('mission_slots_full', 'already 5 active missions')

    count_before = len(active)
    await ctx.act(f'accept:{template}', 'spacemolt', 'accept_mission', {'id': template},
                  verify=lambda b, a: (a.get('active_missions') or 0) > (b.get('active_missions') or 0))
    active = await _active(ctx)
    mine = next((m for m in active if m['title'] == offer['title']), None)
    if mine is None:
        raise SkillError('accept_unconfirmed', f'accepted {template} but it is not in active missions '
                                               f'({count_before} -> {len(active)})')
    after = await ctx.status()
    return _accepted(req, mine, before, after, ctx, reward=offer['reward_credits'])


def _accepted(req, mission, before, after, ctx, note='', reward=None) -> TaskResult:
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"accepted {mission['title']} ({mission['id']}) {note}".strip(),
                      data={'instance_id': mission['id'], 'title': mission['title'],
                            'progress': mission.get('progress'), 'reward_credits': reward, 'note': note},
                      evidence=ctx.evidence(before, after))


async def complete_mission(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """params: instance_id (preferred) or title."""
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    active = await _active(ctx)
    mid, title = req.params.get('instance_id'), req.params.get('title')
    mission = next((m for m in active if m['id'] == mid or (title and m['title'] == title)), None)
    rec = ctx.store.actions.get(f"{ctx.task_id}:complete:{mid or title}")
    if mission is None and not (rec and rec.status in ('confirmed', 'unknown', 'pending')):
        raise SkillError('mission_not_active', f'{mid or title} is not an active mission')
    if mission and mission['progress'] and any(d < t for d, t in mission['progress']):
        raise SkillError('objectives_incomplete', f"{mission['title']} progress {mission['progress']}",
                         progress=mission['progress'])
    before = await ctx.status()
    r = await ctx.act(f"complete:{mid or title}", 'spacemolt', 'complete_mission', {'id': mission['id'] if mission else mid},
                      verify=lambda b, a: (a['credits'] or 0) > (b['credits'] or 0))
    after = await ctx.status()
    cp = ctx.store.observations.latest(ctx.pilot, f"checkpoint:{ctx.task_id}:complete:{mid or title}")
    gained = (after['credits'] or 0) - ((cp['data']['credits'] if cp else before['credits']) or 0)
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"completed {mission['title'] if mission else mid}: +{gained} cr",
                      data={'instance_id': mid, 'credits_gained': gained, 'server_reply': r.text[:500]},
                      evidence=ctx.evidence(before, after))


# ------------------------------------------------------------------ selling and buying
async def sell(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """Instant sell into existing bids. params: item_id, quantity (int or 'all'), min_price."""
    item = req.params.get('item_id')
    min_price = int(req.params.get('min_price', 1))
    if not item:
        raise SkillError('bad_params', 'sell needs params.item_id')
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    before = await ctx.status()
    held = _cargo_ids(before).get(item, 0)
    key = f'sell:{item}'
    already = ctx.store.actions.get(f'{ctx.task_id}:{key}')
    if held <= 0 and not already:
        raise SkillError('nothing_to_sell', f'no {item} in cargo')
    qty = held if req.params.get('quantity', 'all') == 'all' else min(int(req.params['quantity']), held)
    if not already:
        row = next((r for r in await _market(ctx, item_id=item) if r['item_id'] == item), None) \
            or next((r for r in await _market(ctx) if r['item_id'] == item), None)
        bid = row['best_buy'] if row else None
        if not bid or bid < min_price:
            raise SkillError('no_acceptable_bid', f'best bid for {item} is {bid} cr, minimum is {min_price} cr',
                             best_bid=bid)
    r = await ctx.act(key, 'spacemolt', 'sell', {'id': item, 'quantity': qty},
                      verify=lambda b, a: _cargo_ids(a).get(item, 0) < _cargo_ids(b).get(item, 0))
    after = await ctx.status()
    sold = held - _cargo_ids(after).get(item, 0) if not already else qty
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f'sold {sold} {item}; credits {before["credits"]} -> {after["credits"]}',
                      data={'item_id': item, 'sold': sold, 'credits_gained': (after['credits'] or 0) - (before['credits'] or 0),
                            'server_reply': r.text[:500]},
                      evidence=ctx.evidence(before, after))


async def list_sell_order(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """params: item_id, quantity, price_each (>= min_price)."""
    item, qty, price = req.params.get('item_id'), int(req.params.get('quantity', 0)), int(req.params.get('price_each', 0))
    if not item or qty < 1 or price < max(1, int(req.params.get('min_price', 1))):
        raise SkillError('bad_params', 'list_sell_order needs item_id, quantity>=1, price_each>=min_price')
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    before = await ctx.status()
    if _cargo_ids(before).get(item, 0) < qty and not ctx.store.actions.get(f'{ctx.task_id}:sell_order:{item}'):
        raise SkillError('nothing_to_sell', f'need {qty} {item}, have {_cargo_ids(before).get(item, 0)}')
    r = await ctx.act(f'sell_order:{item}', 'spacemolt_market', 'create_sell_order',
                      {'item_id': item, 'quantity': qty, 'price_each': price},
                      verify=lambda b, a: _cargo_ids(a).get(item, 0) < _cargo_ids(b).get(item, 0))
    after = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f'listed {qty} {item} at {price} cr: {r.text[:120]}',
                      data={'order_id': parse_order_id(r.text), 'item_id': item, 'quantity': qty, 'price_each': price},
                      evidence=ctx.evidence(before, after))


async def buy_order(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """params: item_id, quantity, price_each. constraints: max_spend (required)."""
    item, qty, price = req.params.get('item_id'), int(req.params.get('quantity', 0)), int(req.params.get('price_each', 0))
    cap = _max_spend(req)
    if not item or qty < 1 or price < 1:
        raise SkillError('bad_params', 'buy_order needs item_id, quantity>=1, price_each>=1')
    cost = qty * price
    if cost > cap:
        raise SkillError('over_budget', f'{qty} x {price} = {cost} cr exceeds max_spend {cap}')
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    before = await ctx.status()
    if (before['credits'] or 0) < cost + 5 and not ctx.store.actions.get(f'{ctx.task_id}:buy_order:{item}'):
        raise SkillError('insufficient_credits', f'need ~{cost} cr, have {before["credits"]}')
    r = await ctx.act(f'buy_order:{item}', 'spacemolt_market', 'create_buy_order',
                      {'item_id': item, 'quantity': qty, 'price_each': price},
                      verify=lambda b, a: (a['credits'] or 0) < (b['credits'] or 0))
    after = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f'buy order {qty} {item} at {price} cr: {r.text[:120]}',
                      data={'order_id': parse_order_id(r.text), 'item_id': item, 'quantity': qty,
                            'price_each': price, 'credits_spent': (before['credits'] or 0) - (after['credits'] or 0)},
                      evidence=ctx.evidence(before, after))


async def refuel(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """Refuel only if fuel is below params.min_fuel (default 60%) and the estimated cost fits max_spend."""
    cap = _max_spend(req)
    await ctx.ensure_docked_at(req.params.get('station_poi', 'grand_exchange'))
    before = await ctx.status()
    threshold = int(req.params.get('min_fuel', int(0.6 * (before['fuel_max'] or 100))))
    if (before['fuel'] or 0) >= threshold:
        return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                          summary=f"fuel {before['fuel']} >= {threshold}: no refuel needed",
                          data={'refuelled': False}, evidence=ctx.evidence(before, before))
    poi_text = (await ctx.gw.query('spacemolt', 'get_poi', task_id=ctx.task_id)).text
    m = re.search(r'Fuel: (\d+) cr/unit', poi_text)
    price = int(m.group(1)) if m else 20
    estimate = ((before['fuel_max'] or 0) - (before['fuel'] or 0)) * price
    if estimate > cap:
        raise SkillError('over_budget', f'refuel ~{estimate} cr exceeds max_spend {cap}')
    await ctx.act('refuel', 'spacemolt', 'refuel', {},
                  verify=lambda b, a: (a['fuel'] or 0) > (b['fuel'] or 0))
    after = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"fuel {before['fuel']} -> {after['fuel']} for {(before['credits'] or 0) - (after['credits'] or 0)} cr",
                      data={'refuelled': True, 'price_per_unit': price}, evidence=ctx.evidence(before, after))


SKILLS = {'status': status, 'market': market, 'sell': sell, 'list_sell_order': list_sell_order,
          'buy_order': buy_order, 'missions_board': missions_board, 'active_missions': active_missions,
          'accept_mission': accept_mission, 'complete_mission': complete_mission, 'refuel': refuel}
