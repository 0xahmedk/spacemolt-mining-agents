"""Durable state in SQLite, shared by every agent process.

Phase 2 provides the *action ledger* used by the MCP gateway for idempotency.
Phase 3 adds missions, A2A tasks, observations and pilot leases to this file.

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
from dataclasses import dataclass
from pathlib import Path

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

