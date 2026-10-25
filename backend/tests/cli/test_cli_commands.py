from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from travel_agent.cli.arguments import build_parser
from travel_agent.cli.main import main


@pytest.fixture
def configured(monkeypatch):
    from travel_agent.config import loader
    from travel_agent.config.models import Settings

    settings = Settings()
    monkeypatch.setattr(loader, "get_settings", lambda: settings)
    return settings


def test_restore_requires_confirmation_before_storage(configured, monkeypatch, capsys):
    from travel_agent.storage.maintenance import restore

    operation = Mock(side_effect=AssertionError("restore must not run"))
    monkeypatch.setattr(restore, "restore", operation)

    assert main(["restore", "/offline/backup"]) == 1
    operation.assert_not_called()
    output = capsys.readouterr()
    assert output.out == ""
    assert "确认请加 --yes。" in output.err
    assert "当前数据库会被改名留档（不会删除）" in output.err


def test_migrate_sql_never_connects(configured, monkeypatch, capsys):
    from travel_agent.storage.maintenance import checkpoint_schema, connection, migrate

    connect = Mock(side_effect=AssertionError("offline SQL must not connect"))
    checkpoints = Mock(side_effect=AssertionError("offline SQL must not create tables"))
    sql = Mock(side_effect=lambda target: print("-- offline SQL"))
    monkeypatch.setattr(connection, "connect", connect)
    monkeypatch.setattr(checkpoint_schema, "create_checkpoint_schema", checkpoints)
    monkeypatch.setattr(migrate, "upgrade_sql", sql)

    assert main(["migrate", "--sql"]) == 0
    connect.assert_not_called()
    checkpoints.assert_not_called()
    assert sql.call_args.args[0].database == configured.database.name
    output = capsys.readouterr()
    assert output.out == "-- offline SQL\n"
    assert "离线预览" in output.err


def test_backup_prune_dry_run_delegates_without_connecting(
    configured, monkeypatch, capsys
):
    from travel_agent.storage.maintenance import backup, connection

    prune = Mock(return_value=["/offline/backup/automatic"])
    connect = Mock(side_effect=AssertionError("pruning must not connect"))
    monkeypatch.setattr(backup, "prune_automatic_backups", prune)
    monkeypatch.setattr(connection, "connect", connect)

    assert (
        main(
            [
                "backup",
                "--prune",
                "--dry-run",
                "--backup-dir",
                "/offline/backup",
                "--json",
            ]
        )
        == 0
    )
    prune.assert_called_once_with(
        Path("/offline/backup"),
        keep=configured.maintenance.keep_automatic_backups,
        dry_run=True,
    )
    connect.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {
        "pruned": ["/offline/backup/automatic"],
        "dry_run": True,
    }


@pytest.mark.parametrize("as_json", [False, True])
def test_db_status_and_doctor_have_identical_output(
    configured, monkeypatch, capsys, as_json
):
    from travel_agent.cli.doctor import cmd_doctor
    from travel_agent.storage.maintenance import connection

    monkeypatch.setattr(
        connection, "connect", Mock(side_effect=RuntimeError("offline diagnostic"))
    )
    flags = ["--json"] if as_json else []
    assert build_parser().parse_args(["db", "status"]).func is cmd_doctor
    assert main(["doctor", *flags]) == 1
    doctor_output = capsys.readouterr()
    assert main(["db", "status", *flags]) == 1
    assert capsys.readouterr() == doctor_output


def test_parser_preserves_command_defaults_and_usage_errors():
    from travel_agent.cli.migrate import cmd_migrate

    parser = build_parser()
    args = parser.parse_args(["migrate", "--dry-run"])
    assert args.func is cmd_migrate
    assert args.dry_run is True
    assert args.allow_destructive is args.skip_backup is args.sql is args.json is False
    assert args.backup_dir is None
    assert args.log_level == "warning"
    for argv in ([], ["config"], ["db"], ["db", "write-fingerprint"]):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(argv)
        assert exc.value.code == 2
