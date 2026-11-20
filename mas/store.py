"""Durable state in SQLite, shared by every agent process (logs/state.sqlite3).

Tables and who writes them
--------------------------
actions       MCP gateway      every state-changing game call, keyed by idempotency key
missions      coordinator      what we decided to do, why (rationale), and the outcome
a2a_tasks     coordinator      each task handed to a worker over A2A, and its result
pilot_leases  workers          which agent currently steers which pilot (expiring lock)
observations  any agent        timestamped game snapshots; stale ones are rejected

All of it survives a crash: on restart an agent reads its unfinished tasks,
re-observes the game, and continues without repeating confirmed actions.

Why a ledger?  A state-changing game action (sell, mine, accept_mission) must
never be executed twice just because a process crashed or a call was retried.
Every such action gets an idempotency key chosen by the caller, e.g.
"mission-17:sell:copper_ore".  Before calling the game we look the key up:

    confirmed -> already done; return the stored result, do NOT call again
    pending / unknown -> outcome not known; caller must re-observe the game first
    failed    -> server rejected it, nothing happened; safe to try again
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'logs' / 'state.sqlite3'

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions(
    idempotency_key TEXT PRIMARY KEY,
    pilot      TEXT NOT NULL,
    agent      TEXT NOT NULL,
    task_id    TEXT,
    tool       TEXT NOT NULL,
    action     TEXT,
    args_json  TEXT NOT NULL,          -- already redacted
    status     TEXT NOT NULL CHECK(status IN ('pending','confirmed','failed','unknown')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    result_text TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS actions_by_task ON actions(task_id);

CREATE TABLE IF NOT EXISTS missions(
    mission_id   TEXT PRIMARY KEY,         -- our id, e.g. 'M-20261120-0007'
    parent_id    TEXT,                     -- retry of / sub-mission of
    objective    TEXT NOT NULL,            -- e.g. 'complete game mission first_cargo with pilot A'
    pilot        TEXT,
    status       TEXT NOT NULL CHECK(status IN
                 ('proposed','assigned','in_progress','verifying','done','failed','cancelled')),
    decided_by   TEXT NOT NULL,            -- 'llm' | 'rule' | 'human-config'
    rationale    TEXT,                     -- why this was chosen (shown in the demo)
    constraints_json TEXT NOT NULL DEFAULT '{}',
    plan_json    TEXT NOT NULL DEFAULT '{}',
    result_json  TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS a2a_tasks(
    task_id      TEXT PRIMARY KEY,         -- our task id, also sent inside the A2A message
    mission_id   TEXT NOT NULL REFERENCES missions(mission_id),
    a2a_task_id  TEXT,                     -- id assigned by the worker's A2A server
    assignee     TEXT NOT NULL,            -- worker role: 'resource' | 'trading'
    skill        TEXT NOT NULL,            -- e.g. 'mine', 'sell', 'accept_mission'
    pilot        TEXT,
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL CHECK(status IN
                 ('created','submitted','working','completed','failed','unknown','cancelled')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    result_json  TEXT,
    error        TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_by_status ON a2a_tasks(assignee, status);

CREATE TABLE IF NOT EXISTS pilot_leases(
    pilot       TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,             -- agent name
    task_id     TEXT,
    acquired_at REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS observations(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pilot       TEXT NOT NULL,
    kind        TEXT NOT NULL,             -- 'status' | 'poi' | 'market' | 'missions' | ...
    data_json   TEXT NOT NULL,             -- parsed, redacted data
    source      TEXT NOT NULL,             -- e.g. 'spacemolt.get_status'
    observed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS obs_latest ON observations(pilot, kind, observed_at);
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open the shared DB. WAL mode lets several processes read while one writes."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)  # autocommit; we use explicit BEGIN
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=30000')
    db.executescript(SCHEMA)
    return db


@dataclass
class ActionRecord:
    key: str
    status: str
    attempts: int
    error_code: str | None
    result_text: str | None


class ActionLedger:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, key: str) -> ActionRecord | None:
        row = self.db.execute('SELECT * FROM actions WHERE idempotency_key=?', (key,)).fetchone()
        if not row:
            return None
        return ActionRecord(row['idempotency_key'], row['status'], row['attempts'],
                            row['error_code'], row['result_text'])

    def begin(self, key: str, *, pilot: str, agent: str, task_id: str | None,
              tool: str, action: str | None, args: dict) -> tuple[bool, ActionRecord]:
        """Atomically claim `key` for a new attempt.

        Returns (False, existing) if the key is confirmed/pending/unknown: the caller
        must NOT execute. Otherwise marks it pending and returns (True, record).
        """
        now = time.time()
        self.db.execute('BEGIN IMMEDIATE')  # lock so two processes cannot claim the same key
        try:
            existing = self.get(key)
            if existing and existing.status != 'failed':
                self.db.execute('COMMIT')
                return False, existing
            if existing:  # failed before -> retry
                self.db.execute(
                    "UPDATE actions SET status='pending', attempts=attempts+1, error_code=NULL, "
                    "agent=?, task_id=?, updated_at=? WHERE idempotency_key=?", (agent, task_id, now, key))
            else:
                self.db.execute(
                    "INSERT INTO actions(idempotency_key,pilot,agent,task_id,tool,action,args_json,status,"
                    "attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',1,?,?)",
                    (key, pilot, agent, task_id, tool, action, json.dumps(args, sort_keys=True), now, now))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        rec = self.get(key)
        assert rec is not None
        return True, rec

    def finish(self, key: str, status: str, *, result_text: str | None = None,
               error_code: str | None = None) -> None:
        assert status in ('confirmed', 'failed', 'unknown')
        self.db.execute('UPDATE actions SET status=?, result_text=?, error_code=?, updated_at=? '
                        'WHERE idempotency_key=?',
                        (status, (result_text or '')[:4000], error_code, time.time(), key))

    def resolve(self, key: str, status: str, note: str = '') -> None:
        """After re-observing the game, settle an 'unknown'/'pending' action manually."""
        assert status in ('confirmed', 'failed')
        self.db.execute("UPDATE actions SET status=?, result_text=COALESCE(result_text, '') || ?, updated_at=? "
                        "WHERE idempotency_key=?", (status, f'\n[resolved] {note}', time.time(), key))

    def unsettled(self, pilot: str | None = None) -> list[sqlite3.Row]:
        """Actions whose outcome is unknown — checked on every restart."""
        q = "SELECT * FROM actions WHERE status IN ('pending','unknown')"
        args: tuple = ()
        if pilot:
            q += ' AND pilot=?'
            args = (pilot,)
        return self.db.execute(q, args).fetchall()


# =====================================================================  Phase 3
class StoreError(Exception):
    """Base class for store errors."""


class IllegalTransition(StoreError):
    """A status change that the state machine does not allow (e.g. done -> in_progress)."""


def _dumps(value) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _row(row: sqlite3.Row | None) -> dict | None:
    """Row -> dict, decoding every *_json column into `<name>` (without the suffix)."""
    if row is None:
        return None
    out = {}
    for k in row.keys():
        v = row[k]
        if k.endswith('_json'):
            out[k[:-5]] = json.loads(v) if v else None
        else:
            out[k] = v
    return out


def _new_id(prefix: str, clock: Callable[[], float]) -> str:
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime(clock()))
    return f'{prefix}-{stamp}-{uuid.uuid4().hex[:6]}'


class _Base:
    def __init__(self, db: sqlite3.Connection, clock: Callable[[], float] = time.time,
                 log: Callable[[str, dict], None] | None = None):
        self.db, self.clock = db, clock
        self._log = log or (lambda event, data: None)

    def _tx(self):
        """Context manager: BEGIN IMMEDIATE ... COMMIT/ROLLBACK (one writer at a time across processes)."""
        store = self

        class _T:
            def __enter__(self):
                store.db.execute('BEGIN IMMEDIATE')

            def __exit__(self, exc_type, *_):
                store.db.execute('ROLLBACK' if exc_type else 'COMMIT')
                return False
        return _T()


# ---------------------------------------------------------------- missions
MISSION_TRANSITIONS: dict[str, set[str]] = {
    'proposed':    {'assigned', 'cancelled'},
    'assigned':    {'in_progress', 'failed', 'cancelled'},
    'in_progress': {'verifying', 'failed', 'cancelled'},
    'verifying':   {'done', 'failed', 'in_progress'},   # verification may reveal more work
    'done': set(), 'failed': set(), 'cancelled': set(),  # terminal: retry = new mission with parent_id
}
MISSION_OPEN = ('proposed', 'assigned', 'in_progress', 'verifying')


class MissionStore(_Base):
    """The coordinator's decisions: objective, pilot, who decided, why, and the verified outcome."""

    def create(self, objective: str, *, decided_by: str, pilot: str | None = None,
               rationale: str = '', constraints: dict | None = None, plan: dict | None = None,
               parent_id: str | None = None, mission_id: str | None = None) -> str:
        assert decided_by in ('llm', 'rule', 'human-config'), decided_by
        mid = mission_id or _new_id('M', self.clock)
        now = self.clock()
        self.db.execute(
            'INSERT INTO missions(mission_id,parent_id,objective,pilot,status,decided_by,rationale,'
            'constraints_json,plan_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (mid, parent_id, objective, pilot, 'proposed', decided_by, rationale,
             _dumps(constraints), _dumps(plan), now, now))
        self._log('mission.created', {'mission_id': mid, 'objective': objective, 'pilot': pilot,
                                      'decided_by': decided_by, 'rationale': rationale[:300]})
        return mid

    def get(self, mission_id: str) -> dict | None:
        return _row(self.db.execute('SELECT * FROM missions WHERE mission_id=?', (mission_id,)).fetchone())

    def transition(self, mission_id: str, new_status: str, *, result: dict | None = None,
                   note: str = '') -> dict:
        with self._tx():
            row = self.db.execute('SELECT status FROM missions WHERE mission_id=?', (mission_id,)).fetchone()
            if row is None:
                raise StoreError(f'unknown mission {mission_id}')
            old = row['status']
            if new_status not in MISSION_TRANSITIONS[old]:
                raise IllegalTransition(f'mission {mission_id}: {old} -> {new_status} not allowed')
            self.db.execute('UPDATE missions SET status=?, result_json=COALESCE(?, result_json), updated_at=? '
                            'WHERE mission_id=?',
                            (new_status, _dumps(result) if result is not None else None, self.clock(), mission_id))
        self._log('mission.status', {'mission_id': mission_id, 'from': old, 'to': new_status, 'note': note})
        return self.get(mission_id)

    def open(self, pilot: str | None = None) -> list[dict]:
        q = f"SELECT * FROM missions WHERE status IN {MISSION_OPEN}"
        args: tuple = ()
        if pilot:
            q += ' AND pilot=?'
            args = (pilot,)
        return [_row(r) for r in self.db.execute(q + ' ORDER BY created_at', args)]

    def recent(self, limit: int = 20) -> list[dict]:
        return [_row(r) for r in self.db.execute('SELECT * FROM missions ORDER BY created_at DESC LIMIT ?', (limit,))]


# ---------------------------------------------------------------- A2A tasks
TASK_TERMINAL = ('completed', 'failed', 'cancelled')
TASK_UNFINISHED = ('created', 'submitted', 'working', 'unknown')


class TaskStore(_Base):
    """Every task the coordinator delegates over A2A, with its result.

    Pass a deterministic `task_id` (e.g. f'{mission_id}:sell:1') to make creation idempotent:
    a coordinator that crashes and re-plans the same step gets the existing task back
    instead of creating (and later executing) a duplicate.
    """

    def create(self, mission_id: str, *, assignee: str, skill: str, payload: dict,
               pilot: str | None = None, task_id: str | None = None) -> tuple[str, bool]:
        """Returns (task_id, created). created=False means it already existed."""
        tid = task_id or _new_id('T', self.clock)
        now = self.clock()
        cur = self.db.execute(
            'INSERT OR IGNORE INTO a2a_tasks(task_id,mission_id,assignee,skill,pilot,payload_json,status,'
            'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (tid, mission_id, assignee, skill, pilot, _dumps(payload), 'created', now, now))
        created = cur.rowcount == 1
        if created:
            self._log('task.created', {'task_id': tid, 'mission_id': mission_id, 'assignee': assignee,
                                       'skill': skill, 'pilot': pilot})
        return tid, created

    def get(self, task_id: str) -> dict | None:
        return _row(self.db.execute('SELECT * FROM a2a_tasks WHERE task_id=?', (task_id,)).fetchone())

    def mark(self, task_id: str, status: str, *, a2a_task_id: str | None = None,
             result: dict | None = None, error: str | None = None) -> dict:
        assert status in TASK_TERMINAL + TASK_UNFINISHED, status
        with self._tx():
            row = self.db.execute('SELECT status FROM a2a_tasks WHERE task_id=?', (task_id,)).fetchone()
            if row is None:
                raise StoreError(f'unknown task {task_id}')
            old = row['status']
            if old in TASK_TERMINAL and status != old:
                raise IllegalTransition(f'task {task_id} is already {old}')
            self.db.execute(
                'UPDATE a2a_tasks SET status=?, a2a_task_id=COALESCE(?, a2a_task_id), '
                'result_json=COALESCE(?, result_json), error=COALESCE(?, error), '
                'attempts=attempts + ?, updated_at=? WHERE task_id=?',
                (status, a2a_task_id, _dumps(result) if result is not None else None, error,
                 1 if status == 'submitted' else 0, self.clock(), task_id))
        self._log('task.status', {'task_id': task_id, 'from': old, 'to': status,
                                  'a2a_task_id': a2a_task_id, 'error': (error or '')[:200]})
        return self.get(task_id)

    def unfinished(self, assignee: str | None = None) -> list[dict]:
        """Tasks to reconcile after a restart."""
        q = f'SELECT * FROM a2a_tasks WHERE status IN {TASK_UNFINISHED}'
        args: tuple = ()
        if assignee:
            q += ' AND assignee=?'
            args = (assignee,)
        return [_row(r) for r in self.db.execute(q + ' ORDER BY created_at', args)]

    def for_mission(self, mission_id: str) -> list[dict]:
        return [_row(r) for r in self.db.execute(
            'SELECT * FROM a2a_tasks WHERE mission_id=? ORDER BY created_at', (mission_id,))]


# ---------------------------------------------------------------- pilot leases
class LeaseStore(_Base):
    """Expiring lock: one agent steers one pilot at a time.

    A worker acquires the lease before acting and renews it while working. If the worker
    crashes, the lease simply expires and another worker (or the restarted one) can take it.
    """

    def acquire(self, pilot: str, holder: str, ttl: float, task_id: str | None = None) -> bool:
        now = self.clock()
        with self._tx():
            row = self.db.execute('SELECT holder, expires_at FROM pilot_leases WHERE pilot=?', (pilot,)).fetchone()
            if row and row['holder'] != holder and row['expires_at'] > now:
                return False
            self.db.execute(
                'INSERT INTO pilot_leases(pilot,holder,task_id,acquired_at,expires_at) VALUES(?,?,?,?,?) '
                'ON CONFLICT(pilot) DO UPDATE SET holder=excluded.holder, task_id=excluded.task_id, '
                'acquired_at=excluded.acquired_at, expires_at=excluded.expires_at',
                (pilot, holder, task_id, now, now + ttl))
        stolen = bool(row and row['holder'] != holder)
        self._log('lease.acquired', {'pilot': pilot, 'holder': holder, 'task_id': task_id,
                                     'took_over_expired_from': row['holder'] if stolen else None})
        return True

    def renew(self, pilot: str, holder: str, ttl: float) -> bool:
        cur = self.db.execute('UPDATE pilot_leases SET expires_at=? WHERE pilot=? AND holder=?',
                              (self.clock() + ttl, pilot, holder))
        return cur.rowcount == 1

    def release(self, pilot: str, holder: str) -> bool:
        cur = self.db.execute('DELETE FROM pilot_leases WHERE pilot=? AND holder=?', (pilot, holder))
        if cur.rowcount:
            self._log('lease.released', {'pilot': pilot, 'holder': holder})
        return cur.rowcount == 1

    def holder(self, pilot: str) -> str | None:
        row = self.db.execute('SELECT holder FROM pilot_leases WHERE pilot=? AND expires_at>?',
                              (pilot, self.clock())).fetchone()
        return row['holder'] if row else None


# ---------------------------------------------------------------- observations
class ObservationStore(_Base):
    """Timestamped game snapshots. Planning must use fresh ones, never a stale plan."""

    def record(self, pilot: str, kind: str, data: dict, source: str) -> int:
        cur = self.db.execute('INSERT INTO observations(pilot,kind,data_json,source,observed_at) VALUES(?,?,?,?,?)',
                              (pilot, kind, _dumps(data), source, self.clock()))
        return int(cur.lastrowid)

    def latest(self, pilot: str, kind: str) -> dict | None:
        """Most recent observation with its age in seconds (may be stale)."""
        row = _row(self.db.execute('SELECT * FROM observations WHERE pilot=? AND kind=? '
                                   'ORDER BY observed_at DESC, id DESC LIMIT 1', (pilot, kind)).fetchone())
        if row:
            row['age'] = self.clock() - row['observed_at']
        return row

    def fresh(self, pilot: str, kind: str, max_age: float) -> dict | None:
        """Data of the latest observation if younger than max_age seconds, else None (re-observe!)."""
        row = self.latest(pilot, kind)
        return row['data'] if row and row['age'] <= max_age else None

    def prune(self, keep_seconds: float) -> int:
        cur = self.db.execute('DELETE FROM observations WHERE observed_at < ?', (self.clock() - keep_seconds,))
        return cur.rowcount


# ---------------------------------------------------------------- facade
class Store:
    """One object per process giving access to every table on a single connection."""

    def __init__(self, path: str | Path = DEFAULT_DB, *, agent: str = 'system',
                 clock: Callable[[], float] = time.time, log_path: str | None = None):
        self.db = connect(path)
        self.agent = agent

        def log(event: str, data: dict):
            from scripts.evidence import record  # local import: keeps store usable without scripts/
            record(event, agent=agent, task_id=data.get('task_id'), data=data,
                   **({'path': log_path} if log_path else {}))

        self.actions = ActionLedger(self.db)
        self.missions = MissionStore(self.db, clock, log)
        self.tasks = TaskStore(self.db, clock, log)
        self.leases = LeaseStore(self.db, clock, log)
        self.observations = ObservationStore(self.db, clock, log)

    def close(self):
        self.db.close()
