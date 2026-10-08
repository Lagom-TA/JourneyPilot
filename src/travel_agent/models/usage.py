"""LLM usage capture layer（C 域遥测捕获）.

本模块只做**捕获与进程内缓冲**：把每一次 LLM 调用的 token（含缓存/推理细分）、
wall time、TTFT、model、tier 以及 run/node/agent 归因收敛成一条 ``LLMCallRecord``，
投进线程/协程安全的 ``UsageRecorder`` 缓冲区。落库、成本计算、价格表、SSE 暴露都不
在这里。

设计要点：

- **归因**复用 run 控制层的 contextvars（``current_run_id`` / ``current_node`` /
  ``current_agent``），无 run 上下文（run_id 为 None，例如离线 eval）时**静默跳过**，
  以保证既有用例零回归。
- **token 字段命名**向 OTel GenAI 语义约定（development 阶段）对齐：
  ``input_tokens`` / ``output_tokens`` / ``cached_input_tokens`` /
  ``reasoning_output_tokens``（不用 prompt/completion 旧名）。
- **DeepSeek 缓存细分**是顶层 ``prompt_cache_hit_tokens``，LangChain 的标准
  ``usage_metadata`` 映射会丢——需要时从 ``response_metadata["token_usage"]`` 原始
  dict 补读（04 号 §4）。
- **全零 usage 对象**（个别供应商的中间 chunk 回 0 而非 null）不视作真实计数：
  input/output/total 全为 0/None 时判为「缺失」，走 estimated 降级。
- **usage 缺失**：成功响应使用共享离线估算并标记 ``estimated=True``；错误或取消时
  用量保持未知。估算不能替代实际账单。
"""

from __future__ import annotations

import collections
import threading
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from .token_counting import estimate_tokens as estimate_tokens


# 缓冲上限：08 落库方尚未接线时（或落库暂时落后）避免无界增长；超限丢最旧并计数。
DEFAULT_BUFFER_MAX = 10_000


def generate_call_id() -> str:
    return f"llm_{uuid.uuid4().hex[:16]}"


# --------------------------------------------------------------------------- #
# 归因：读取 run 控制层的 contextvars（懒导入，避免 models -> workflows 的硬依赖环）
# --------------------------------------------------------------------------- #

def read_attribution() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (run_id, node, agent)。任一读取失败时退化为全 None（静默跳过记账）。"""
    try:
        from ..workflows.run_control import current_agent, current_node, current_run_id
    except Exception:  # pragma: no cover - run_control 恒可用，仅作防御
        return None, None, None
    return current_run_id.get(), current_node.get(), current_agent.get()


def infer_provider(base_url: Optional[str], model_name: str = "") -> str:
    """从 base_url / 模型名粗判供应商（08 定价按 provider 前缀匹配时用）。"""
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
    """一次 LLM 调用的计量记录（04 号 §3 的字段面，成本列留给 08 落库时计算）。"""

    id: str
    run_id: str
    node: Optional[str]
    agent: Optional[str]
    tier: Optional[str]
    provider: Optional[str]
    model_request: str
    method: str  # ainvoke | ainvoke_with_tools | astream | astream_with_tools
    stream: bool
    start_ts: str  # ISO8601（wall clock，供 08 落库）
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
    """进程内计量缓冲：捕获方 ``record()``，落库方（08）``drain()`` 取走。

    线程/协程安全：LangGraph 的异步节点共享事件循环，但 Pregel 亦可能在线程池里
    跑同步节点——统一用一把 ``threading.Lock`` 保护，代价可忽略。
    """

    def __init__(self, maxlen: int = DEFAULT_BUFFER_MAX) -> None:
        self._buffer: "collections.deque[LLMCallRecord]" = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dropped = 0

    def record(self, rec: LLMCallRecord) -> None:
        with self._lock:
            if self._buffer.maxlen is not None and len(self._buffer) >= self._buffer.maxlen:
                self._dropped += 1  # deque 满时 append 会自动挤掉最旧的一条
            self._buffer.append(rec)

    def drain(self) -> List[LLMCallRecord]:
        """取走并清空全部缓冲记录（FIFO 顺序）。"""
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            return items

    def requeue(self, records: List[LLMCallRecord]) -> None:
        """把一批落库失败的记录放回缓冲头部，等待下一次 drain 重试。

        ``record_calls`` 按 id 幂等，重试安全；放回头部保持 FIFO，让最早失败的先被重试。
        缓冲已满时 extendleft 从右端（最新）挤出并计入 dropped——落库失败是罕见路径，
        这里让「已产生但未落库」的旧计量优先于尚在缓冲的新计量。
        """
        if not records:
            return
        with self._lock:
            before = len(self._buffer)
            self._buffer.extendleft(reversed(records))
            overflow = before + len(records) - len(self._buffer)
            if overflow > 0:
                self._dropped += overflow

    def snapshot(self) -> List[LLMCallRecord]:
        """只读快照，不清空（测试/巡检用）。"""
        with self._lock:
            return list(self._buffer)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._dropped = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


_recorder_singleton: Optional[UsageRecorder] = None


def get_usage_recorder() -> UsageRecorder:
    """进程级计量缓冲单例（router 捕获与 AppComponents 暴露共用同一实例）。"""
    global _recorder_singleton
    if _recorder_singleton is None:
        _recorder_singleton = UsageRecorder()
    return _recorder_singleton


# --------------------------------------------------------------------------- #
# usage 提取 / 估算 helpers（纯函数，供 router 织入调用）
# --------------------------------------------------------------------------- #

def _as_int(value: Any) -> Optional[int]:
    """Accept nonnegative integer counts only; malformed telemetry is missing."""
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
    """供应商的终止原因；``length`` 就是输出撞上 max_tokens 被截断的那个事实。

    截断的 JSON 不可解析，worker 定型只能报「不是精确 JSON 对象」——两端对不上时，
    finish_reason 是唯一能把「模型没写对」和「输出被截断」分开的证据。流式路径读的是
    累加后 chunk 的 ``response_metadata``（终结 chunk 带 finish_reason）。
    """
    meta = _getter(message)("response_metadata") or {}
    if not isinstance(meta, dict):
        return None
    reason = meta.get("finish_reason") or meta.get("stop_reason")
    return str(reason) if reason else None


def response_model_name(message: Any) -> Optional[str]:
    meta = _getter(message)("response_metadata") or {}
    if isinstance(meta, dict):
        name = meta.get("model_name") or meta.get("model")
        if name:
            return str(name)
    return None


def _is_empty_usage(input_tokens: Optional[int], output_tokens: Optional[int], total: Optional[int]) -> bool:
    """input/output/total 全为 None 或 0 → 视作缺失（全零 usage 对象不当真实计数用）。"""
    return all(v in (None, 0) for v in (input_tokens, output_tokens, total))


def extract_usage(message: Any) -> Optional[Dict[str, Optional[int]]]:
    """Normalize inclusive input/output totals from standard AND raw usage.

    Read/write are disjoint subsets of input. Reasoning is a subset of output,
    never an additional completion charge. Anthropic-shaped raw input excludes
    cache buckets; convert it once when standardized totals are unavailable.
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
        reported_total = None  # Empty standard total is another adapter placeholder.
    # Standard adapters may insert zero for an absent side. A positive raw
    # total establishes that this placeholder is missing, rather than free.
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
    # Derive a missing side only when a genuine total and the other side exist.
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
    """Expose only returned usage, without retaining an error body or prompt."""
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
