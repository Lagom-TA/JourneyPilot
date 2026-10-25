from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional
from travel_agent.storage.cost_ledger_store import cost_event_summary
from travel_agent.tools.exposure_ledger import get_tool_exposure_ledger
from travel_agent.runtime.budget import peek_ledger

logger = logging.getLogger(__name__)


class ChatAccounting:
    def __init__(
        self, *, run_id, message_id, cost_ledger_store, usage_recorder, trip_run_store
    ):
        self.run_id = run_id
        self.message_id = message_id
        self.cost_ledger_store = cost_ledger_store
        self.usage_recorder = usage_recorder
        self.trip_run_store = trip_run_store

    async def flush_usage_updates(self) -> List[Dict[str, Any]]:
        """周期性 drain 捕获层 → 算成本落库 → 返回本 run 的 usage_update SSE 事件。

        recorder 是进程单例、并发 run 共用：drain 出的记录按各自 run_id 落库（都持久化），
        但只有本 run 的记录发 usage_update（audit-safe：只有计数与成本，无内容）。
        """
        if self.cost_ledger_store is None or self.usage_recorder is None:
            return []
        batch = await asyncio.to_thread(self.usage_recorder.drain)
        if not batch:
            return []
        try:
            ledger = await self.cost_ledger_store.record_calls(batch)
            await asyncio.to_thread(self.usage_recorder.ack, batch)
        except Exception as exc:
            logger.warning(f"usage 落库失败（保留 {len(batch)} 条待重试）: {exc}")
            return []
        events: List[Dict[str, Any]] = []
        for call in ledger:
            if call.run_id != self.run_id:
                continue

            events.append(
                {
                    "type": "usage_update",
                    "call_id": call.id,
                    "message_id": self.message_id,
                    "run_id": self.run_id,
                    "node": call.node,
                    "agent": call.agent,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "total_tokens": call.total_tokens,
                    "cost_usd": call.cost_usd,
                    "estimated": call.estimated,
                    "usage_complete": call.usage_complete,
                }
            )
        return events

    async def finalize_cost_summary(
        self, *, terminal: bool
    ) -> Optional[Dict[str, Any]]:
        """终结时兜底 drain + 落库，返回 run 级成本汇总。

        终态按落库真实结果分流事件（CB-02）：全部落库成功发 run.cost_recorded；有本 run 记录
        落库失败则保留待重试 + 发 run.cost_record_failed（携 record_failed 计数），事件流不再撒谎。
        record_failed 一并随 run_cost_summary 下发供前端诚实呈现。
        """
        if self.cost_ledger_store is None:
            return None
        record_failed = 0
        record_error: Optional[str] = None
        if self.usage_recorder is not None:
            batch = await asyncio.to_thread(self.usage_recorder.drain, run_id=self.run_id)
            if batch:
                try:
                    await self.cost_ledger_store.record_calls(batch)
                    await asyncio.to_thread(self.usage_recorder.ack, batch)
                except Exception as exc:
                    record_failed = sum(1 for rec in batch if rec.run_id == self.run_id)
                    record_error = exc.__class__.__name__
                    logger.warning(
                        f"usage 终结落库失败（保留 {len(batch)} 条待重试，本 run {record_failed} 条）: {exc}"
                    )
        try:
            summary = await self.cost_ledger_store.run_summary(self.run_id)
        except Exception as exc:
            logger.warning(f"run 成本汇总失败: {exc}")
            return None

        try:
            summary["tool_context_saving"] = get_tool_exposure_ledger().summary(
                self.run_id
            )
        except Exception as exc:
            logger.debug(f"tool_context_saving 汇总失败（不影响主流）: {exc}")
        summary["record_failed"] = record_failed
        if self.usage_recorder is not None:
            await asyncio.to_thread(self.usage_recorder.apply_integrity, summary)
            record_failed = summary["record_failed"]

        budget_ledger = peek_ledger(self.run_id)
        if budget_ledger is not None:
            summary["run_budget"] = budget_ledger.report()
        if terminal:
            if record_failed:
                event_type = "run.cost_record_failed"
                payload = {
                    **cost_event_summary(summary),
                    "record_failed": record_failed,
                    "error": record_error,
                }
            else:
                event_type = "run.cost_recorded"
                payload = cost_event_summary(summary)
            try:
                await self.trip_run_store.append_event(self.run_id, event_type, payload)
            except Exception as exc:
                logger.warning(f"{event_type} 事件写入失败: {exc}")
        return summary
