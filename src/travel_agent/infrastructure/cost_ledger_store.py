"""Cost ledger persistence（台账层 / 暴露层）.

把捕获层缓冲的每条 ``LLMCallRecord`` 落成 Postgres 台账行 ``run_llm_calls``，
写入时按价格表**快照计算** ``cost_usd``（LangSmith 语义：价格表后改不追溯重算已落库行），
再经 SSE（运行中）与 REST（历史）暴露 run 级成本汇总。

设计要点：

- **快照计算**：cost 在 ``record_calls`` 写入时算好并存库；``run_summary`` 只读库里的
  cost 聚合，绝不重算——因此改价格表不影响历史行。
- **未命中价格 → cost_usd=None**：只报 token，不编造成本（``resolve_price`` 返回 None）。
- **互斥输入桶**：``(input-read-write)×p_in + read×p_read + write×p_write + output×p_out``；
  reasoning 已含在 output_tokens 里，不另算。
- **聚合走查询期**：表小无需预聚合；``run_summary`` 拉全量行后用纯函数 ``summarize_calls``
  聚合，SQL 与 InMemory 两实现共用同一聚合逻辑，保证形状一致、可单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from ..config import ModelPricingItem, resolve_price
from ..models.usage import LLMCallRecord
from .database import get_db_session
from .row_values import iso_or_none as _iso

logger = logging.getLogger(__name__)


class CostLedgerConflict(Exception):
    """Same call id already stored with different content."""




def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# 台账行 + 成本公式
# --------------------------------------------------------------------------- #

@dataclass
class LLMCostCall:
    """一条成本台账行（run_llm_calls）：捕获层字段 + 写入时快照 cost_usd。"""

    id: str
    run_id: str
    node: Optional[str]
    agent: Optional[str]
    tier: Optional[str]
    provider: Optional[str]
    model_request: str
    model_response: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cached_input_tokens: Optional[int]
    reasoning_output_tokens: Optional[int]
    cost_usd: Optional[float]
    estimated: bool
    start_ts: Optional[str]
    end_ts: Optional[str]
    ttft_ms: Optional[float]
    latency_ms: Optional[float]
    status: str
    stream: bool
    cache_write_input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    usage_complete: bool = True
    usage_source: str = "reported"
    logical_call_id: Optional[str] = None
    attempt_number: int = 1
    request_input_tokens_estimate: Optional[int] = None
    tool_schema_tokens_estimate: Optional[int] = None
    finish_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "node": self.node,
            "agent": self.agent,
            "tier": self.tier,
            "provider": self.provider,
            "model_request": self.model_request,
            "model_response": self.model_response,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "total_tokens": self.total_tokens,
            "usage_complete": self.usage_complete,
            "usage_source": self.usage_source,
            "logical_call_id": self.logical_call_id,
            "attempt_number": self.attempt_number,
            "request_input_tokens_estimate": self.request_input_tokens_estimate,
            "tool_schema_tokens_estimate": self.tool_schema_tokens_estimate,
            "finish_reason": self.finish_reason,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "cost_usd": self.cost_usd,
            "estimated": self.estimated,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "ttft_ms": self.ttft_ms,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "stream": self.stream,
        }


def compute_cost_usd(
    price: Optional[ModelPricingItem],
    *,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cached_input_tokens: Optional[int],
    cache_write_input_tokens: Optional[int] = None,
) -> Optional[float]:
    """Price disjoint uncached/read/write input buckets and inclusive output."""
    if price is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None  # Missing usage is unknown, never a zero-token side.
    if any(value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 0
    ) for value in (input_tokens, output_tokens, cached_input_tokens, cache_write_input_tokens)):
        return None
    inp = max(0, input_tokens or 0)
    out = max(0, output_tokens or 0)
    cached = max(0, cached_input_tokens or 0)
    written = max(0, cache_write_input_tokens or 0)
    if cached + written > inp:
        return None  # Invalid bucket counts cannot support an accurate bill.
    if (cached_input_tokens is None and price.cached_input_per_1m is not None
            and price.cached_input_per_1m != price.input_per_1m):
        return None
    if (cache_write_input_tokens is None and price.cache_write_per_1m is not None
            and price.cache_write_per_1m != price.input_per_1m):
        return None  # A surcharge exists, but its billed quantity is unknown.
    p_in = price.input_per_1m / 1_000_000.0
    p_cached = (
        price.cached_input_per_1m if price.cached_input_per_1m is not None else price.input_per_1m
    ) / 1_000_000.0
    p_out = price.output_per_1m / 1_000_000.0
    p_write = (price.cache_write_per_1m if price.cache_write_per_1m is not None
               else price.input_per_1m) / 1_000_000.0
    cost = (inp - cached - written) * p_in + cached * p_cached + written * p_write + out * p_out
    return round(cost, 8)


def build_ledger_call(
    record: LLMCallRecord,
    *,
    pricing: Optional[List[ModelPricingItem]] = None,
) -> LLMCostCall:
    """捕获层 ``LLMCallRecord`` → 台账行，写入时快照计算 cost_usd。"""
    count_fields = ("input_tokens", "output_tokens", "cached_input_tokens",
                    "cache_write_input_tokens", "reasoning_output_tokens", "total_tokens")
    counts = {field: getattr(record, field) for field in count_fields}
    invalid_usage = False
    for field, value in counts.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            counts[field] = None
            invalid_usage = True
    inp, out = counts["input_tokens"], counts["output_tokens"]
    cached, written = counts["cached_input_tokens"], counts["cache_write_input_tokens"]
    reasoning = counts["reasoning_output_tokens"]
    price = resolve_price(record.model_request, record.provider, pricing=pricing)
    cost = None if invalid_usage else compute_cost_usd(
        price,
        input_tokens=inp,
        output_tokens=out,
        cached_input_tokens=cached,
        cache_write_input_tokens=written,
    )
    complete = (
        record.usage_complete and not record.estimated and not invalid_usage
        and inp is not None and out is not None
        and (cached or 0) + (written or 0) <= inp
        and (reasoning or 0) <= out
    )
    source = record.usage_source
    if not complete and source == "reported":
        source = "missing" if inp is None and out is None else "partial"
    return LLMCostCall(
        id=record.id,
        run_id=record.run_id,
        node=record.node,
        agent=record.agent,
        tier=record.tier,
        provider=record.provider,
        model_request=record.model_request,
        model_response=record.model_response,
        input_tokens=inp,
        output_tokens=out,
        cached_input_tokens=cached,
        cache_write_input_tokens=written,
        total_tokens=inp + out if inp is not None and out is not None else counts["total_tokens"],
        usage_complete=complete,
        usage_source=source,
        logical_call_id=record.logical_call_id,
        attempt_number=record.attempt_number,
        request_input_tokens_estimate=record.request_input_tokens_estimate,
        tool_schema_tokens_estimate=record.tool_schema_tokens_estimate,
        finish_reason=record.finish_reason,
        reasoning_output_tokens=reasoning,
        cost_usd=cost,
        estimated=bool(record.estimated),
        start_ts=record.start_ts,
        end_ts=record.end_ts,
        ttft_ms=record.ttft_ms,
        latency_ms=record.latency_ms,
        status=record.status or "ok",
        stream=bool(record.stream),
    )


# --------------------------------------------------------------------------- #
# run 级聚合（纯函数，SQL 与 InMemory 共用）
# --------------------------------------------------------------------------- #

def _call_total(call: LLMCostCall) -> Optional[int]:
    if call.input_tokens is not None and call.output_tokens is not None:
        return call.input_tokens + call.output_tokens
    return call.total_tokens


def _round_cost(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 8)


def _group_aggregate(calls: List[LLMCostCall], key_attr: str, label: str) -> List[Dict[str, Any]]:
    """按 node / agent 分组聚合，成本降序返回。"""
    buckets: Dict[str, Dict[str, Any]] = {}
    for call in calls:
        key = getattr(call, key_attr) or "unknown"
        bucket = buckets.setdefault(
            key,
            {
                label: key,
                "call_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "reasoning_output_tokens": 0,
                "usage_complete": True,
                "_known": set(),
                "cost_complete": True,
                "cost_usd": None,
                "latency_ms": 0.0,
            },
        )
        bucket["call_count"] += 1
        for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"):
            if getattr(call, field) is not None:
                bucket["_known"].add(field)
        if _call_total(call) is not None:
            bucket["_known"].add("total_tokens")
        bucket["input_tokens"] += call.input_tokens or 0
        bucket["output_tokens"] += call.output_tokens or 0
        bucket["total_tokens"] += _call_total(call) or 0
        bucket["cached_input_tokens"] += call.cached_input_tokens or 0
        bucket["cache_write_input_tokens"] += call.cache_write_input_tokens or 0
        bucket["reasoning_output_tokens"] += call.reasoning_output_tokens or 0
        bucket["usage_complete"] = bucket["usage_complete"] and call.usage_complete and not call.estimated
        bucket["cost_complete"] = bucket["cost_complete"] and call.cost_usd is not None and call.usage_complete and not call.estimated
        bucket["latency_ms"] += call.latency_ms or 0.0
        if call.cost_usd is not None:
            bucket["cost_usd"] = (bucket["cost_usd"] or 0.0) + call.cost_usd
    rows = list(buckets.values())
    for row in rows:
        known = row.pop("_known")
        for field in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"):
            if field not in known:
                row[field] = None
        row["cost_usd"] = _round_cost(row["cost_usd"])
        row["latency_ms"] = round(row["latency_ms"], 3)
    rows.sort(key=lambda r: ((r["cost_usd"] or 0.0), (r["total_tokens"] or 0)), reverse=True)
    return rows


def summarize_calls(run_id: str, calls: List[LLMCostCall]) -> Dict[str, Any]:
    """聚合出 run 级成本摘要：总量、按 agent 分解、瓶颈节点 top3、estimated 占比。"""
    total_input = total_output = total_cached = total_written = total_reasoning = total_tokens = 0
    complete_usage = missing_usage = 0
    request_estimate = tool_schema_estimate = 0
    total_cost = 0.0
    priced = estimated = errors = 0
    total_latency = 0.0
    starts: List[datetime] = []
    ends: List[datetime] = []

    for call in calls:
        total_input += call.input_tokens or 0
        total_output += call.output_tokens or 0
        total_tokens += _call_total(call) or 0
        total_cached += call.cached_input_tokens or 0
        total_written += call.cache_write_input_tokens or 0
        complete_usage += int(call.usage_complete and not call.estimated)
        missing_usage += int(call.usage_source == "missing")
        request_estimate += call.request_input_tokens_estimate or 0
        tool_schema_estimate += call.tool_schema_tokens_estimate or 0
        total_reasoning += call.reasoning_output_tokens or 0
        total_latency += call.latency_ms or 0.0
        if call.cost_usd is not None:
            total_cost += call.cost_usd
            priced += 1
        if call.estimated:
            estimated += 1
        if call.status in {"error", "cancelled", "interrupted"}:
            errors += 1
        st = _parse_ts(call.start_ts)
        en = _parse_ts(call.end_ts)
        if st is not None:
            starts.append(st)
        if en is not None:
            ends.append(en)

    call_count = len(calls)
    wall_ms: Optional[float] = None
    if starts and ends:
        span = (max(ends) - min(starts)).total_seconds() * 1000.0
        wall_ms = round(span, 3) if span >= 0 else None

    by_node = _group_aggregate(calls, "node", "node")
    by_agent = _group_aggregate(calls, "agent", "agent")

    bottleneck_by_cost = [
        {
            "node": row["node"],
            "cost_usd": row["cost_usd"],
            "latency_ms": row["latency_ms"],
            "call_count": row["call_count"],
        }
        for row in by_node[:3]
    ]
    bottleneck_by_latency = [
        {
            "node": row["node"],
            "latency_ms": row["latency_ms"],
            "cost_usd": row["cost_usd"],
            "call_count": row["call_count"],
        }
        for row in sorted(by_node, key=lambda r: r["latency_ms"], reverse=True)[:3]
    ]

    return {
        "run_id": run_id,
        "call_count": call_count,
        "priced_call_count": priced,
        "unpriced_call_count": call_count - priced,
        "estimated_call_count": estimated,
        "error_call_count": errors,
        "estimated_ratio": round(estimated / call_count, 4) if call_count else 0.0,
        "cost_coverage_ratio": round(priced / call_count, 4) if call_count else 0.0,
        "total_input_tokens": total_input if not calls or any(call.input_tokens is not None for call in calls) else None,
        "total_output_tokens": total_output if not calls or any(call.output_tokens is not None for call in calls) else None,
        "total_cached_input_tokens": total_cached if not calls or any(call.cached_input_tokens is not None for call in calls) else None,
        "total_reasoning_output_tokens": total_reasoning if not calls or any(call.reasoning_output_tokens is not None for call in calls) else None,
        "total_tokens": total_tokens if not calls or any(_call_total(call) is not None for call in calls) else None,
        "total_cache_write_input_tokens": total_written if not calls or any(call.cache_write_input_tokens is not None for call in calls) else None,
        "total_request_input_tokens_estimate": request_estimate if not calls or any(call.request_input_tokens_estimate is not None for call in calls) else None,
        "total_tool_schema_tokens_estimate": tool_schema_estimate if not calls or any(call.tool_schema_tokens_estimate is not None for call in calls) else None,
        "token_usage_complete": complete_usage == call_count,
        "cache_read_usage_complete": all(call.cached_input_tokens is not None for call in calls),
        "cache_write_usage_complete": all(call.cache_write_input_tokens is not None for call in calls),
        "reasoning_usage_complete": all(call.reasoning_output_tokens is not None for call in calls),
        "cache_hit_ratio": (round(total_cached / total_input, 6) if total_input and all(
            call.input_tokens is not None and call.cached_input_tokens is not None
            and not call.estimated
            and 0 <= call.cached_input_tokens + (call.cache_write_input_tokens or 0) <= call.input_tokens
            for call in calls
        ) else None),
        "cost_complete": priced == call_count and complete_usage == call_count,
        "partial_usage_call_count": call_count - complete_usage - missing_usage,
        "missing_usage_call_count": missing_usage,
        "logical_call_count": len({call.logical_call_id or call.id for call in calls}),
        # priced_call_count==0 时不编造 0 成本，报 None（只报 token）。
        "total_cost_usd": _round_cost(total_cost) if priced else None,
        "currency": "USD",
        "total_latency_ms": round(total_latency, 3),
        "wall_ms": wall_ms,
        "by_agent": by_agent,
        "by_node": by_node,
        "bottleneck_by_cost": bottleneck_by_cost,
        "bottleneck_by_latency": bottleneck_by_latency,
        # Tool Search 上下文节省量：DB 台账不持有进程内曝光计量，基值 null；由 chat 终结层
        # 用 ToolExposureLedger.summary(run_id) 回填后随 run_cost_summary 下发。
        "tool_context_saving": None,
    }


def cost_event_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """终态 run.cost_recorded 事件的 audit-safe 摘要（只计数无内容）。"""
    top = summary.get("bottleneck_by_cost") or []
    return {
        "call_count": summary.get("call_count", 0),
        "total_tokens": summary.get("total_tokens", 0),
        "total_cost_usd": summary.get("total_cost_usd"),
        "currency": summary.get("currency", "USD"),
        "estimated_ratio": summary.get("estimated_ratio", 0.0),
        "cost_coverage_ratio": summary.get("cost_coverage_ratio", 0.0),
        "bottleneck_node": top[0]["node"] if top else None,
        "bottleneck_cost_usd": top[0]["cost_usd"] if top else None,
    }


# --------------------------------------------------------------------------- #
# 台账存储：SQL + InMemory 双实现
# --------------------------------------------------------------------------- #

def _call_from_row(row: Dict[str, Any]) -> LLMCostCall:
    return LLMCostCall(
        id=row["id"],
        run_id=row["run_id"],
        node=row.get("node"),
        agent=row.get("agent"),
        tier=row.get("tier"),
        provider=row.get("provider"),
        model_request=row.get("model_request") or "",
        model_response=row.get("model_response"),
        input_tokens=row.get("input_tokens"),
        output_tokens=row.get("output_tokens"),
        cached_input_tokens=row.get("cached_input_tokens"),
        cache_write_input_tokens=row.get("cache_write_input_tokens", None),
        total_tokens=row.get("total_tokens", None),
        usage_complete=row.get("usage_complete", False),
        usage_source=row.get("usage_source", "legacy"),
        logical_call_id=row.get("logical_call_id", None),
        attempt_number=row.get("attempt_number", 1),
        request_input_tokens_estimate=row.get("request_input_tokens_estimate", None),
        tool_schema_tokens_estimate=row.get("tool_schema_tokens_estimate", None),
        finish_reason=row.get("finish_reason", None),
        reasoning_output_tokens=row.get("reasoning_output_tokens"),
        cost_usd=row.get("cost_usd"),
        estimated=bool(row.get("estimated")),
        start_ts=_iso(row.get("start_ts")),
        end_ts=_iso(row.get("end_ts")),
        ttft_ms=row.get("ttft_ms"),
        latency_ms=row.get("latency_ms"),
        status=row.get("status") or "ok",
        stream=bool(row.get("stream")),
    )


def _norm_cost(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _ledger_identity(call: LLMCostCall) -> Tuple[Any, ...]:
    """Fields that must match for same-id idempotent replay."""
    return (
        call.run_id,
        call.node,
        call.agent,
        call.provider,
        call.model_request,
        call.model_response,
        call.input_tokens,
        call.output_tokens,
        call.cached_input_tokens,
        call.cache_write_input_tokens,
        call.total_tokens,
        call.usage_complete,
        call.usage_source,
        call.logical_call_id,
        call.attempt_number,
        call.request_input_tokens_estimate,
        call.tool_schema_tokens_estimate,
        call.finish_reason,
        call.reasoning_output_tokens,
        # Prices are a commit-time snapshot. A changed price configuration
        # must not reject replay of the same captured telemetry after a crash.
        call.status,
        call.tier,
        call.estimated,
        call.stream,
    )


def _assert_ledger_idempotent(existing: LLMCostCall, incoming: LLMCostCall) -> None:
    if _ledger_identity(existing) != _ledger_identity(incoming):
        logger.error(
            "cost ledger id conflict: id=%s existing_run=%s incoming_run=%s",
            incoming.id,
            existing.run_id,
            incoming.run_id,
        )
        raise CostLedgerConflict(
            f"LLM call id {incoming.id!r} already stored with different content"
        )


class CostLedgerStore:
    """PostgreSQL-backed cost ledger repository."""

    async def record_calls(
        self,
        batch: List[LLMCallRecord],
        *,
        pricing: Optional[List[ModelPricingItem]] = None,
    ) -> List[LLMCostCall]:
        """把捕获层 drain 出的记录算好 cost 后批量落库；同 id 内容一致则幂等跳过。"""
        ledger = [build_ledger_call(rec, pricing=pricing) for rec in batch if rec and rec.run_id]
        if not ledger:
            return []
        committed = []
        async with get_db_session() as session:
            for call in ledger:
                await session.execute(
                    text(
                        """
                        INSERT INTO run_llm_calls
                            (id, run_id, node, agent, tier, provider, model_request,
                             model_response, input_tokens, output_tokens, cached_input_tokens,
                             reasoning_output_tokens, cost_usd, estimated,
                             cache_write_input_tokens, total_tokens, usage_complete, usage_source, logical_call_id, attempt_number, request_input_tokens_estimate, tool_schema_tokens_estimate, finish_reason, start_ts, end_ts,
                             ttft_ms, latency_ms, status, stream, created_at)
                        VALUES
                            (:id, :run_id, :node, :agent, :tier, :provider, :model_request,
                             :model_response, :input_tokens, :output_tokens, :cached_input_tokens,
                             :reasoning_output_tokens, :cost_usd, :estimated,
                             :cache_write_input_tokens, :total_tokens, :usage_complete, :usage_source, :logical_call_id, :attempt_number, :request_input_tokens_estimate, :tool_schema_tokens_estimate, :finish_reason,
                             CAST(:start_ts AS timestamptz), CAST(:end_ts AS timestamptz),
                             :ttft_ms, :latency_ms, :status, :stream, NOW())
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": call.id,
                        "run_id": call.run_id,
                        "node": call.node,
                        "agent": call.agent,
                        "tier": call.tier,
                        "provider": call.provider,
                        "model_request": call.model_request,
                        "model_response": call.model_response,
                        "input_tokens": call.input_tokens,
                        "output_tokens": call.output_tokens,
                        "cached_input_tokens": call.cached_input_tokens,
                        "cache_write_input_tokens": call.cache_write_input_tokens,
                        "total_tokens": call.total_tokens,
                        "usage_complete": call.usage_complete,
                        "usage_source": call.usage_source,
                        "logical_call_id": call.logical_call_id,
                        "attempt_number": call.attempt_number,
                        "request_input_tokens_estimate": call.request_input_tokens_estimate,
                        "tool_schema_tokens_estimate": call.tool_schema_tokens_estimate,
                        "finish_reason": call.finish_reason,
                        "reasoning_output_tokens": call.reasoning_output_tokens,
                        "cost_usd": call.cost_usd,
                        "estimated": call.estimated,
                        # asyncpg 对 timestamptz 参数只接受 datetime 对象；ISO 字符串
                        # 会在预编译阶段抛 DataError（CAST 也救不回来）。
                        "start_ts": _parse_ts(call.start_ts),
                        "end_ts": _parse_ts(call.end_ts),
                        "ttft_ms": call.ttft_ms,
                        "latency_ms": call.latency_ms,
                        "status": call.status,
                        "stream": call.stream,
                    },
                )
                existing_row = await session.execute(
                    text("SELECT * FROM run_llm_calls WHERE id = :id"),
                    {"id": call.id},
                )
                row = existing_row.mappings().first()
                if row is not None:
                    existing = _call_from_row(dict(row))
                    _assert_ledger_idempotent(existing, call)
                    committed.append(existing)
        return committed

    async def list_calls(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LLMCostCall]:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM run_llm_calls
                    WHERE run_id = :run_id
                    ORDER BY start_ts ASC, id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"run_id": run_id, "limit": max(1, min(limit, 500)), "offset": max(0, offset)},
            )
            return [_call_from_row(dict(row)) for row in result.mappings().all()]

    async def run_summary(self, run_id: str) -> Dict[str, Any]:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM run_llm_calls
                    WHERE run_id = :run_id
                    ORDER BY start_ts ASC, id ASC
                    """
                ),
                {"run_id": run_id},
            )
            calls = [_call_from_row(dict(row)) for row in result.mappings().all()]
        summary = summarize_calls(run_id, calls)
        from ..models.usage import get_usage_recorder
        summary.update(get_usage_recorder().integrity(run_id))
        if not summary["capture_complete"]:
            summary["token_usage_complete"] = False
            summary["cost_complete"] = False
        return summary

    async def count_calls(self, run_id: str) -> int:
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) AS count FROM run_llm_calls WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            return int(result.mappings().first()["count"])


class InMemoryCostLedgerStore(CostLedgerStore):
    """In-memory cost ledger with the same async contract."""

    def __init__(self) -> None:
        self.calls: List[LLMCostCall] = []
        self._ids: set[str] = set()

    async def record_calls(
        self,
        batch: List[LLMCallRecord],
        *,
        pricing: Optional[List[ModelPricingItem]] = None,
    ) -> List[LLMCostCall]:
        ledger = [build_ledger_call(rec, pricing=pricing) for rec in batch if rec and rec.run_id]
        inserted: List[LLMCostCall] = []
        for call in ledger:
            if call.id in self._ids:
                existing = next(c for c in self.calls if c.id == call.id)
                _assert_ledger_idempotent(existing, call)
                continue  # 幂等：同 id 同内容不重复落
            self._ids.add(call.id)
            self.calls.append(call)
            inserted.append(call)
        return inserted

    def _run_calls(self, run_id: str) -> List[LLMCostCall]:
        rows = [call for call in self.calls if call.run_id == run_id]
        rows.sort(key=lambda c: (c.start_ts or "", c.id))
        return rows

    async def list_calls(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LLMCostCall]:
        rows = self._run_calls(run_id)
        start = max(0, offset)
        return rows[start : start + max(1, min(limit, 500))]

    async def run_summary(self, run_id: str) -> Dict[str, Any]:
        return summarize_calls(run_id, self._run_calls(run_id))

    async def count_calls(self, run_id: str) -> int:
        return len(self._run_calls(run_id))


_cost_ledger_store_singleton: Optional[CostLedgerStore] = None


def get_cost_ledger_store() -> CostLedgerStore:
    global _cost_ledger_store_singleton
    if _cost_ledger_store_singleton is None:
        _cost_ledger_store_singleton = CostLedgerStore()
    return _cost_ledger_store_singleton
