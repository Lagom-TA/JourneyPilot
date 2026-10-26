"""PostgreSQL 相关 fixture 只使用一次性的 jp_test_<random> 数据库。"""

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
    from travel_agent.config.loader import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def base_target(settings):
    """配置中的凭证只用于创建和删除一次性数据库。"""

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
            # 要求 PostgreSQL 时必须失败，不能静默跳过。
            pytest.fail(f"PostgreSQL 不可达（{base_target.describe()}）：{exc}", pytrace=False)
        print(f"\n[tests] PostgreSQL 不可达（{base_target.describe()}）：{exc}")
        return False


@pytest.fixture
def temp_database(base_target, postgres_available) -> Iterator[object]:
    """随机库名隔离并发测试与中断运行留下的残留。"""

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
                # 先关闭残留连接，避免 DROP DATABASE 失败。
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def unmanaged_database(temp_database) -> object:
    """删除 baseline 版本标记，以验证未纳管数据库的处理路径。"""

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
    """把环境变量、设置与引擎一起指向一次性数据库。"""

    from travel_agent.config.loader import reload_settings
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
        # 在数据库 fixture 删除数据库之前先释放引擎。
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
    """Alembic 每条迁移打两行 INFO，会占满测试输出。"""

    import logging

    logger = logging.getLogger("alembic")
    previous = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(previous)


def pytest_report_header(config: pytest.Config) -> str:
    host = os.getenv("JOURNEYPILOT_DATABASE__HOST", "(config.yaml)")
    return f"[tests] JOURNEYPILOT_DATABASE__HOST={host}"
