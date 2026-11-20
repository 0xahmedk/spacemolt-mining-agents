"""Resource-acquisition agent skills: observe, travel, mine, return to station.

Each skill takes (SkillContext, TaskRequest) and returns a TaskResult with game evidence.
"""
from __future__ import annotations

from collections import Counter

from mas.a2a_protocol import TaskRequest, TaskResult
from mas.mcp_gateway import GameError
from mas.parsers import parse_mine
from mas.worker import STATION_POI, SkillContext, SkillError

DEFAULT_BELT = 'commerce_fields'
POI_REFRESH_EVERY = 5      # re-read the deposit table every N mining cycles


async def status(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    st = await ctx.status()
    p = await ctx.poi()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"{st['credits']} cr, fuel {st['fuel']}/{st['fuel_max']}, cargo "
                              f"{st['cargo_used']}/{st['cargo_max']}, at {p['id']}",
                      data={'status': st, 'poi': p}, evidence=ctx.evidence(st, st))


async def survey(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    if req.params.get('poi'):
        await ctx.ensure_at(req.params['poi'])
    p = await ctx.poi()
    workable = [r for r in p['resources'] if r['workable'] and r['remaining'] > 0]
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed',
                      summary=f"{p['id']}: " + (', '.join(f"{r['resource']} {r['remaining']}" for r in workable)
                                                or 'no workable deposits'),
                      data={'poi': p, 'workable': workable}, evidence=ctx.evidence(None, ctx.last_status))


async def go_to(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    target = req.params.get('poi')
    if not target:
        raise SkillError('bad_params', 'go_to needs params.poi')
    before = await ctx.status()
    await ctx.ensure_at(target)
    after = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed', summary=f'at {target}',
                      data={'poi': target}, evidence=ctx.evidence(before, after))


async def return_to_station(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    station = req.params.get('station_poi', STATION_POI)
    before = await ctx.status()
    await ctx.ensure_docked_at(station)
    after = await ctx.status()
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed', summary=f'docked at {after["docked_at"]}',
                      data={'docked_at': after['docked_at']}, evidence=ctx.evidence(before, after))


async def mine(ctx: SkillContext, req: TaskRequest) -> TaskResult:
    """Mine until one stop condition holds.

    params:      poi (default commerce_fields), target_item ('Copper Ore', optional), target_qty (int, optional)
    constraints: max_cycles (default 30), min_free_cargo (default 1)
    Stop reasons: target_reached | max_cycles | cargo_full | belt_depleted | game_error:<code>
    A stop is not a failure: the result reports what happened and the coordinator re-plans.
    """
    poi_id = req.params.get('poi', DEFAULT_BELT)
    target_item = req.params.get('target_item')
    target_qty = int(req.params.get('target_qty') or 0)
    max_cycles = int(req.constraints.get('max_cycles', 30))
    min_free = int(req.constraints.get('min_free_cargo', 1))
    if max_cycles < 1 or max_cycles > 200:
        raise SkillError('bad_params', 'max_cycles must be 1..200')

    before = await ctx.status()
    await ctx.ensure_at(poi_id)
    deposits = (await ctx.poi())['resources']
    mined: Counter = Counter()
    stop = 'max_cycles'

    def counted() -> int:
        return mined[target_item] if target_item else sum(mined.values())

    for i in range(max_cycles):
        if target_qty and counted() >= target_qty:
            stop = 'target_reached'
            break
        if i % POI_REFRESH_EVERY == 0 and i:
            deposits = (await ctx.poi())['resources']
        if deposits and all(d['remaining'] <= 0 for d in deposits):
            stop = 'belt_depleted'
            break
        st = ctx.last_status or await ctx.status()
        if st['cargo_max'] is not None and st['cargo_max'] - (st['cargo_used'] or 0) < min_free:
            stop = 'cargo_full'
            break
        try:
            r = await ctx.act(f'mine:{i}', 'spacemolt', 'mine',
                              verify=lambda b, a: (a['cargo_used'] or 0) > (b['cargo_used'] or 0))
        except GameError as e:
            stop = f'game_error:{e.code}'
            break
        m = parse_mine(r.text)
        if m:
            mined[m['item']] += m['qty']
        if i % 3 == 0:
            await ctx.progress(f'cycle {i + 1}/{max_cycles}: mined {dict(mined)}')

    after = await ctx.status()
    total = sum(mined.values())
    summary = (f"mined {total} unit(s) " + (f"({', '.join(f'{k} x{v}' for k, v in mined.items())}) " if mined else '')
               + f'at {poi_id}; stopped: {stop}')
    return TaskResult(req.task_id, req.skill, req.pilot, 'completed', summary=summary,
                      data={'poi': poi_id, 'mined': dict(mined), 'total': total, 'target_item': target_item,
                            'target_qty': target_qty, 'target_count': counted(), 'stop_reason': stop,
                            'deposits_last_seen': deposits},
                      evidence=ctx.evidence(before, after))


SKILLS = {'status': status, 'survey': survey, 'go_to': go_to, 'return_to_station': return_to_station, 'mine': mine}
