"""baseline 迁移的硬约束：空库能迁出完整结构、未版本化的库被拒绝、结构对不上就拒绝。

迁移是唯一能建出业务结构的东西（API 进程不建表），所以这几条约束必须成立。
"""

from __future__ import annotations

import pytest

from travel_agent.storage.maintenance import migrate
from travel_agent.storage.maintenance.connection import connect
from travel_agent.storage.maintenance.fingerprint import diff_fingerprints, fingerprint_sync
from travel_agent.storage.maintenance.schema_contract import BASELINE_REVISION, MANAGED_TABLES

pytestmark = pytest.mark.postgres


def _fingerprint(target, dimensions: int) -> dict:
    with connect(target) as conn:
        return fingerprint_sync(conn, embedding_dimensions=dimensions)


def test_empty_database_upgrades_to_head(temp_database, settings):
    """空库 → `upgrade head`：结构完整、版本号落到 head、指纹与存档一致。"""

    migrate.upgrade(temp_database)

    with connect(temp_database) as conn:
        from travel_agent.storage.maintenance.census import take_census

        census = take_census(conn)

    line = migrate.revision_line()
    head = line[-1]
    assert census.alembic_revision == head, "迁移后版本号必须是 head"
    assert not census.missing_managed_tables, (
        f"upgrade head 之后仍缺表：{census.missing_managed_tables}"
    )
    assert not census.missing_required_extensions, (
        f"缺核心扩展：{census.missing_required_extensions}"
    )

    actual = _fingerprint(temp_database, settings.embedding.dimensions)
    archived = migrate.expected_fingerprint_for(head, line=line)
    assert archived is not None, (
        f"缺 head（{head}）的指纹存档。"
        f"用 `journeypilot db write-fingerprint --revision {head}` 生成。"
    )
    problems = diff_fingerprints(archived, actual)
    assert not problems, "迁移建出来的结构与存档的 head 指纹不一致：\n" + "\n".join(problems)


def test_unmanaged_database_is_refused_not_adopted(unmanaged_database, settings):
    """有核心表、无 alembic_version → 拒绝。

    未版本化的库无法证明结构与当前代码匹配；这里不做指纹比对后的 stamp，一律
    要求重建数据库或从匹配的备份恢复。
    """

    with connect(unmanaged_database) as conn:
        plan = migrate.plan(
            conn, unmanaged_database, embedding_dimensions=settings.embedding.dimensions
        )

    assert plan.decision is migrate.Decision.REFUSE_UNKNOWN_SCHEMA, (
        f"未版本化的库必须被拒绝，实际是 {plan.decision.value}：{plan.problems}"
    )
    assert plan.refused
    assert plan.current_revision is None
    # 拒绝必须给出下一步，而且不能是「再跑一次 migrate」—— migrate 不会纳管它。
    assert plan.next_action
    assert "重建" in plan.next_action or "恢复" in plan.next_action, plan.next_action


def test_versioned_database_with_drift_is_refused(temp_database, settings):
    """版本号已在 head，结构却多了一列 → 拒绝，并指出差在哪。"""

    migrate.upgrade(temp_database)
    with connect(temp_database) as conn:
        with conn.cursor() as cur:
            # 一个合同外的列，模拟「版本号说 head，结构却不是 head」。
            cur.execute("ALTER TABLE trip_runs ADD COLUMN mystery_column TEXT")
        plan = migrate.plan(
            conn, temp_database, embedding_dimensions=settings.embedding.dimensions
        )

    assert plan.decision is migrate.Decision.REFUSE_UNKNOWN_SCHEMA
    assert plan.refused
    assert any("mystery_column" in problem for problem in plan.problems), (
        f"拒绝的理由必须指出差在哪，实际：{plan.problems}"
    )
    # 拒绝时必须给出下一步，而不只是「不行」。
    assert plan.next_action


def test_baseline_downgrade_removes_managed_tables(temp_database, settings):
    """唯一迁移的 up/down 对称：downgrade 到 base 之后一张受管表都不剩。"""

    migrate.upgrade(temp_database, BASELINE_REVISION)
    with connect(temp_database) as conn:
        from travel_agent.storage.maintenance.census import take_census

        assert take_census(conn).alembic_revision == BASELINE_REVISION

    migrate.downgrade(temp_database, "base")

    with connect(temp_database) as conn:
        from travel_agent.storage.maintenance.census import take_census

        census = take_census(conn)
    assert census.present_managed_tables == (), (
        f"downgrade 之后仍有受管表残留：{census.present_managed_tables}"
    )
    assert census.alembic_revision is None
    assert len(MANAGED_TABLES) == len(census.missing_managed_tables)
