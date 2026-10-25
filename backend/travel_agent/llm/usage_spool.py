"""Local write-ahead outbox for telemetry, without prompts or credentials.

One SQLite file per persistent application volume. Multiple API workers may
share it; concurrent drains may duplicate a batch, so PostgreSQL call_id
idempotency is mandatory. Only confirmed commits are acknowledged.
"""
import json
import os
from pathlib import Path
import sqlite3
import socket
import time


def process_identity(pid):
    try:
        # PID reuse must not keep an abandoned request alive indefinitely.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return f"{socket.gethostname()}:{fields[19]}"
    except (OSError, IndexError):
        return None


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
        deadline = time.monotonic() + 10
        while True:
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                # Concurrent WAL initialization can bypass SQLite's busy timeout.
                if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                    self.db.close()
                    raise
                time.sleep(0.01)
        self.db.execute("PRAGMA synchronous=FULL")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("CREATE TABLE IF NOT EXISTS usage_outbox (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, phase TEXT NOT NULL, pid INTEGER NOT NULL, payload TEXT NOT NULL, owner_token TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS usage_capture_failures (run_id TEXT PRIMARY KEY, failures INTEGER NOT NULL)")
        self.recover_abandoned()

    @staticmethod
    def encode(payload):
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def recover_abandoned(self, alive=pid_alive):
        with self.db:
            rows = self.db.execute("SELECT id,pid,payload,owner_token FROM usage_outbox WHERE phase='started'").fetchall()
            for call_id, pid, data, owner_token in rows:
                if alive(pid) and process_identity(pid) == owner_token:
                    continue
                payload = json.loads(data)
                payload.update(status="interrupted", usage_complete=False, usage_source="missing",
                               error_type="ProcessInterruptedBeforeUsageCommit")
                self.db.execute("UPDATE usage_outbox SET phase='complete',payload=? WHERE id=? AND phase='started'",
                                (self.encode(payload), call_id))

    def put(self, payload, *, phase):
        encoded = self.encode(payload)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT phase,payload FROM usage_outbox WHERE id=?", (payload["id"],)).fetchone()
            if row and row[0] == "complete" and row[1] != encoded:
                raise UsageSpoolConflict("call_id has conflicting usage payload")
            self.db.execute("INSERT INTO usage_outbox (id,run_id,phase,pid,payload,owner_token) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET phase=excluded.phase,payload=excluded.payload",
                            (payload["id"], payload["run_id"], phase, os.getpid(), encoded, process_identity(os.getpid())))

    def pending(self, *, run_id=None, limit=500, exclude_ids=(), include_ids=None):
        sql = "SELECT payload FROM usage_outbox WHERE phase='complete'"
        params = []
        if run_id:
            sql += " AND run_id=?"
            params.append(run_id)
        if exclude_ids:
            sql += " AND id NOT IN (" + ",".join("?" for _ in exclude_ids) + ")"
            params.extend(exclude_ids)
        if include_ids is not None:
            if not include_ids:
                return []
            sql += " AND id IN (" + ",".join("?" for _ in include_ids) + ")"
            params.extend(include_ids)
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
