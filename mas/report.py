"""Summarise one run (or compare several) from the shared store, the events log and the LLM ledger.

    python -m mas.report --pilot Prac-Ahmed1 --since 1795157000 --until 1795160000 --label MAS
    python -m mas.report --pilot Prac-Ahmed1 --compare MAS:1795157000:1795160000 BASE:1795161000:1795164000

Prints a Markdown table (paste into the report). Everything is computed from recorded evidence:
completed task results (credits/cargo before vs after), mission outcomes, ledger action states,
JSONL events and the LLM budget ledger. Use --out to also write the table to a file.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from mas.coordinator import tally_from_db
from mas.store import DEFAULT_DB, connect

EVENTS = Path('logs/events.jsonl')
BUDGET_DB = Path('logs/budget.sqlite3')
EVENT_KINDS = ('llm.call', 'llm.error', 'llm.invalid_choice', 'worker.unavailable', 'coordinator.resend',
               'coordinator.adopt_result', 'mcp.relogin', 'mcp.wait', 'mcp.retry', 'mcp.ambiguous',
               'mcp.duplicate_skipped', 'action.reconciled', 'worker.recovered', 'task.duplicate_returned')


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def summarise(db: sqlite3.Connection, pilot: str, since: float, until: float) -> dict:
    s: dict = {'minutes': round((until - since) / 60, 1)}
    s.update(tally_from_db(db, pilot, since, until))
    tasks = Counter(r['status'] for r in db.execute(
        'SELECT status FROM a2a_tasks WHERE pilot=? AND created_at BETWEEN ? AND ?', (pilot, since, until)))
    s['tasks'] = sum(tasks.values())
    s['tasks_failed'] = tasks.get('failed', 0)
    ms = list(db.execute('SELECT status, decided_by FROM missions WHERE pilot=? AND created_at BETWEEN ? AND ? '
                         "AND objective NOT LIKE 'observe game state%'", (pilot, since, until)))
    s['missions_done'] = sum(1 for m in ms if m['status'] == 'done')
    s['missions_failed'] = sum(1 for m in ms if m['status'] == 'failed')
    s['decided_by_llm'] = sum(1 for m in ms if m['decided_by'] == 'llm')
    s['decided_by_rule'] = sum(1 for m in ms if m['decided_by'] == 'rule')
    acts = Counter(r['status'] for r in db.execute(
        'SELECT status FROM actions WHERE pilot=? AND created_at BETWEEN ? AND ?', (pilot, since, until)))
    s['game_actions'] = sum(acts.values())
    s['game_actions_rejected'] = acts.get('failed', 0)
    s['game_actions_unknown'] = acts.get('unknown', 0) + acts.get('pending', 0)
    ev = Counter()
    tokens = 0
    if EVENTS.exists():
        for line in EVENTS.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = _ts(e['time_utc'])
            if since <= t <= until and e['event'] in EVENT_KINDS:
                ev[e['event']] += 1
                if e['event'] == 'llm.call':
                    tokens += (e['data'].get('tokens_in') or 0) + (e['data'].get('tokens_out') or 0)
    s['llm_calls'] = ev['llm.call']
    s['llm_tokens'] = tokens
    s['credits_per_hour'] = round(s['credits_earned'] / max(s['minutes'] / 60, 1e-9))
    s['ore_per_hour'] = round(s['ore_mined'] / max(s['minutes'] / 60, 1e-9), 1)
    s['recovery_events'] = {k: v for k, v in ev.items() if k != 'llm.call'}
    return s


def budget_totals() -> dict:
    if not BUDGET_DB.exists():
        return {}
    db = sqlite3.connect(BUDGET_DB)
    try:
        n, tok = db.execute("SELECT COUNT(*), COALESCE(SUM(input_tokens+output_tokens),0) FROM usage "
                            "WHERE status IN ('ok','reserved','failed')").fetchone()
        return {'requests': n, 'tokens': tok, 'cap_requests': 300, 'cap_tokens': 250000}
    finally:
        db.close()


ROWS = ['minutes', 'credits_earned', 'ore_mined', 'sales', 'spent', 'credits_per_hour', 'ore_per_hour',
        'missions_done', 'missions_failed', 'decided_by_llm', 'decided_by_rule', 'tasks', 'tasks_failed',
        'game_actions', 'game_actions_rejected', 'game_actions_unknown', 'llm_calls', 'llm_tokens']


def markdown(results: dict[str, dict]) -> str:
    labels = list(results)
    out = ['| metric | ' + ' | '.join(labels) + ' |', '|---|' + '---|' * len(labels)]
    for r in ROWS:
        out.append(f'| {r} | ' + ' | '.join(str(results[l].get(r, '')) for l in labels) + ' |')
    for l in labels:
        if results[l]['recovery_events']:
            out.append(f"\n*{l} recovery/robustness events:* " +
                       ', '.join(f'{k}={v}' for k, v in sorted(results[l]['recovery_events'].items())))
    b = budget_totals()
    if b:
        out.append(f"\n*LLM ledger (all runs in logs/budget.sqlite3):* {b['requests']}/{b['cap_requests']} requests, "
                   f"{b['tokens']}/{b['cap_tokens']} tokens.")
    return '\n'.join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pilot', required=True)
    p.add_argument('--db', default=str(DEFAULT_DB))
    p.add_argument('--since', type=float, help='epoch seconds (printed by coordinator/baseline)')
    p.add_argument('--until', type=float)
    p.add_argument('--label', default='run')
    p.add_argument('--compare', nargs='*', help='LABEL:SINCE:UNTIL entries')
    p.add_argument('--out')
    a = p.parse_args()
    db = connect(a.db)
    runs: dict[str, dict] = {}
    if a.compare:
        for spec in a.compare:
            label, since, until = spec.split(':')
            runs[label] = summarise(db, a.pilot, float(since), float(until))
    else:
        runs[a.label] = summarise(db, a.pilot, a.since or 0, a.until or 1e12)
    text = markdown(runs)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + '\n', encoding='utf-8')
        print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
