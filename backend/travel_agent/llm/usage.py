"""LLM 用量捕获层。

把每次 LLM 调用的 token（含缓存/推理细分）、耗时、TTFT、模型、档位以及
run/node/agent 归因收敛为一条 ``LLMCallRecord``，写入线程安全的 ``UsageRecorder``
缓冲。落库、成本计算、价格表与 SSE 暴露不在本模块。

归因复用 run 控制层的 contextvars；无 run 上下文（如离线 eval）时静默跳过记账。
token 字段命名与 OTel GenAI 语义约定对齐。全零 usage 对象视为缺失，成功响应改用
离线估算并标记 ``estimated=True``；估算不能替代实际账单。
"""

from __future__ import annotations

import logging
from pathlib import Path
from copy import deepcopy

from .usage_spool import UsageSpool, UsageSpoolConflict
import threading
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

# 默认取批大小；不限制总记录数，不挤出未确认记录。
DEFAULT_BUFFER_MAX = 10_000


def generate_call_id() -> str:
    return f"llm_{uuid.uuid4().hex[:16]}"


# --------------------------------------------------------------------------- #
# 归因：读取 runtime.context 中共享的执行上下文。
# --------------------------------------------------------------------------- #

def read_attribution() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (run_id, node, agent)；任一读取失败时返回全 None，跳过记账。"""
    try:
        from travel_agent.runtime.context import current_agent, current_node, current_run_id
    except Exception:  # pragma: no cover - context 恒可用，仅作防御
        return None, None, None
    return current_run_id.get(), current_node.get(), current_agent.get()


def infer_provider(base_url: Optional[str], model_name: str = "") -> str:
    """根据 base_url 与模型名推断供应商，用于按 provider 前缀匹配定价。"""
    host = (base_url or "").lower()
    model = (model_name or "").lower()
    for needle, name in (
        ("deepseek", "deepseek"),
        ("minimax", "minimax"),
        ("dashscope", "qwen"),
        ("aliyuncs", "qwen"),
        ("moonshot", "moonshot"),
        ("api.openai.com", "openai"),
    ):
        if needle in host:
            return name
    if "deepseek" in model:
        return "deepseek"
    if "qwen" in model:
        return "qwen"
    if "minimax" in model or model.startswith("abab") or model.startswith("m2"):
        return "minimax"
    return "openai-compat"


# --------------------------------------------------------------------------- #
# 计量记录
# --------------------------------------------------------------------------- #

@dataclass
class LLMCallRecord:
    """一次 LLM 调用的计量记录；成本字段在落库时计算。"""

    id: str
    run_id: str
    node: Optional[str]
    agent: Optional[str]
    tier: Optional[str]
    provider: Optional[str]
    model_request: str
    method: str  # ainvoke | ainvoke_with_tools | astream | astream_with_tools
    stream: bool
    start_ts: str  # ISO8601 wall clock 时间戳
    model_response: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    cache_write_input_tokens: Optional[int] = None
    reasoning_output_tokens: Optional[int] = None
    estimated: bool = False
    usage_complete: bool = True
    usage_source: str = "reported"
    logical_call_id: Optional[str] = None
    attempt_number: int = 1
    request_input_tokens_estimate: Optional[int] = None
    tool_schema_tokens_estimate: Optional[int] = None
    finish_reason: Optional[str] = None
    end_ts: Optional[str] = None
    latency_ms: Optional[float] = None
    ttft_ms: Optional[float] = None  # 仅流式方法有意义
    status: str = "ok"  # ok | error
    error_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 缓冲区
# --------------------------------------------------------------------------- #

class UsageRecorder:
    """待持久化的用量遥测。drain 是读取，ack 在数据库提交后调用。

    maxlen 用作批大小，不是淘汰上限。隔离测试使用内存 SQLite，应用单例使用文件。
    磁盘写入失败时记录保留在内存并计入覆盖率失败；该降级路径不保证进程崩溃后记录
    仍然存在。
    """
    def __init__(self, maxlen=DEFAULT_BUFFER_MAX, *, spool_path=":memory:"):
        self._lock = threading.Lock()
        self._batch_size = max(1, maxlen)
        self._volatile = {}
        self._conflicts = {}
        self._failures = {}
        self._spool_error = False
        try:
            self._spool = UsageSpool(spool_path)
        except Exception as exc:
            logging.getLogger(__name__).error("Usage spool unavailable: %s", type(exc).__name__)
            self._spool = None
            self._spool_error = True

    def _mark_conflict(self, *records):
        for rec in records:
            self._conflicts.setdefault(rec.id, set()).add(rec.run_id)

    def _persist(self, rec, phase, *, retry=False) -> bool:
        existing = self._volatile.get(rec.id)
        if rec.id in self._conflicts or (
            existing and existing[0] == "complete" and existing != (phase, rec)
        ):
            self._mark_conflict(rec, *([existing[1]] if existing else []))
            raise UsageSpoolConflict("call_id has conflicting usage payload")
        try:
            if self._spool is None:
                raise OSError("usage spool unavailable")
            self._spool.put(rec.to_dict(), phase=phase)
            for run_id, count in list(self._failures.items()):
                self._spool.failure(run_id, count)
                del self._failures[run_id]
            self._volatile.pop(rec.id, None)
            self._spool_error = False
            return True
        except UsageSpoolConflict:
            self._mark_conflict(rec)
            self._volatile.setdefault(rec.id, (phase, deepcopy(rec)))
            raise
        except Exception as exc:
            self._spool_error = True
            if not retry:
                self._failures[rec.run_id] = self._failures.get(rec.run_id, 0) + 1
            self._volatile[rec.id] = (phase, deepcopy(rec))
            logging.getLogger(__name__).error("Usage persistence failed call_id=%s error=%s", rec.id, type(exc).__name__)
            return False

    def _put(self, rec, phase):
        with self._lock:
            self._persist(rec, phase)

    def admit(self, rec):
        rec.status, rec.usage_complete, rec.usage_source = "started", False, "missing"
        self._put(rec, "started")

    def record(self, rec):
        self._put(rec, "complete")

    def drain(self, *, run_id=None):
        with self._lock:
            attempts = 0
            write_failed = False
            for phase, rec in list(self._volatile.values()):
                if (phase != "complete" or rec.id in self._conflicts
                        or (run_id and rec.run_id != run_id)):
                    continue
                if attempts >= self._batch_size:
                    break
                attempts += 1
                try:
                    if not self._persist(rec, phase, retry=True):
                        write_failed = True
                        break
                except UsageSpoolConflict:
                    continue
            records = {}
            if self._spool:
                try:
                    if not write_failed:
                        self._spool.recover_abandoned()
                    # 内存记录可能位于持久批次边界之外；冲突处理前先按 id 核对。
                    volatile_ids = [
                        rec.id for phase, rec in self._volatile.values()
                        if phase == "complete" and rec.id not in self._conflicts
                        and (not run_id or rec.run_id == run_id)
                    ]
                    for offset in range(0, len(volatile_ids), 500):
                        ids = volatile_ids[offset:offset + 500]
                        for data in self._spool.pending(include_ids=ids, limit=len(ids)):
                            rec = LLMCallRecord(**data)
                            if self._volatile[rec.id][1] != rec:
                                self._mark_conflict(rec, self._volatile[rec.id][1])
                    while True:
                        records = {}
                        found_conflict = False
                        for data in self._spool.pending(
                            run_id=run_id, limit=self._batch_size,
                            exclude_ids=self._conflicts,
                        ):
                            rec = LLMCallRecord(**data)
                            existing = self._volatile.get(rec.id)
                            if existing and existing[0] == "complete" and existing[1] != rec:
                                self._mark_conflict(rec, existing[1])
                                found_conflict = True
                            else:
                                records[rec.id] = rec
                        if not found_conflict:
                            break
                except Exception as exc:
                    self._spool_error = True
                    logging.getLogger(__name__).error("Usage spool read failed: %s", type(exc).__name__)
            for phase, rec in self._volatile.values():
                if (phase == "complete" and rec.id not in self._conflicts
                        and (not run_id or rec.run_id == run_id)):
                    records[rec.id] = deepcopy(rec)
            return list(records.values())

    def ack(self, records):
        with self._lock:
            records = [rec for rec in records if rec.id not in self._conflicts]
            if self._spool and records:
                self._spool.ack([rec.to_dict() for rec in records])
            for rec in records:
                if self._volatile.get(rec.id) == ("complete", rec):
                    self._volatile.pop(rec.id)

    def snapshot(self):
        return self.drain()

    def integrity(self, run_id):
        with self._lock:
            try:
                pending, failures = self._spool.integrity(run_id) if self._spool else (0, 0)
            except Exception:
                pending, failures = 0, 0
                self._spool_error = True
            pending += sum(1 for _, rec in self._volatile.values() if rec.run_id == run_id)
            pending = max(pending, sum(run_id in runs for runs in self._conflicts.values()))
            failures += self._failures.get(run_id, 0)
            return {"pending_call_count": pending, "spool_write_failed": failures,
                    "capture_complete": not (pending or failures or self._spool_error),
                    "record_failed": pending + failures}

    def apply_integrity(self, summary):
        summary.update(self.integrity(summary["run_id"]))
        if not summary["capture_complete"]:
            summary["token_usage_complete"] = False
            summary["cost_complete"] = False
            if not summary.get("call_count"):
                for key in ("total_tokens", "total_input_tokens", "total_output_tokens",
                            "total_cached_input_tokens", "total_cache_write_input_tokens",
                            "total_reasoning_output_tokens"):
                    summary[key] = None
        return summary

    def clear(self):
        with self._lock:
            if self._spool:
                with self._spool.db:
                    self._spool.db.execute("DELETE FROM usage_outbox")
                    self._spool.db.execute("DELETE FROM usage_capture_failures")
            self._volatile.clear()
            self._conflicts.clear()
            self._failures.clear()

    def __len__(self):
        return len(self.snapshot())


_recorder_singleton: Optional[UsageRecorder] = None


def get_usage_recorder() -> UsageRecorder:
    """进程级计量缓冲单例（router 捕获与 AppComponents 暴露共用同一实例）。"""
    global _recorder_singleton
    if _recorder_singleton is None:
        from ..config.loader import get_settings
        _recorder_singleton = UsageRecorder(spool_path=Path(get_settings().usage.spool_path))
    return _recorder_singleton


# --------------------------------------------------------------------------- #
# usage 提取 / 估算 helpers（纯函数，供 router 织入调用）
# --------------------------------------------------------------------------- #

def _as_int(value: Any) -> Optional[int]:
    """仅接受非负整数计数；格式非法的遥测视为缺失。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        return parsed if parsed >= 0 and float(value) == parsed else None
    except (TypeError, ValueError, OverflowError):
        return None


def _getter(obj: Any):
    if isinstance(obj, dict):
        return obj.get
    return lambda key, default=None: getattr(obj, key, default)


def _first_count(*values: Any) -> Optional[int]:
    return next((count for value in values if (count := _as_int(value)) is not None), None)


def _raw_usage(message: Any) -> dict[str, Any]:
    meta = _getter(message)("response_metadata") or {}
    usage = _getter(meta)("token_usage") or _getter(meta)("usage") or {}
    return usage if isinstance(usage, dict) else {}


def response_finish_reason(message: Any) -> Optional[str]:
    """返回供应商的终止原因；``length`` 表示输出达到 max_tokens 被截断。

    截断的 JSON 无法解析，worker 只能报告「不是精确 JSON 对象」；finish_reason 用于
    区分输出格式错误与输出截断。流式路径从累加 chunk 的 ``response_metadata`` 读取。
    """
    meta = _getter(message)("response_metadata") or {}
    if not isinstance(meta, dict):
        return None
    reason = meta.get("finish_reason") or meta.get("stop_reason")
    if not reason and meta.get("status") == "incomplete":
        details = meta.get("incomplete_details") or {}
        reason = details.get("reason") if isinstance(details, dict) else None
        reason = "length" if reason == "max_output_tokens" else (reason or "incomplete")
    if not reason and meta.get("status") in {"completed", "failed", "cancelled"}:
        reason = "stop" if meta["status"] == "completed" else meta["status"]
    return str(reason) if reason else None


def response_model_name(message: Any) -> Optional[str]:
    meta = _getter(message)("response_metadata") or {}
    if isinstance(meta, dict):
        name = meta.get("model_name") or meta.get("model")
        if name:
            return str(name)
    return None


def _is_empty_usage(input_tokens: Optional[int], output_tokens: Optional[int], total: Optional[int]) -> bool:
    """input/output/total 全为 None 或 0 时视为缺失。"""
    return all(v in (None, 0) for v in (input_tokens, output_tokens, total))


def extract_usage(message: Any) -> Optional[Dict[str, Optional[int]]]:
    """从标准 usage 与原始 usage 归一化 input/output 总量。

    读写缓存是 input 的子集；reasoning 是 output 的子集，不额外计入 completion。
    Anthropic 风格的原始 input 不含缓存部分，在缺少标准总量时转换一次。
    """
    if message is None:
        return None
    standard = _getter(message)("usage_metadata") or {}
    get = _getter(standard)
    raw = _raw_usage(message)
    in_details = get("input_token_details") or {}
    out_details = get("output_token_details") or {}
    raw_in = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    raw_out = raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
    cached = _first_count(raw.get("prompt_cache_hit_tokens"),
                          _getter(raw_in)("cached_tokens"), raw.get("cache_read_input_tokens"),
                          _getter(in_details)("cache_read"))
    written = _first_count(_getter(raw_in)("cache_write_tokens"), _getter(raw_in)("cache_creation_tokens"),
                           raw.get("cache_creation_input_tokens"), raw.get("cache_write_tokens"),
                           _getter(in_details)("cache_creation"), _getter(in_details)("cache_write"))
    reasoning = _first_count(_getter(raw_out)("reasoning_tokens"), _getter(out_details)("reasoning"))
    input_tokens = _as_int(raw.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _as_int(raw.get("input_tokens"))
        if input_tokens is not None and any(key in raw for key in (
            "cache_read_input_tokens", "cache_creation_input_tokens"
        )):
            input_tokens += (cached or 0) + (written or 0)
    if input_tokens is None:
        input_tokens = _as_int(get("input_tokens"))
    output_tokens = _first_count(raw.get("completion_tokens"), raw.get("output_tokens"), get("output_tokens"))
    reported_total = _first_count(raw.get("total_tokens"), get("total_tokens"))
    if reported_total == 0 and "total_tokens" not in raw and ((input_tokens or 0) + (output_tokens or 0)) > 0:
        reported_total = None  # 标准总量为 0 且原始 usage 无 total 时，视为占位值。
    # 标准适配器可能为缺失的一侧填 0。原始 total 为正数时，说明该 0 是占位值
    # 而不是免费额度。
    if reported_total is not None:
        if (not any(key in raw for key in ("prompt_tokens", "input_tokens"))
                and input_tokens == 0 and output_tokens is not None
                and reported_total > output_tokens):
            input_tokens = None
        if (not any(key in raw for key in ("completion_tokens", "output_tokens"))
                and output_tokens == 0 and input_tokens is not None
                and reported_total > input_tokens):
            output_tokens = None
    if _is_empty_usage(input_tokens, output_tokens, reported_total):
        return None
    # 仅在存在有效 total 与另一侧计数时推导缺失的一侧。
    if reported_total is not None:
        if input_tokens is None and output_tokens is not None and reported_total >= output_tokens:
            input_tokens = reported_total - output_tokens
        if output_tokens is None and input_tokens is not None and reported_total >= input_tokens:
            output_tokens = reported_total - input_tokens
    total = input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else reported_total
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": written,
        "reasoning_output_tokens": reasoning,
        "usage_complete": (input_tokens is not None and output_tokens is not None
                           and (reported_total is None or reported_total == total)),
    }


def error_usage_message(error: BaseException) -> Any:
    """只暴露错误中返回的 usage，不保留错误体或 prompt。"""
    completion = getattr(error, "completion", None)
    if completion is not None:
        usage = getattr(completion, "usage", None)
        if usage is not None:
            choices = getattr(completion, "choices", None) or []
            return {"response_metadata": {
                "token_usage": usage.model_dump(),
                "finish_reason": getattr(choices[0], "finish_reason", None) if choices else None,
                "model_name": getattr(completion, "model", None),
            }}
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        body = {}
    usage = body.get("usage") or _getter(body.get("error") or {})("usage")
    if not isinstance(usage, dict):
        response = getattr(error, "response", None)
        if response is not None:
            try:
                raw = response.json()
                usage = raw.get("usage") or _getter(raw.get("error") or {})("usage")
            except (ValueError, TypeError, AttributeError):
                pass
    if not isinstance(usage, dict):
        return None
    return {"response_metadata": {"token_usage": usage}}
