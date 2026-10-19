from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ExecutionJournal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (plan_id TEXT NOT NULL, operation_id TEXT NOT NULL, source_id TEXT, target_id TEXT, action TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL, error_category TEXT, started_at TEXT, completed_at TEXT, client_token TEXT, PRIMARY KEY(plan_id, operation_id))")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(operations)")}
        if "client_token" not in columns:
            self.db.execute("ALTER TABLE operations ADD COLUMN client_token TEXT")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def prepare(self, plan_id, operation_id, source_id, target_id, action):
        existing = self.db.execute("SELECT client_token FROM operations WHERE plan_id=? AND operation_id=?", (plan_id, operation_id)).fetchone()
        token = existing[0] if existing else None
        if action == "CREATE" and not token:
            token = str(uuid.uuid4())
        self.db.execute("INSERT OR IGNORE INTO operations(plan_id,operation_id,source_id,target_id,action,state,client_token) VALUES(?,?,?,?,?, 'PENDING', ?)", (plan_id, operation_id, source_id, target_id, action, token))
        if token:
            self.db.execute("UPDATE operations SET client_token=? WHERE plan_id=? AND operation_id=? AND client_token IS NULL", (token, plan_id, operation_id))
        self.db.commit()
        return token

    def client_token(self, plan_id, operation_id):
        row = self.db.execute("SELECT client_token FROM operations WHERE plan_id=? AND operation_id=?", (plan_id, operation_id)).fetchone()
        return row[0] if row else None

    def operation(self, plan_id, source_id):
        return self.db.execute("SELECT plan_id,operation_id,source_id,target_id,action,attempts,state,error_category,client_token,started_at,completed_at FROM operations WHERE plan_id=? AND source_id=?", (plan_id, source_id)).fetchone()

    def start(self, plan_id, operation_id):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("UPDATE operations SET state='IN_PROGRESS', attempts=attempts+1, started_at=? WHERE plan_id=? AND operation_id=?", (now, plan_id, operation_id)); self.db.commit()

    def finish(self, plan_id, operation_id, state, error_category=None):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("UPDATE operations SET state=?, error_category=?, completed_at=? WHERE plan_id=? AND operation_id=?", (state, error_category, now, plan_id, operation_id)); self.db.commit()

    def unresolved(self) -> list[tuple]:
        return self.db.execute("SELECT plan_id,operation_id,source_id,target_id,action,state,error_category FROM operations WHERE state NOT IN ('SUCCEEDED','FAILED') ORDER BY plan_id,operation_id").fetchall()

    def summary(self) -> dict[str, int]:
        return {row[0]: row[1] for row in self.db.execute("SELECT state,COUNT(*) FROM operations GROUP BY state")}
