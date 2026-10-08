"""Local write-ahead outbox for telemetry, without prompts or credentials.

One SQLite file per persistent application volume. Multiple API workers may
share it; concurrent drains may duplicate a batch, so PostgreSQL call_id
idempotency is mandatory. Only confirmed commits are acknowledged.
"""
import json
import os
from pathlib import Path
import sqlite3


class UsageSpoolConflict(ValueError):
    pass


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class UsageSpool:
    def __init__(self, path):
        if str(path) != ":memory:":
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS usage_outbox (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, phase TEXT NOT NULL, pid INTEGER NOT NULL, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS usage_capture_failures (run_id TEXT PRIMARY KEY, failures INTEGER NOT NULL)")
        self.db.commit()
        self.recover_abandoned()

    @staticmethod
    def encode(payload):
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def recover_abandoned(self, alive=pid_alive):
        with self.db:
            rows = self.db.execute("SELECT id,pid,payload FROM usage_outbox WHERE phase='started'").fetchall()
            for call_id, pid, data in rows:
                if alive(pid):
                    continue
                payload = json.loads(data)
                payload.update(status="interrupted", usage_complete=False, usage_source="missing",
                               error_type="ProcessInterruptedBeforeUsageCommit")
                self.db.execute("UPDATE usage_outbox SET phase='complete',payload=? WHERE id=? AND phase='started'",
                                (self.encode(payload), call_id))

    def put(self, payload, *, phase):
        encoded = self.encode(payload)
        with self.db:
            row = self.db.execute("SELECT phase,payload FROM usage_outbox WHERE id=?", (payload["id"],)).fetchone()
            if row and row[0] == "complete" and row[1] != encoded:
                raise UsageSpoolConflict("call_id has conflicting usage payload")
            self.db.execute("INSERT INTO usage_outbox VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET phase=excluded.phase,payload=excluded.payload",
                            (payload["id"], payload["run_id"], phase, os.getpid(), encoded))

    def pending(self, *, run_id=None, limit=500):
        sql = "SELECT payload FROM usage_outbox WHERE phase='complete'"
        params = []
        if run_id:
            sql += " AND run_id=?"
            params.append(run_id)
        sql += " ORDER BY rowid LIMIT ?"
        return [json.loads(row[0]) for row in self.db.execute(sql, [*params, limit])]

    def ack(self, payloads):
        with self.db:
            for payload in payloads:
                self.db.execute("DELETE FROM usage_outbox WHERE id=? AND phase='complete' AND payload=?",
                                (payload["id"], self.encode(payload)))

    def failure(self, run_id, count):
        with self.db:
            self.db.execute("INSERT INTO usage_capture_failures VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET failures=usage_capture_failures.failures+excluded.failures",
                            (run_id, count))

    def integrity(self, run_id):
        pending = self.db.execute("SELECT count(*) FROM usage_outbox WHERE run_id=?", (run_id,)).fetchone()[0]
        row = self.db.execute("SELECT failures FROM usage_capture_failures WHERE run_id=?", (run_id,)).fetchone()
        return pending, row[0] if row else 0
