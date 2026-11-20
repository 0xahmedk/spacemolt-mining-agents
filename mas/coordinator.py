"""Coordinator / planner agent (its own process). It never touches the game directly.

    python -m mas.coordinator --config config/mission.json

Loop per pilot (both pilots run concurrently):

  1. OBSERVE   Use fresh observations from the shared store; if too old, delegate a read task
               (status / active_missions / missions_board / market) to a worker over A2A.
  2. OPTIONS   Build a menu of SAFE, VALIDATED next actions from that state (deterministic):
               complete a finished mission, mine for a mission, accept a feasible mission,
               place the buy/sell order a market mission needs, sell into a bid, wait, ...
               Spending caps, unsafe mission types and repeated failures are filtered out here.
  3. DECIDE    Forced rules first (claim finished missions, refuel when low). Otherwise, if
               several options remain, the LLM picks one and explains why (mas/llm.py). If the
               state has not changed since the last LLM plan, that plan is reused (saves budget).
               No LLM / invalid answer -> highest-scoring option (deterministic fallback).
  4. DELEGATE  Record a mission (objective, decided_by, rationale) and a task with a
               deterministic id, send it to the resource or trading worker over A2A.
  5. VERIFY    Check the worker's evidence (credits/cargo before vs after, order ids, ...) and
               close the mission as done/failed. Failures are remembered and avoided.

Restart safety: on start, unfinished tasks of open missions are resent with the SAME task id;
workers replay confirmed steps from the action ledger instead of repeating them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mas.a2a_client import WorkerClient, WorkerUnavailable
from mas.a2a_protocol import TaskRequest, TaskResult
from mas.llm import LLM
from mas.parsers import item_id_from_name
from mas.store import IllegalTransition, Store
from scripts.evidence import record

DEFAULT_CONFIG: dict = {
    'pilots': ['Prac-Ahmed1'],
    'workers': {'resource': 'http://127.0.0.1:9101', 'trading': 'http://127.0.0.1:9102'},
    'station_poi': 'grand_exchange',
    'belt_poi': 'commerce_fields',
    'targets_per_pilot': {'credits_earned': 1000, 'ore_mined': 15, 'sales': 1},
    'limits': {
        'max_spend_total_per_pilot': 700,   # combined target is <= 1,500 spent
        'max_spend_per_task': 120,
        'max_cycles_per_mine_task': 20,
        'min_fuel': 40,
        'max_active_missions': 2,
        'min_sell_price': 1,
    },
    'freshness_seconds': {'status': 90, 'active_missions': 300, 'missions_board': 1800, 'market': 600},
    'wait_seconds_when_belt_empty': 300,
    'idle_seconds': 30,
    'llm': {'enabled': True, 'max_calls_per_run': 60},
}

OBJ_MINE = re.compile(r'^Mine (\d+) units? of (.+?)(?:: \d+/\d+)?$')
OBJ_SELL = re.compile(r'^Sell (\d+) units? of any item', re.I)
OBJ_BUY = re.compile(r'^Buy (\d+) units? of any item', re.I)

SYSTEM_PROMPT = (
    'You are the planning coordinator of an autonomous SpaceMolt mining/trading team. '
    'Each turn you choose exactly ONE next action for one pilot from the provided options; '
    'options are already validated and safe. Goal: reach the pilot targets (credits earned, ore mined, '
    'at least one exchange sale) while spending few credits and travelling little. Prefer finishing missions '
    'already accepted; prefer mining missions whose ore is actually left at the belt (belt.remaining); market '
    'participation missions pay 1000 cr for a small cost; avoid options that recently failed. '
    'Answer ONLY with JSON: {"choice": "<option id>", "rationale": "<max 30 words, cite the numbers>"}')


@dataclass
class Option:
    id: str
    role: str
    skill: str
    params: dict
    constraints: dict
    summary: str
    score: float
    kind: str


def tally_from_db(db, pilot: str, since: float | None = None, until: float | None = None) -> dict:
    """Progress from verified (completed) task results in the shared store.

    Used by the coordinator (all runs) and by mas/report.py (one run's time window).
    """
    t = Counter()
    q = "SELECT skill, result_json FROM a2a_tasks WHERE pilot=? AND status='completed'"
    args: list = [pilot]
    if since is not None:
        q, args = q + ' AND created_at>=?', args + [since]
    if until is not None:
        q, args = q + ' AND created_at<=?', args + [until]
    for row in db.execute(q, args):
        res = json.loads(row['result_json'] or '{}')
        d, ev = res.get('data') or {}, res.get('evidence') or {}
        before, after = ev.get('before') or {}, ev.get('after') or {}
        if row['skill'] == 'mine':
            t['ore_mined'] += d.get('total', 0) or 0
        elif row['skill'] in ('sell', 'complete_mission'):
            t['credits_earned'] += max(0, d.get('credits_gained', 0) or 0)
            if row['skill'] == 'sell' and (d.get('sold') or 0) > 0:
                t['sales'] += 1
        elif row['skill'] in ('buy_order', 'refuel', 'list_sell_order'):
            if before.get('credits') is not None and after.get('credits') is not None:
                t['spent'] += max(0, before['credits'] - after['credits'])
            if row['skill'] == 'list_sell_order':
                t['sales'] += 1   # listed at the best bid -> fills immediately (verify on profile)
    return {'credits_earned': t['credits_earned'], 'ore_mined': t['ore_mined'], 'sales': t['sales'],
            'spent': t['spent']}


def load_config(path: str | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path:
        if not Path(path).exists():
            raise SystemExit(f'config file {path} not found. Create it from the example:\n'
                             f'  cp config/mission.example.json {path}      (Windows: copy)\n'
                             f'then set "pilots" in it.')
        user = json.loads(Path(path).read_text())
        for k, v in user.items():
            if k.startswith('_'):
                continue
            cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


class A2ADispatcher:
    """Sends tasks to worker processes over A2A (one WorkerClient per role)."""

    def __init__(self, urls: dict[str, str]):
        self.urls = urls
        self.clients: dict[str, WorkerClient] = {}

    async def run(self, role: str, req: TaskRequest) -> tuple[TaskResult, str]:
        client = self.clients.get(role)
        if client is None:
            client = WorkerClient(self.urls[role])
            await client.connect()
            self.clients[role] = client
        try:
            return await client.run_task(req)
        except WorkerUnavailable:
            await client.close()
            self.clients.pop(role, None)   # rediscover the card next time (worker may have restarted)
            raise

    async def close(self):
        for c in self.clients.values():
            await c.close()


class Coordinator:
    def __init__(self, cfg: dict, store: Store, dispatcher, llm: LLM | None, *,
                 sleep=asyncio.sleep, clock=time.time, log_path: str | None = None):
        self.cfg, self.store, self.dispatcher, self.llm = cfg, store, dispatcher, llm
        self.sleep, self.clock = sleep, clock
        self._log_kw = {'path': log_path} if log_path else {}
        self.failures: Counter = Counter()           # (pilot, option id) -> consecutive failures
        self.wait_until: dict[str, float] = {}
        self.last_plan: dict[str, tuple[frozenset, str, str]] = {}   # pilot -> (option ids, choice, mission)
        self.observe_mission: dict[str, str] = {}
        self.stats = Counter()
        self.dirty: set[str] = set()       # pilots whose mission progress must be re-read (after acting)
        self.needs_recover = False         # a worker was unreachable -> reconcile open missions

    def log(self, event: str, data: dict, task_id: str | None = None):
        record(event, agent='coordinator', task_id=task_id, data=data, **self._log_kw)

    # ================================================================ main loop
    async def run(self, max_rounds: int | None = None):
        await self.recover()
        await asyncio.gather(*(self.pilot_loop(p, max_rounds) for p in self.cfg['pilots']))
        self.log('coordinator.finished', {'stats': dict(self.stats),
                                          'tally': {p: self.tally(p) for p in self.cfg['pilots']}})

    async def pilot_loop(self, pilot: str, max_rounds: int | None):
        rounds = 0
        while max_rounds is None or rounds < max_rounds:
            rounds += 1
            if not await self.step(pilot):
                break

    async def step(self, pilot: str) -> bool:
        """One observe-decide-delegate-verify round. Returns False when this pilot is finished."""
        if self.needs_recover:
            self.needs_recover = False
            await self.recover()
        view = await self.observe(pilot)
        if view is None:
            await self.sleep(self.cfg['idle_seconds'])
            return True
        tally = self.tally(pilot)
        if self.targets_met(tally):
            self.log('pilot.targets_met', {'pilot': pilot, 'tally': tally})
            if not view['status']['docked']:
                await self.execute(pilot, self._opt_return(), 'rule', 'targets met: park the ship docked')
            return False
        if self.clock() < self.wait_until.get(pilot, 0):
            await self.sleep(min(30, self.wait_until[pilot] - self.clock()))
            return True
        options = self.build_options(pilot, view, tally)
        if not options:
            self.log('coordinator.no_options', {'pilot': pilot})
            await self.sleep(self.cfg['idle_seconds'])
            return True
        choice, by, why = await self.decide(pilot, view, tally, options)
        self.log('coordinator.decision', {'pilot': pilot, 'choice': choice.id, 'decided_by': by,
                                          'rationale': why, 'options': [o.id for o in options]})
        if choice.kind == 'wait':
            self.wait_until[pilot] = self.clock() + choice.params['seconds']
            return True
        await self.execute(pilot, choice, by, why)
        return True

    # ================================================================ observe
    async def observe(self, pilot: str) -> dict | None:
        obs, fresh = self.store.observations, self.cfg['freshness_seconds']
        st = obs.fresh(pilot, 'status', fresh['status'])
        if st is None:
            r = await self.observe_task(pilot, 'resource', 'status')
            if r is None:
                return None
            st = r.data['status']
        active = obs.fresh(pilot, 'active_missions', fresh['active_missions'])
        if active is None or pilot in self.dirty:     # never plan on progress read before our last action
            self.dirty.discard(pilot)
            r = await self.observe_task(pilot, 'trading', 'active_missions')
            active = {'missions': r.data['missions']} if r else {'missions': []}
        board, market = obs.latest(pilot, 'missions_board'), obs.latest(pilot, 'market')
        if st['docked'] and (board is None or board['age'] > fresh['missions_board']):
            r = await self.observe_task(pilot, 'trading', 'missions_board')
            board = {'data': {'missions': r.data['missions']}, 'age': 0} if r else board
        if st['docked'] and (market is None or market['age'] > fresh['market']):
            r = await self.observe_task(pilot, 'trading', 'market', {'category': 'ore'})
            market = {'data': {'rows': r.data['rows']}, 'age': 0} if r else market
        belt, belt_age = self._latest_belt(pilot)
        return {'status': st, 'active': active['missions'],
                'board': board['data']['missions'] if board else [],
                'market': market['data']['rows'] if market else [],
                'belt': belt, 'belt_age': belt_age}

    def _latest_belt(self, pilot: str):
        rows = self.store.db.execute(
            "SELECT data_json, observed_at FROM observations WHERE pilot=? AND kind='poi' "
            'ORDER BY observed_at DESC LIMIT 50', (pilot,)).fetchall()
        for r in rows:
            data = json.loads(r['data_json'])
            if data.get('id') == self.cfg['belt_poi']:
                return data.get('resources') or [], self.clock() - r['observed_at']
        return None, None

    async def observe_task(self, pilot: str, role: str, skill: str, params: dict | None = None) -> TaskResult | None:
        mid = self.observe_mission.get(pilot)
        if mid is None:
            mid = self.store.missions.create(f'observe game state for {pilot}', decided_by='rule', pilot=pilot,
                                             rationale='fresh observations before every decision')
            self.store.missions.transition(mid, 'assigned')
            self.store.missions.transition(mid, 'in_progress')
            self.observe_mission[pilot] = mid
        self.stats['observe_tasks'] += 1
        req = TaskRequest(task_id=f'{mid}:{skill}:{self.stats["observe_tasks"]}', mission_id=mid, skill=skill,
                          pilot=pilot, params=params or {}, issued_by='coordinator',
                          rationale='observation older than freshness limit')
        self.store.tasks.create(mid, assignee=role, skill=skill, pilot=pilot,
                                payload={'params': req.params, 'constraints': {}}, task_id=req.task_id)
        r = await self._dispatch(role, req)
        return r if r is not None and r.ok else None

    # ================================================================ options
    def build_options(self, pilot: str, view: dict, tally: dict) -> list[Option]:
        lim = self.cfg['limits']
        st = view['status']
        opts: list[Option] = []
        cargo = {item_id_from_name(n): q for n, q in (st.get('cargo') or {}).items() if q > 0}
        free = (st['cargo_max'] or 0) - (st['cargo_used'] or 0)
        bids = {r['item_id']: r['best_buy'] for r in view['market'] if r.get('best_buy')}
        asks = {r['item_id']: (r['best_sell'], r['sell_qty']) for r in view['market'] if r.get('best_sell')}
        belt_left = {d['resource']: d['remaining'] for d in view['belt']} if view['belt'] is not None else None
        budget_left = lim['max_spend_total_per_pilot'] - tally['spent']
        spend_cap = min(lim['max_spend_per_task'], budget_left)

        def ore_available(item: str) -> bool:
            return belt_left is None or belt_left.get(item, 0) > 0

        # refuel is forced when low
        if (st['fuel'] or 0) < lim['min_fuel'] and spend_cap > 0:
            opts.append(Option('refuel', 'trading', 'refuel', {'min_fuel': lim['min_fuel']},
                               {'max_spend': spend_cap}, f"refuel (fuel {st['fuel']})", 95, 'refuel'))

        # A. accepted missions
        active_titles = set()
        for m in view['active']:
            active_titles.add(m['title'])
            prog = m.get('progress') or []
            if prog and all(d >= t for d, t in prog):
                opts.append(Option(f"complete:{m['id']}", 'trading', 'complete_mission', {'instance_id': m['id']}, {},
                                   f"claim reward of finished mission {m['title']}", 100, 'complete'))
                continue
            for obj, (done, total) in zip([o for o in m['objectives'] if re.search(r': \d+/\d+$', o)], prog):
                need = total - done
                if need <= 0:
                    continue
                if mm := OBJ_MINE.match(obj):
                    item = mm.group(2)
                    if ore_available(item) and free > 1:
                        cycles = min(lim['max_cycles_per_mine_task'], max(need * 3, 5))
                        opts.append(Option(f'mine_for:{m["id"]}', 'resource', 'mine',
                                           {'poi': self.cfg['belt_poi'], 'target_item': item, 'target_qty': need},
                                           {'max_cycles': cycles},
                                           f"mine {need} {item} for {m['title']} (belt has "
                                           f"{belt_left.get(item, '?') if belt_left else '?'})", 70, 'mine'))
                elif OBJ_SELL.match(obj):
                    cands = sorted(((bids[i], i, q) for i, q in cargo.items() if bids.get(i)), reverse=True)
                    if cands:
                        bid, item, q = cands[0]
                        opts.append(Option(f'sell_order_for:{m["id"]}', 'trading', 'list_sell_order',
                                           {'item_id': item, 'quantity': min(q, need), 'price_each': bid},
                                           {}, f'list {min(q, need)} {item} at the best bid {bid} cr '
                                               f"(fills now) for {m['title']}", 65, 'sell_order'))
                elif OBJ_BUY.match(obj):
                    cands = sorted((price, i) for i, (price, qty) in asks.items() if qty >= need and price)
                    if cands and cands[0][0] * need <= spend_cap:
                        price, item = cands[0]
                        opts.append(Option(f'buy_for:{m["id"]}', 'trading', 'buy_order',
                                           {'item_id': item, 'quantity': need, 'price_each': price},
                                           {'max_spend': price * need},
                                           f"buy {need} {item} at the best ask {price} cr ({price * need} cr) "
                                           f"for {m['title']}", 60, 'buy_order'))

        # B. accept feasible, safe missions
        if len(view['active']) < lim['max_active_missions'] and st['docked']:
            offers = []
            for b in view['board']:
                if not b.get('safe') or b['title'] in active_titles:
                    continue
                kinds = []
                for obj in b['objectives']:
                    if mm := OBJ_MINE.match(obj):
                        kinds.append('mine' if ore_available(mm.group(2)) else 'infeasible')
                    elif OBJ_SELL.match(obj):
                        kinds.append('sell')
                    elif OBJ_BUY.match(obj):
                        kinds.append('buy')
                    else:
                        kinds.append('unknown')
                if not kinds or any(k in ('infeasible', 'unknown') for k in kinds):
                    continue
                offers.append(Option(f"accept:{b['id']}", 'trading', 'accept_mission', {'template_id': b['id']}, {},
                                     f"accept {b['title']} ({'; '.join(b['objectives'])}) reward "
                                     f"{b['reward_credits']} cr", 50 + b['reward_credits'] / 1000, 'accept'))
            opts += sorted(offers, key=lambda o: -o.score)[:4]

        # C. sell cargo into existing bids
        for item, q in cargo.items():
            if bids.get(item, 0) >= lim['min_sell_price']:
                opts.append(Option(f'sell:{item}', 'trading', 'sell',
                                   {'item_id': item, 'quantity': 'all', 'min_price': bids[item]}, {},
                                   f'sell {q} {item} into bid {bids[item]} cr', 35, 'sell'))

        # D. generic mining for the ore target
        if tally['ore_mined'] < self.cfg['targets_per_pilot']['ore_mined'] and free > 1:
            if belt_left is None or any(v > 0 for v in belt_left.values()):
                opts.append(Option('mine', 'resource', 'mine', {'poi': self.cfg['belt_poi']},
                                   {'max_cycles': lim['max_cycles_per_mine_task']},
                                   'mine any ore at the belt (ore target not met)', 30, 'mine'))
            else:
                opts.append(Option('wait', 'none', 'wait', {'seconds': self.cfg['wait_seconds_when_belt_empty']}, {},
                                   'belt empty: wait for deposits to regenerate', 5, 'wait'))

        # E. go back to the station when the hold is nearly full
        if not st['docked'] and free < 5:
            opts.append(self._opt_return(score=40))

        opts = [o for o in opts if self.failures[(pilot, o.id)] < 2]
        return sorted(opts, key=lambda o: -o.score)

    def _opt_return(self, score: float = 20) -> Option:
        return Option('return', 'resource', 'return_to_station', {'station_poi': self.cfg['station_poi']}, {},
                      'fly back to the station and dock', score, 'return')

    # ================================================================ decide
    async def decide(self, pilot: str, view: dict, tally: dict, options: list[Option]) -> tuple[Option, str, str]:
        forced = [o for o in options if o.kind in ('complete', 'refuel')]
        if forced:
            return forced[0], 'rule', f'forced rule: {forced[0].summary}'
        if len(options) == 1:
            return options[0], 'rule', f'only valid option: {options[0].summary}'
        ids = frozenset(o.id for o in options)
        prev = self.last_plan.get(pilot)
        if prev and prev[0] == ids and self.failures[(pilot, prev[1])] == 0:
            same = next(o for o in options if o.id == prev[1])
            return same, 'rule', f'state unchanged since LLM plan in mission {prev[2]}: continue "{same.summary}"'
        if self.llm is not None and self.llm.available and self.cfg['llm']['enabled']:
            payload = self._llm_payload(pilot, view, tally, options)
            resp = await self.llm.choose_json(SYSTEM_PROMPT, payload, purpose='choose_next_action', task_id=pilot)
            if resp and resp.get('choice') in ids:
                choice = next(o for o in options if o.id == resp['choice'])
                why = str(resp.get('rationale', ''))[:300] or 'LLM choice'
                self.last_plan[pilot] = (ids, choice.id, '?')
                self.stats['llm_decisions'] += 1
                return choice, 'llm', why
            if resp is not None:
                self.log('llm.invalid_choice', {'pilot': pilot, 'response': str(resp)[:300]})
        self.stats['fallback_decisions'] += 1
        return options[0], 'rule', f'heuristic fallback (highest score {options[0].score:.0f}): {options[0].summary}'

    def _llm_payload(self, pilot, view, tally, options) -> dict:
        st = view['status']
        recent = [{'objective': m['objective'], 'status': m['status'],
                   'result': (m.get('result') or {}).get('summary', '')[:120]}
                  for m in self.store.missions.recent(8) if m['pilot'] == pilot and m['decided_by'] != 'rule'
                  or (m['pilot'] == pilot and m['status'] == 'failed')][:4]
        return {
            'pilot': pilot,
            'ship': {'credits': st['credits'], 'fuel': f"{st['fuel']}/{st['fuel_max']}",
                     'cargo': st.get('cargo'), 'free_cargo': (st['cargo_max'] or 0) - (st['cargo_used'] or 0),
                     'docked': st['docked']},
            'progress_vs_target': {k: f"{tally.get(k, 0)}/{v}" for k, v in self.cfg['targets_per_pilot'].items()},
            'spent_so_far': tally['spent'],
            'belt': {'deposits': view['belt'] and [{d['resource']: d['remaining']} for d in view['belt']],
                     'age_s': int(view['belt_age']) if view['belt_age'] is not None else None},
            'active_missions': [{'title': m['title'], 'progress': m.get('progress')} for m in view['active']],
            'recent_outcomes': recent,
            'options': [{'id': o.id, 'action': o.summary, 'score': round(o.score)} for o in options],
        }

    # ================================================================ delegate + verify
    async def execute(self, pilot: str, opt: Option, decided_by: str, rationale: str) -> TaskResult | None:
        ms = self.store.missions
        mid = ms.create(opt.summary, decided_by=decided_by, pilot=pilot, rationale=rationale,
                        constraints=opt.constraints, plan={'option': asdict(opt)})
        if decided_by == 'llm' and pilot in self.last_plan:
            self.last_plan[pilot] = (*self.last_plan[pilot][:2], mid)
        ms.transition(mid, 'assigned', note=f'-> {opt.role} worker')
        req = TaskRequest(task_id=f'{mid}:{opt.skill}:1', mission_id=mid, skill=opt.skill, pilot=pilot,
                          params=opt.params, constraints=opt.constraints, issued_by='coordinator',
                          rationale=rationale)
        self.store.tasks.create(mid, assignee=opt.role, skill=opt.skill, pilot=pilot,
                                payload={'params': opt.params, 'constraints': opt.constraints}, task_id=req.task_id)
        ms.transition(mid, 'in_progress')
        result = await self._dispatch(opt.role, req)
        if result is None:
            return None          # task 'unknown'; mission stays in_progress and is resent by recover()
        self._finish(pilot, mid, opt, result)
        return result

    async def _dispatch(self, role: str, req: TaskRequest) -> TaskResult | None:
        self._mark(req.task_id, 'submitted')
        try:
            result, a2a_id = await self.dispatcher.run(role, req)
        except WorkerUnavailable as e:
            self._mark(req.task_id, 'unknown', error=str(e)[:300])
            self.stats['worker_unavailable'] += 1
            self.needs_recover = True
            self.log('worker.unavailable', {'role': role, 'error': str(e)[:300]}, req.task_id)
            await self.sleep(self.cfg['idle_seconds'])
            return None
        if result.status == 'needs_reconcile' and (result.error or {}).get('code') == 'task_in_progress':
            self.needs_recover = True
            await self.sleep(self.cfg['idle_seconds'])
            return None
        self.log('coordinator.task_result', {'role': role, 'skill': req.skill, 'status': result.status,
                                             'summary': result.summary, 'a2a_task_id': a2a_id}, req.task_id)
        return result

    def _mark(self, task_id: str, status: str, **kw):
        try:
            self.store.tasks.mark(task_id, status, **kw)
        except IllegalTransition:
            pass   # the worker already recorded a final state; its record wins

    def _finish(self, pilot: str, mid: str, opt: Option, result: TaskResult):
        ms = self.store.missions
        self.dirty.add(pilot)
        ms.transition(mid, 'verifying')
        ok, why = self.verify(opt, result)
        if opt.skill == 'mine' and (result.data or {}).get('stop_reason') in ('belt_depleted',):
            self.wait_until[pilot] = self.clock() + self.cfg['wait_seconds_when_belt_empty']
        self.failures[(pilot, opt.id)] = 0 if ok else self.failures[(pilot, opt.id)] + 1
        ms.transition(mid, 'done' if ok else 'failed', note=why,
                      result={'status': result.status, 'summary': result.summary, 'verified': ok, 'why': why,
                              'data': result.data, 'error': result.error})
        self.stats['missions_done' if ok else 'missions_failed'] += 1
        self.log('mission.verified', {'mission_id': mid, 'ok': ok, 'why': why, 'summary': result.summary})

    @staticmethod
    def verify(opt: Option, r: TaskResult) -> tuple[bool, str]:
        """Accept a result only with game evidence that the intended change happened."""
        if not r.ok:
            return False, f"worker reported {r.status}: {(r.error or {}).get('code')}"
        d, ev = r.data or {}, r.evidence or {}
        before, after = ev.get('before') or {}, ev.get('after') or {}
        checks = {
            'mine': (d.get('total', 0) > 0, f"mined {d.get('total', 0)}; cargo {before.get('cargo_used')} -> "
                                            f"{after.get('cargo_used')}"),
            'sell': (d.get('credits_gained', 0) > 0, f"credits +{d.get('credits_gained')}"),
            'complete_mission': (d.get('credits_gained', 0) > 0, f"credits +{d.get('credits_gained')}"),
            'accept_mission': (bool(d.get('instance_id')), f"instance {d.get('instance_id')}"),
            'list_sell_order': (bool(d.get('order_id')), f"order {d.get('order_id')}"),
            'buy_order': (bool(d.get('order_id')), f"order {d.get('order_id')}"),
            'return_to_station': (bool(after.get('docked_at')), f"docked at {after.get('docked_at')}"),
        }
        return checks.get(opt.skill, (True, 'completed'))

    # ================================================================ progress
    def tally(self, pilot: str) -> dict:
        return tally_from_db(self.store.db, pilot)

    def targets_met(self, tally: dict) -> bool:
        return all(tally.get(k, 0) >= v for k, v in self.cfg['targets_per_pilot'].items())

    # ================================================================ restart recovery
    async def recover(self):
        """Resend unfinished tasks of open coordinator missions with the SAME task id."""
        for t in self.store.tasks.unfinished():
            m = self.store.missions.get(t['mission_id'])
            if m is None or m['status'] not in ('assigned', 'in_progress') or m['pilot'] not in self.cfg['pilots']:
                continue
            opt_d = (m.get('plan') or {}).get('option')
            if not opt_d and not m['objective'].startswith('observe game state'):
                continue   # not a coordinator mission (e.g. a manual send_task test)
            req = TaskRequest(task_id=t['task_id'], mission_id=m['mission_id'], skill=t['skill'], pilot=t['pilot'],
                              params=(t['payload'] or {}).get('params', {}),
                              constraints=(t['payload'] or {}).get('constraints', {}),
                              issued_by='coordinator', rationale=f'resent after restart ({t["status"]})')
            self.log('coordinator.resend', {'mission_id': m['mission_id'], 'previous_status': t['status']},
                     t['task_id'])
            self.stats['resent'] += 1
            result = await self._dispatch(t['assignee'], req)
            if result is not None and opt_d:
                self._finish(t['pilot'], m['mission_id'], Option(**opt_d), result)
        # Missions whose task already finished but whose reply never reached us (lost reply / crash
        # between the worker finishing and us verifying): close them from the stored task result.
        for m in self.store.missions.open():
            opt_d = (m.get('plan') or {}).get('option')
            if m['status'] != 'in_progress' or not opt_d or m['pilot'] not in self.cfg['pilots']:
                continue
            tasks = self.store.tasks.for_mission(m['mission_id'])
            done = [t for t in tasks if t['status'] in ('completed', 'failed') and t.get('result')]
            if tasks and len(done) == len(tasks):
                self.log('coordinator.adopt_result', {'mission_id': m['mission_id']}, done[-1]['task_id'])
                self._finish(m['pilot'], m['mission_id'], Option(**opt_d), TaskResult(**done[-1]['result']))
        for m in self.store.missions.open():
            if m['status'] in ('proposed', 'assigned') and not self.store.tasks.for_mission(m['mission_id']):
                self.store.missions.transition(m['mission_id'], 'cancelled', note='no task at restart')
            elif (m['status'] == 'in_progress' and m['objective'].startswith('observe game state')
                  and m['mission_id'] not in self.observe_mission.values()):   # a previous run's
                self.store.missions.transition(m['mission_id'], 'verifying')
                self.store.missions.transition(m['mission_id'], 'done', note='observation mission closed at restart')


async def main_async(a):
    cfg = load_config(a.config)
    if a.no_llm:
        cfg['llm']['enabled'] = False
    store = Store(agent='coordinator')
    llm = LLM(max_calls=cfg['llm']['max_calls_per_run']) if cfg['llm']['enabled'] else None
    if llm is not None and not llm.available:
        print('[coordinator] no GROQ_API_KEY: deterministic fallback decisions only')
    print(f"[coordinator] pilots={cfg['pilots']} workers={cfg['workers']} targets={cfg['targets_per_pilot']}")
    if llm is not None:
        print(f'[coordinator] LLM budget before run: {llm.usage()}')
    dispatcher = A2ADispatcher(cfg['workers'])
    coord = Coordinator(cfg, store, dispatcher, llm)
    start = time.time()
    print(f'[coordinator] START {start:.0f}')
    try:
        await coord.run(max_rounds=a.rounds)
    finally:
        await dispatcher.close()
        end = time.time()
        print(f'[coordinator] END {end:.0f}  ->  python -m mas.report --pilot {cfg["pilots"][0]} '
              f'--since {start:.0f} --until {end:.0f} --label MAS')
        print(f'[coordinator] stats: {dict(coord.stats)}')
        for p in cfg['pilots']:
            print(f'[coordinator] {p} tally: {coord.tally(p)}')
        if llm is not None:
            print(f'[coordinator] LLM budget after run: {llm.usage()}')


def main():
    p = argparse.ArgumentParser(description='SpaceMolt MAS coordinator')
    p.add_argument('--config', default=None, help='JSON config (see config/mission.example.json)')
    p.add_argument('--rounds', type=int, default=None, help='stop after N decisions per pilot')
    p.add_argument('--no-llm', action='store_true', help='deterministic decisions only (baseline/testing)')
    asyncio.run(main_async(p.parse_args()))


if __name__ == '__main__':
    main()
