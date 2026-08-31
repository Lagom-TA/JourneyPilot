"""tool_execution_audits 的同 id 重复写自证一致（评审条目 A12）。

同一个 ``infrastructure`` 包里两张台账原来处置相反：``cost_ledger_store`` 会拿一个
身份元组比对、不一致就抛（``cost_ledger_store.py:_ledger_identity``），而
``tool_audit_store`` 命中 ``audit_id`` 就直接把旧行返回，新 envelope 里的内容零比对
地丢掉。这个文件把两边的语义拉平，并且**两个实现跑同一组断言**：语义分叉只会在
「测试大多跑内存那个」的时候变成生产事故。

PostgreSQL 那半用一张假会话表跑，而不是标记成 ``postgres`` 后在没库的机器上跳过：
要验的东西是 ``record_envelope`` 里那个分支的判定，不是 SQL 方言，假会话跑的是同一
段真代码，而 skip 掉的那条什么都不验。
"""

from __future__ import annotations

import contextlib
from typing import Any, Dict, Optional

import pytest

from travel_agent.entities.tool_gateway import ToolManifest
from travel_agent.infrastructure import tool_audit_store as store_module
from travel_agent.infrastructure.tool_audit_store import (
    InMemoryToolAuditStore,
    ToolAuditConflict,
    ToolAuditStore,
    _audit_identity,
    build_audit_record_from_envelope,
)

_MANIFEST = ToolManifest(tool_name="amap_route", source="tool", server_name="amap")


def _envelope(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "audit_id": "tool_fixed_id",
        "tool_name": "amap_route",
        "server_name": "amap",
        "source_type": "tool",
        "status": "ok",
        "args_digest": "sha256:aaaa",
        "result_summary": "3 routes",
        "metadata": {},
    }
    base.update(overrides)
    return base


# ── 假 PostgreSQL 会话 ────────────────────────────────────────────────────────
# `ToolAuditStore.record_envelope` 只用到 execute / mappings().first()，所以一个
# 按 audit_id 索引的 dict 就够了：SELECT 命中就把那行喂回去，INSERT 把参数原样存下。


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> Optional[dict]:
        return self._rows[0] if self._rows else None

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    def __init__(self, table: Dict[str, dict]) -> None:
        self.table = table

    async def execute(self, statement: Any, params: Optional[dict] = None) -> _FakeResult:
        params = params or {}
        if str(statement).lstrip().upper().startswith("SELECT"):
            row = self.table.get(params.get("audit_id"))
            return _FakeResult([row] if row is not None else [])
        # INSERT：落库后回读走的是同一批列名，created_at 由数据库的 NOW() 给，
        # 这里留空让 `_record_from_row` 走它自己的兜底。
        self.table[params["audit_id"]] = {**params, "created_at": None}
        return _FakeResult([])


class _FakePostgresToolAuditStore:
    """真的 `ToolAuditStore`，只把它的会话换成上面那张表。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.table: Dict[str, dict] = {}
        self._store = ToolAuditStore()
        session = _FakeSession(self.table)

        @contextlib.asynccontextmanager
        async def _fake_get_db_session():
            yield session

        monkeypatch.setattr(store_module, "get_db_session", _fake_get_db_session)

    async def record_envelope(self, envelope: Dict[str, Any], **kwargs: Any):
        return await self._store.record_envelope(envelope, **kwargs)


@pytest.fixture(params=["in_memory", "postgres"])
def audit_store(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.param == "in_memory":
        return InMemoryToolAuditStore()
    return _FakePostgresToolAuditStore(monkeypatch)


# ── 五条断言，两个实现各跑一遍 ────────────────────────────────────────────────


async def test_same_content_replay_returns_stored_row(audit_store) -> None:
    """1. 同 id 同内容重写：返回旧行，不抛。"""

    first = await audit_store.record_envelope(_envelope(), manifest=_MANIFEST)
    second = await audit_store.record_envelope(_envelope(), manifest=_MANIFEST)

    assert first.audit_id == second.audit_id == "tool_fixed_id"
    assert _audit_identity(first) == _audit_identity(second)


async def test_different_result_digest_conflicts(audit_store) -> None:
    """2. 同 id 不同 result_digest：抛冲突，绝不静默丢弃新内容。"""

    await audit_store.record_envelope(_envelope(), manifest=_MANIFEST)
    with pytest.raises(ToolAuditConflict):
        await audit_store.record_envelope(
            _envelope(result_summary="0 routes"), manifest=_MANIFEST
        )


async def test_different_status_conflicts(audit_store) -> None:
    """3. 同 id 不同 status：抛冲突。"""

    await audit_store.record_envelope(_envelope(), manifest=_MANIFEST)
    with pytest.raises(ToolAuditConflict):
        await audit_store.record_envelope(
            _envelope(status="failed"), manifest=_MANIFEST
        )


async def test_orphaned_run_id_does_not_conflict(audit_store) -> None:
    """4. 旧行 run_id 为 None、新 envelope 带 run_id：**不抛**。

    ``tool_execution_audits.run_id`` 是 ``ON DELETE SET NULL``
    （``migrations/versions/0001_baseline_current_schema.py:593``），所以父 run 被删
    之后旧行的 run_id 就是 NULL，而重新到达的 envelope 还带着它自己的 run_id。这是
    这张表的正常状态，不是内容冲突 —— 把 run_id 放进身份元组会在这里抛假冲突。
    """

    stored = await audit_store.record_envelope(
        _envelope(), manifest=_MANIFEST, run_id=None
    )
    assert stored.run_id is None

    replayed = await audit_store.record_envelope(
        _envelope(), manifest=_MANIFEST, run_id="run_readded"
    )
    assert replayed.run_id is None  # 旧行仍然是权威，重复写不改已落库的行


async def test_latency_only_difference_does_not_conflict(audit_store) -> None:
    """5. 同 id 只有时延 / 重试类字段不同：不抛。

    这些字段在重放时天然会变；比进去只会制造假报警。
    """

    await audit_store.record_envelope(
        _envelope(metadata={"retry_attempt": 0, "retry_count": 0}),
        manifest=_MANIFEST,
    )
    replayed = await audit_store.record_envelope(
        _envelope(metadata={"retry_attempt": 2, "retry_count": 2}),
        manifest=_MANIFEST,
    )
    assert replayed.audit_id == "tool_fixed_id"


# ── 身份元组本身的钉子 ────────────────────────────────────────────────────────


def test_identity_tuple_excludes_run_id_and_created_at() -> None:
    """元组对 run_id / created_at 免疫：这两个字段变化不得改变身份。"""

    base = build_audit_record_from_envelope(
        _envelope(), manifest=_MANIFEST, run_id=None
    )
    moved = build_audit_record_from_envelope(
        _envelope(), manifest=_MANIFEST, run_id="run_readded"
    )
    moved.created_at = "2099-01-01T00:00:00+00:00"

    assert _audit_identity(base) == _audit_identity(moved)
