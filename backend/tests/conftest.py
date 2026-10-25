"""PostgreSQL fixtures use disposable jp_test_<random> databases only."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Iterator

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "postgres: requires a reachable PostgreSQL instance (skipped when absent)"
    )


@pytest.fixture(scope="session")
def settings():
    from travel_agent.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def base_target(settings):
    """Use configured credentials only to create and drop disposable databases."""

    from travel_agent.storage.maintenance.connection import DatabaseTarget

    return DatabaseTarget.from_settings(settings)


@pytest.fixture(scope="session")
def postgres_available(base_target) -> bool:
    from travel_agent.storage.maintenance.connection import connect_maintenance

    try:
        with connect_maintenance(base_target) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001 — 任何连接失败都同样是「不可用」
        if os.getenv("JP_TESTS_REQUIRE_POSTGRES") == "1":
            # Required PostgreSQL must fail rather than silently skip.
            pytest.fail(f"PostgreSQL 不可达（{base_target.describe()}）：{exc}", pytrace=False)
        print(f"\n[tests] PostgreSQL 不可达（{base_target.describe()}）：{exc}")
        return False


@pytest.fixture
def temp_database(base_target, postgres_available) -> Iterator[object]:
    """Random names isolate concurrent tests and leftovers from interrupted runs."""

    if not postgres_available:
        pytest.skip("需要可达的 PostgreSQL")

    from travel_agent.storage.maintenance.connection import connect_maintenance

    name = f"jp_test_{uuid.uuid4().hex[:12]}"
    with connect_maintenance(base_target) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{name}"')
    try:
        yield base_target.with_database(name)
    finally:
        with connect_maintenance(base_target) as conn:
            with conn.cursor() as cur:
                # Close residual connections so DROP DATABASE cannot leave an orphan.
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def unmanaged_database(temp_database) -> object:
    """Remove the baseline version marker to exercise unmanaged-database handling."""

    from travel_agent.storage.maintenance import migrate
    from travel_agent.storage.maintenance.connection import connect
    from travel_agent.storage.maintenance.schema_contract import BASELINE_REVISION

    migrate.upgrade(temp_database, BASELINE_REVISION)
    with connect(temp_database) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE alembic_version")
    return temp_database


@pytest.fixture
async def migrated_async_database(temp_database, monkeypatch):
    """Point environment, settings and engine at the disposable database together."""

    from travel_agent.config import reload_settings
    from travel_agent.storage.maintenance import migrate
    from travel_agent.storage.database import close_db

    migrate.upgrade(temp_database)
    monkeypatch.setenv("JOURNEYPILOT_DATABASE__HOST", temp_database.host)
    monkeypatch.setenv("JOURNEYPILOT_DATABASE__PORT", str(temp_database.port))
    monkeypatch.setenv("JOURNEYPILOT_DATABASE__NAME", temp_database.database)
    monkeypatch.setenv("JOURNEYPILOT_DATABASE__USER", temp_database.user)
    monkeypatch.setenv("JOURNEYPILOT_DATABASE__PASSWORD", temp_database.password)
    await close_db()
    reload_settings()
    try:
        yield temp_database
    finally:
        # Dispose the engine before the database fixture drops its database.
        await close_db()
        monkeypatch.undo()
        reload_settings()


@pytest.fixture
def scratch_dir(tmp_path) -> Path:
    """备份类测试的输出目录。用 pytest 的 tmp_path，绝不写进仓库。"""

    path = tmp_path / "backups"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def _quiet_alembic_logging():
    """Alembic 每条迁移打两行 INFO。测试输出里它们只是噪音。"""

    import logging

    logger = logging.getLogger("alembic")
    previous = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(previous)


def pytest_report_header(config: pytest.Config) -> str:
    host = os.getenv("JOURNEYPILOT_DATABASE__HOST", "(config.yaml)")
    return f"[tests] JOURNEYPILOT_DATABASE__HOST={host}"
