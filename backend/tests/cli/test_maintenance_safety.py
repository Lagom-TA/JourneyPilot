"""维护命令在失败和并发写入下保持备份与数据库可恢复。"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from travel_agent.storage.maintenance import backup, restore
from travel_agent.storage.maintenance.connection import DatabaseTarget


_TARGET = DatabaseTarget(host="localhost", port=5432, user="u", password="p", database="travel")


class _Connection:
    def __init__(self):
        self.active = False
        self.statements = []

    @contextmanager
    def transaction(self):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, statement):
        self.statements.append(statement)

    def fetchone(self):
        return ("snapshot-1",)


def _prepare_backup(monkeypatch, conn, *, bad_dump=False):
    census = SimpleNamespace(
        reachable=True, postgres_major=18, postgres_version="18", alembic_revision="0001",
        row_counts={"user_profiles": 2}, total_business_rows=2, optional_capabilities={},
    )

    def read_census(actual_conn, *, strict=False):
        assert actual_conn is conn and conn.active and strict
        return census

    class Runner:
        strategy = "local"
        client_major = 18
        container = ""

        def describe(self):
            return "test"

        def run(self, tool, args, **kwargs):
            if tool == "pg_dump":
                assert conn.active
                assert args[args.index("--snapshot") + 1] == "snapshot-1"
                kwargs["stdout_path"].write_bytes(b"database dump")
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            return SimpleNamespace(returncode=int(bad_dump), stdout=b"TOC", stderr=b"invalid")

    monkeypatch.setattr(backup, "take_census", read_census)
    monkeypatch.setattr(backup, "resolve_runner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr(backup, "fingerprint_sync", lambda *args, **kwargs: {"tables": {}})
    monkeypatch.setattr(backup, "fingerprint_digest", lambda *_: "test-digest")
    monkeypatch.setattr(backup, "_database_size_bytes", lambda *args: 16)
    monkeypatch.setattr(backup, "_write_redacted_config", lambda *_: None)


def test_backup_shares_one_snapshot_with_dump(monkeypatch, tmp_path):
    conn = _Connection()
    _prepare_backup(monkeypatch, conn)
    result = backup.create_backup(conn, _TARGET, embedding_dimensions=1024, output_root=tmp_path)
    assert conn.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SELECT pg_export_snapshot()",
    ]
    assert not conn.active
    assert result.manifest["row_counts"] == {"user_profiles": 2}
    assert backup.verify_backup(result.directory) == []


def test_failed_dump_verification_removes_only_its_incomplete_backup(monkeypatch, tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    conn = _Connection()
    _prepare_backup(monkeypatch, conn, bad_dump=True)
    with pytest.raises(backup.BackupVerificationError):
        backup.create_backup(conn, _TARGET, embedding_dimensions=1024, output_root=tmp_path)
    assert list(tmp_path.iterdir()) == [existing]
    assert not conn.active


def test_backup_verification_requires_checked_dump_and_fingerprint(tmp_path):
    dump = tmp_path / backup.DUMP_FILENAME
    dump.write_bytes(b"dump")
    manifest = {"files": [], "row_counts": {}, "migration_revision": None,
                "database": {"postgres_major": 18}}
    (tmp_path / backup.MANIFEST_FILENAME).write_text(json.dumps(manifest))
    errors = backup.verify_backup(tmp_path)
    assert any(backup.DUMP_FILENAME in error for error in errors)
    assert any(backup.FINGERPRINT_FILENAME in error for error in errors)

    manifest["files"] = [{"name": "../outside", "bytes": 4,
                          "sha256": hashlib.sha256(b"dump").hexdigest()}]
    (tmp_path / backup.MANIFEST_FILENAME).write_text(json.dumps(manifest))
    assert any("条目无效" in error for error in backup.verify_backup(tmp_path))


def test_restore_switch_rolls_original_name_back_after_second_rename_fails():
    class Cursor:
        def __init__(self):
            self.names = {"current", "staging"}
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("switch failed")
            parts = statement.split('"')
            self.names.remove(parts[1])
            self.names.add(parts[3])

    cursor = Cursor()
    with pytest.raises(restore.RestoreError, match="原库 current 已恢复"):
        restore._switch_database(SimpleNamespace(cursor=lambda: cursor), "current", "staging", "retained")
    assert cursor.names == {"current", "staging"}
