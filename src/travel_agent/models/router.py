"""
统一模型路由层。

用单一入口管理 primary / fast 两档模型，避免散落的实例化逻辑。
未配置真实模型时直接抛出 RuntimeError（不提供占位实现）。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import time
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from ..config import (
    FastModelConfig,
    PrimaryModelConfig,
    ProviderCapabilities,
    capabilities_for,
    get_settings,
    resolve_price,
)
from ..entities.trip_run import utc_now_iso
from ..config.providers import TokenLimitField
from ..utils.concurrency import channel_gate
from ..workflows.run_control import (
    ModelWindowClosed,
    await_model_operation,
    current_budget_ledger,
    current_model_window,
    guard_run_budget,
    observe_current_run_deadline,
    remaining_model_seconds,
)
from .usage import (
    LLMCallRecord,
    UsageRecorder,
    estimate_tokens,
    extract_usage,
    error_usage_message,
    generate_call_id,
    get_usage_recorder,
    infer_provider,
    read_attribution,
    response_finish_reason,
    response_model_name,
)
from .chat_client import ReasoningChatOpenAI, reasoning_replay
from .request_policy import is_openai_reasoning_model, model_reasoning_effort
from .token_counting import estimate_request_tokens

logger = logging.getLogger(__name__)


class IncompleteModelResponse(RuntimeError):
    """A Responses request ended without a completed response envelope."""

    def __init__(self, message: Any) -> None:
        self.message = message
        reason = response_finish_reason(message) or "missing_terminal_response"
        super().__init__(f"Model response did not complete: {reason}")


def estimate_output_text(response: Any) -> str:
    """Visible output estimate includes function arguments as well as prose."""
    text = _coerce_text(response.content)
    tool_calls = (getattr(response, "tool_calls", None) or []) + (getattr(response, "invalid_tool_calls", None) or [])
    if tool_calls:
        text += json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":"))
    return text


def _close_unstarted(awaitable: Any) -> None:
    """关掉一个还没被 await 的协程。已经跑过的对象上是 no-op。"""

    close = getattr(awaitable, "close", None)
    if callable(close):
        try:
            close()
        except RuntimeError:
            pass


@runtime_checkable
class BaseLLM(Protocol):
    """本模块使用的 LLM 协议类型（duck typing，由各实现类自带签名对齐）。"""

    async def ainvoke(self, messages: List[Dict[str, Any]], **kwargs: Any) -> str: ...

    async def ainvoke_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]: ...

    async def astream(
        self, messages: List[Dict[str, Any]], **kwargs: Any
    ) -> AsyncIterator[str]: ...

    async def astream_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]: ...

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    ChatOpenAI = ReasoningChatOpenAI
except ImportError:  # pragma: no cover - langchain 未安装时降级（如纯前端开发环境）
    AIMessage = HumanMessage = SystemMessage = ToolMessage = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]


class ModelTier(str, Enum):
    PRIMARY = "primary"
    FAST = "fast"


#: 档位默认对应的并发通道。名字与 `ProviderChannelConfig` 的字段一一对应。
_TIER_CHANNELS = {
    ModelTier.PRIMARY: "primary_research_llm",
    ModelTier.FAST: "online_fast_llm",
}

# 一次调用属于哪个通道。默认按档位，但**入库**要走自己的配额：它和在线快问快答用
# 同一个 fast 上游，不分开的话一次上传就能把在线请求排到队尾。
current_llm_channel: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_llm_channel",
    default=None,
)


@contextlib.contextmanager
def llm_channel(name: str) -> Iterator[None]:
    """把这一段里的模型调用记到 ``name`` 通道的配额上。"""

    token = current_llm_channel.set(name)
    try:
        yield
    finally:
        current_llm_channel.reset(token)


def _coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _messages_text(messages: List[Dict[str, Any]]) -> str:
    """拼接入参消息文本，供 usage 缺失时的字符数粗估（仅估算用途）。"""
    parts: List[str] = []
    for msg in messages or []:
        if isinstance(msg, dict):
            parts.append(_coerce_text(msg.get("content", "")))
    return "".join(parts)


def _chunk_text(text: str, chunk_size: int = 48) -> Iterable[str]:
    normalized = text or ""
    if not normalized:
        return []
    return [normalized[i : i + chunk_size] for i in range(0, len(normalized), chunk_size)]


def _normalize_tool_calls(raw_calls: Any) -> List[Dict[str, Any]]:
    tool_calls: List[Dict[str, Any]] = []
    if not isinstance(raw_calls, list):
        return tool_calls

    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        args = item.get("args", item.get("arguments", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError, TypeError):
                args = {"raw": args}
        if not isinstance(args, dict):
            args = {}
        name = str(item.get("name") or "")
        if not name:
            continue
        tool_calls.append(
            {
                "id": str(item.get("id") or item.get("tool_call_id") or name),
                "name": name,
                "arguments": args,
            }
        )
    return tool_calls


def _to_langchain_messages(messages: List[Dict[str, Any]]) -> List[Any]:
    if SystemMessage is None or HumanMessage is None or AIMessage is None or ToolMessage is None:
        raise RuntimeError("langchain 消息类不可用，无法构建真实模型消息")

    converted: List[Any] = []
    # 合法的 tool 响应必须紧随拥有对应 tool_call_id 的 assistant tool_calls。
    # worker 曾把预取的地点/缺口上下文以 role="tool" 注入；宽松 provider 接受，
    # DeepSeek 则会 400。孤立、错配或已被后续普通消息隔开的 tool 结果降级为 user
    # 上下文，避免伪造 tool 协议关系而不丢失文本。
    pending_tool_call_ids: set[str] = set()
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = msg.get("content", "")

        if role == "system":
            converted.append(SystemMessage(content=content))
            pending_tool_call_ids.clear()
            continue

        if role == "assistant":
            # tool_calls 必须进 AIMessage 的结构化字段：langchain 序列化时才会补全
            # OpenAI wire 格式的 type="function" + function 包裹。塞进 additional_kwargs
            # 会被原样透传、缺 type，触发 provider 400 `messages[N]: missing field type`
            # ——ReAct 迭代 1 起每轮都携带上一轮的 assistant tool_calls，故必现。
            tool_calls = [
                {"name": tc["name"], "args": tc["arguments"], "id": tc["id"], "type": "tool_call"}
                for tc in _normalize_tool_calls(msg.get("tool_calls"))
            ]
            converted.append(AIMessage(
                content=content,
                tool_calls=tool_calls,
                additional_kwargs=reasoning_replay(msg.get("assistant_replay") or {}),
            ))
            pending_tool_call_ids = {str(call["id"]) for call in tool_calls}
            continue

        if role == "tool":
            raw_tool_call_id = msg.get("tool_call_id")
            tool_call_id = str(raw_tool_call_id) if raw_tool_call_id is not None else ""
            if tool_call_id and tool_call_id in pending_tool_call_ids:
                converted.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                    )
                )
                pending_tool_call_ids.remove(tool_call_id)
            else:
                converted.append(HumanMessage(content=f"[工具结果] {content}"))
                # 一条非协议 tool 消息已经把 assistant/tool 相邻关系打断；后续 tool
                # 消息不能再借用更早 assistant 的 tool_calls。
                pending_tool_call_ids.clear()
            continue

        converted.append(HumanMessage(content=content))
        pending_tool_call_ids.clear()
    return converted


def _provider_extra_body(
    capabilities: ProviderCapabilities, *, max_tokens: int, reasoning_effort: str = "low"
) -> Dict[str, Any]:
    """Translate an enabled reasoning policy and output limit to the wire dialect."""

    body: Dict[str, Any] = {}
    control = capabilities.reasoning_control
    if control in ("deepseek", "all_dialects"):
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = reasoning_effort
    if control in ("openrouter", "all_dialects"):
        body["reasoning"] = {"effort": reasoning_effort, "enabled": True}
    if capabilities.token_limit_field in ("max_tokens", "both"):
        body["max_tokens"] = max_tokens
    return body


_JSON_OBJECT_PROMPT_TOKEN = (
    "以 JSON (json) 对象返回结果，不要输出 JSON 之外的任何文本。"
)


def _normalize_response_format(
    kwargs: Dict[str, Any], *, capabilities: ProviderCapabilities
) -> Dict[str, Any]:
    """按上游声明的 capability 决定要不要降级 response format。

    降级的判据从「base_url 长得像不像 api.deepseek.com」换成了一份**声明**
    （`configs/providers/*.yaml`）：前者在同一个模型搬到代理后面那天就不成立，
    而失效是静默的 —— 开关不再命中，结构化输出退回一个形状正确但键名不对的对象。

    认不出的上游走保守档（不声明支持 json_schema），走 json_object + 在 prompt 里
    明写 schema 那条路。它更啰嗦但两边都能到；反过来（假设支持）拿到的是一次 400。
    """
    response_format = kwargs.get("response_format")
    if (
        not capabilities.supports_json_schema
        and isinstance(response_format, dict)
        and response_format.get("type") == "json_schema"
    ):
        return {**kwargs, "response_format": {"type": "json_object"}}
    return kwargs


def _satisfy_json_object_prompt_requirement(
    messages: List[Dict[str, Any]],
    kwargs: Dict[str, Any],
    *,
    dropped_schema: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Restore in the prompt what the ``json_object`` downgrade took away.

    Two things ride on a caller's ``json_schema``: the literal word ``json``
    (DeepSeek rejects ``json_object`` without it) and the response shape itself.
    ``json_object`` enforces neither, so a call site that relied on the schema
    alone to convey its shape gets a well-formed object with the wrong keys.  The
    router states both in the prompt instead.  Callers who already spell out JSON
    and pass no schema are left untouched.
    """
    response_format = kwargs.get("response_format")
    if not isinstance(response_format, dict) or response_format.get("type") != "json_object":
        return messages
    instructions: List[str] = []
    if not any("json" in str(message.get("content") or "").lower() for message in messages):
        instructions.append(_JSON_OBJECT_PROMPT_TOKEN)
    if (
        isinstance(dropped_schema, dict)
        and dropped_schema
        and not _messages_already_contain_schema(messages, dropped_schema)
    ):
        instructions.append(
            "返回对象必须严格满足此 JSON Schema（键名、必填项、层级一律照此输出）："
            f"{json.dumps(dropped_schema, ensure_ascii=False)}"
        )
    if not instructions:
        return messages
    return [*messages, {"role": "user", "content": "".join(instructions)}]


def _messages_already_contain_schema(
    messages: List[Dict[str, Any]], schema: Dict[str, Any]
) -> bool:
    """Do not paste the same structured-output schema into a prompt twice.

    Some high-context agents already render their response schema beside the
    domain contract.  A provider downgrade from ``json_schema`` to
    ``json_object`` used to append that schema a second time, adding thousands
    of identical prompt tokens on every repair round.  Compare the canonical
    compact JSON representation so whitespace differences do not defeat the
    check; callers that do not carry the schema still receive the router-owned
    instruction.
    """

    compact = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return any(compact in str(message.get("content") or "") for message in messages)


def _downgraded_json_schema(
    kwargs: Dict[str, Any], *, capabilities: ProviderCapabilities
) -> Optional[Dict[str, Any]]:
    """Return the schema `_normalize_response_format` is about to drop, if any."""
    response_format = kwargs.get("response_format")
    if not (
        not capabilities.supports_json_schema
        and isinstance(response_format, dict)
        and response_format.get("type") == "json_schema"
    ):
        return None
    wrapper = response_format.get("json_schema")
    if not isinstance(wrapper, dict):
        return None
    schema = wrapper.get("schema")
    return schema if isinstance(schema, dict) and schema else None


class OpenAICompatibleLLM(BaseLLM):
    """基于 langchain-openai 的轻量包装。"""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        temperature: float,
        max_tokens: int,
        timeout: int = 60,
        max_retries: int = 2,
        tier: ModelTier,
        reasoning_effort: Optional[str] = None,
        usage_recorder: Optional[UsageRecorder] = None,
        use_responses_api: bool = False,
        responses_streaming: bool = False,
        token_limit_field: Optional[TokenLimitField] = None,
    ) -> None:
        if ChatOpenAI is None:
            raise RuntimeError("langchain_openai 不可用，无法创建真实模型客户端")

        self.model_name = model_name
        self.tier = tier
        self.base_url = base_url
        self._use_responses_api = use_responses_api
        self._responses_streaming = use_responses_api and responses_streaming
        self.provider = infer_provider(base_url, model_name)
        # 这个上游支持什么，来自 `configs/providers/*.yaml` 的声明；认不出走保守档。
        self.capabilities = capabilities_for(base_url)
        if token_limit_field is not None:
            self.capabilities = self.capabilities.model_copy(update={"token_limit_field": token_limit_field})
        self._reasoning_effort = model_reasoning_effort(
            model_name, reasoning_effort or ("medium" if tier == ModelTier.PRIMARY else "low")
        )
        self._usage_recorder = usage_recorder
        # 预算守卫按「本次最坏输出」估账，而最坏输出就是这个上限。
        self._max_tokens = int(max_tokens)
        self._max_retries = max(0, int(max_retries))
        # ``request_timeout`` is this client's default per SDK attempt.  A call
        # site needing a wider bound passes ``timeout=`` in its own kwargs; the
        # SDK applies that to the single request instead of the shared client.
        self._client = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url=base_url,
            temperature=None if is_openai_reasoning_model(model_name) else temperature,
            reasoning_effort=self._reasoning_effort if (
                is_openai_reasoning_model(model_name)
                or "deepseek" in model_name.lower()
            ) else None,
            max_tokens=max_tokens,
            request_timeout=timeout,
            # Retry in this layer so every attempt receives its own usage row.
            max_retries=0,
            # langchain-openai 仅在默认 OpenAI base_url 下自动开启流式 usage，而本仓
            # 全部模型自定义 base_url，不显式开则流式 usage 永远为空。
            stream_usage=self.capabilities.supports_stream_usage,
            use_responses_api=use_responses_api,
            streaming=self._responses_streaming,
            use_legacy_max_tokens=self.capabilities.token_limit_field == "max_tokens",
            store=False if use_responses_api else None,
            # Responses has native reasoning/output fields; Chat dialect extras
            # would overwrite them after the SDK serializes the request.
            extra_body={} if use_responses_api else _provider_extra_body(
                self.capabilities, max_tokens=max_tokens, reasoning_effort=self._reasoning_effort
            ),
        )

    # --- usage 捕获织入 ------------------------------------------------ #

    def _recorder(self) -> UsageRecorder:
        # 显式 None 判断：UsageRecorder 定义了 __len__，空缓冲会被判 falsy，不能用 `or`。
        if self._usage_recorder is not None:
            return self._usage_recorder
        return get_usage_recorder()

    # --- 并发通道与预算守卫 --------------------------------------------- #

    def _channel(self):
        name = current_llm_channel.get() or _TIER_CHANNELS[self.tier]
        limit = int(getattr(get_settings().provider_channels, name))
        return channel_gate(f"llm.{name}", limit)

    def _guard_budget(
        self,
        operation: str,
        messages: List[Dict[str, Any]],
        *,
        output_tokens: Optional[int] = None,
    ) -> None:
        """在花掉这次调用之前判预算，按最坏开销估账。

        输入侧按字符数粗估（供应商还没告诉我们真实 token），输出侧按配置上限 ——
        这次调用最多能吐出来的就是那么多。
        """

        guard_run_budget(
            operation,
            llm_calls=1,
            input_tokens=estimate_tokens(json.dumps(messages, ensure_ascii=False), self.model_name),
            output_tokens=output_tokens or self._max_tokens,
        )

    def _apply_output_token_limit(
        self, kwargs: Dict[str, Any]
    ) -> tuple[Dict[str, Any], int]:
        """Apply one task-scoped output ceiling in the configured API dialect.

        ``langchain-openai`` serializes ``max_tokens`` as
        ``max_completion_tokens`` while DeepSeek-compatible providers may only
        read the former inside ``extra_body``.  A per-call limit therefore has
        to replace both fields together; changing just one leaves the client's
        configured default active on the other path. Responses instead uses
        its native ``max_output_tokens`` without Chat-specific body overrides.
        """

        kwargs = dict(kwargs)
        if is_openai_reasoning_model(self.model_name):
            for parameter in ("temperature", "top_p", "top_logprobs", "logprobs"):
                kwargs.pop(parameter, None)
        limits = [value for key in ("max_output_tokens", "max_tokens", "max_completion_tokens")
                  if (value := kwargs.pop(key, None)) is not None]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in limits):
            raise ValueError("Output token limits must be positive integers")
        if len({int(value) for value in limits}) > 1:
            raise ValueError("Conflicting output token limits")
        requested = limits[0] if limits else None
        if requested is None:
            return kwargs, self._max_tokens
        limit = int(requested)
        if limit < 1:
            raise ValueError("max_output_tokens must be positive and supported by the model")
        scoped = dict(kwargs)
        if self._use_responses_api:
            # LangChain stores the deployment default under this legacy key
            # and maps it to max_output_tokens during Responses serialization.
            scoped["max_completion_tokens"] = limit
            return scoped, limit
        scoped["max_tokens"] = limit
        scoped["extra_body"] = _provider_extra_body(
            self.capabilities,
            max_tokens=limit,
            reasoning_effort=self._reasoning_effort,
        )
        return scoped, limit

    async def _in_channel(self, awaitable: Awaitable[Any], *, operation: str) -> Any:
        """在通道配额内发起一次调用，并受 Run 的时间窗约束。

        排队等在时间窗**里面**：等不到位置和调用本身太慢对一个 Run 是同一件事 ——
        窗口关了。没有窗口的那一档（快问快答、授权之前）由
        `provider_channels.max_queue_wait_seconds` 兜底，否则通道满了这条请求永远不回来。
        """

        gate = self._channel()
        try:
            wait_seconds = remaining_model_seconds(operation)
            if wait_seconds is None:
                wait_seconds = self._queue_wait_seconds()
            async with gate.hold(wait_seconds=wait_seconds):
                return await await_model_operation(awaitable, operation=operation)
        except BaseException:
            # 同步拒绝（窗口已关、已取消、通道满）时调用方构造好的那个协程还没被 await。
            # 不关掉它就是一条 "coroutine was never awaited" 警告。
            _close_unstarted(awaitable)
            raise

    def _queue_wait_seconds(self) -> float:
        return float(get_settings().provider_channels.max_queue_wait_seconds)

    def _validate_response_completion(self, message: Any) -> None:
        if self._use_responses_api:
            metadata = getattr(message, "response_metadata", {}) or {}
            if metadata.get("status") != "completed":
                raise IncompleteModelResponse(message)

    def _start_record(self, method: str, *, stream: bool) -> Optional[LLMCallRecord]:
        """无 run 上下文（离线 eval 等）→ 返回 None，静默跳过记账。"""
        run_id, node, agent = read_attribution()
        if run_id is None:
            return None
        return LLMCallRecord(
            id=generate_call_id(),
            run_id=run_id,
            node=node,
            agent=agent,
            tier=self.tier.value,
            provider=self.provider,
            model_request=self.model_name,
            method=method,
            stream=stream,
            start_ts=utc_now_iso(),
        )

    def _emit(
        self,
        record: Optional[LLMCallRecord],
        monotonic_start: float,
        *,
        status: str = "ok",
        error: Optional[BaseException] = None,
        message: Any = None,
        input_text: str = "",
        output_text: str = "",
        ttft_ms: Optional[float] = None,
        reported_usage: Optional[Dict[str, Optional[int]]] = None,
    ) -> None:
        if record is None:
            return
        record.end_ts = utc_now_iso()
        record.latency_ms = (time.perf_counter() - monotonic_start) * 1000.0
        record.ttft_ms = ttft_ms
        record.status = status
        if error is not None:
            record.error_type = type(error).__name__
            if message is None:
                message = error_usage_message(error)
        if message is not None:
            record.model_response = response_model_name(message)

        usage = reported_usage if reported_usage is not None else extract_usage(message)
        if usage is not None:
            record.input_tokens = usage["input_tokens"]
            record.output_tokens = usage["output_tokens"]
            record.total_tokens = usage["total_tokens"]
            record.cached_input_tokens = usage["cached_input_tokens"]
            record.cache_write_input_tokens = usage["cache_write_input_tokens"]
            record.reasoning_output_tokens = usage["reasoning_output_tokens"]
            record.estimated = False
            record.usage_complete = (
                bool(usage.get("usage_complete", True))
                and record.input_tokens is not None and record.output_tokens is not None
                and (record.cached_input_tokens or 0) + (record.cache_write_input_tokens or 0) <= record.input_tokens
                and (record.reasoning_output_tokens or 0) <= record.output_tokens
            )
            record.usage_source = "reported" if record.usage_complete else "partial"
        elif status == "ok":
            # usage 缺失（流被中断/供应商不回/全零对象）→ 字符数粗估并标记 estimated
            in_est = record.request_input_tokens_estimate
            if in_est is None:
                in_est = estimate_tokens(input_text, self.model_name)
            out_est = estimate_tokens(output_text, self.model_name)
            record.input_tokens = in_est
            record.output_tokens = out_est
            record.total_tokens = in_est + out_est
            record.estimated = True
            record.usage_complete = False
            record.usage_source = "estimated"
        else:
            record.usage_complete = False
            record.usage_source = "missing"
        record.finish_reason = response_finish_reason(message)
        # status=error 且无 usage：token 列留 null，绝不编数

        # 每次调用一行取证：finish_reason=length 即输出被 max_tokens 截断，配合
        # output_tokens 就能判断当前输出设置是否把 Research Packet 切断。归因直接用
        # record 的字段（run 控制层 contextvars），不另开一套通道；离线 eval 无 run 上下文
        # 时上面已经返回，日志与记账同进同退。
        logger.info(
            "LLM 调用完成 (call_id=%s, tier=%s, model=%s, method=%s, node=%s, agent=%s, "
            "status=%s, finish_reason=%s, output_tokens=%s, estimated=%s, latency_ms=%.0f)",
            record.id,
            record.tier,
            record.model_request,
            record.method,
            record.node,
            record.agent,
            record.status,
            response_finish_reason(message) or "unknown",
            record.output_tokens,
            record.estimated,
            record.latency_ms,
        )

        self._recorder().record(record)
        self._charge_budget(record)

    def _charge_budget(self, record: Optional[LLMCallRecord]) -> None:
        """把这一次调用记进 Run 的预算账本。

        费用用**同一个公式**（`cost_ledger_store.compute_cost_usd`）算：预算和台账
        对同一次调用给两个价钱，就没有一个数字能当上限用。价格表没命中时账本记一次
        未定价调用，而不是记 0 元。

        失败的调用也计数：它一样占了配额、一样可能被无限循环重复。
        """

        ledger = current_budget_ledger()
        if ledger is None or record is None:
            return
        # 延迟 import：台账层要经 `models.usage` 拿 LLMCallRecord，模块级引用会成环。
        from ..infrastructure.cost_ledger_store import compute_cost_usd

        price = resolve_price(record.model_request, record.provider)
        ledger.record_llm_call(
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            usage_complete=record.usage_complete and not record.estimated,
            cost_usd=compute_cost_usd(
                price,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cached_input_tokens=record.cached_input_tokens,
                cache_write_input_tokens=record.cache_write_input_tokens,
            ),
        )

    def _request_estimate(
        self, record: Optional[LLMCallRecord], messages: List[Dict[str, Any]],
        kwargs: Dict[str, Any], tools: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if record is None:
            return
        request_kwargs = dict(kwargs)
        if tools is not None:
            request_kwargs["tools"] = tools
        payload = self._client._get_request_payload(_to_langchain_messages(messages), **request_kwargs)
        record.request_input_tokens_estimate, record.tool_schema_tokens_estimate = estimate_request_tokens(
            payload, self.model_name
        )

    @staticmethod
    def _retryable(error: BaseException) -> bool:
        from openai import APIConnectionError, APIStatusError

        return isinstance(error, APIConnectionError) or (
            isinstance(error, APIStatusError) and (
                error.status_code in {408, 409, 429} or error.status_code >= 500
            )
        )

    async def _invoke_message(
        self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any], *,
        method: str, output_limit: int, tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        logical_id = generate_call_id()
        for attempt in range(self._max_retries + 1):
            self._guard_budget(f"model.{method}", messages, output_tokens=output_limit)
            record = None
            started = time.perf_counter()
            bound = self._client.bind_tools(tools) if tools is not None else self._client

            async def invoke_admitted():
                nonlocal record, started
                # The channel/deadline guards must accept the operation before
                # outbox admission: a rejected coroutine never reaches a provider.
                record = self._start_record(method, stream=self._responses_streaming)
                if record is not None:
                    record.logical_call_id, record.attempt_number = logical_id, attempt + 1
                self._request_estimate(record, messages, kwargs, tools)
                if record is not None:
                    self._recorder().admit(record)
                started = time.perf_counter()
                return await bound.ainvoke(_to_langchain_messages(messages), **kwargs)

            try:
                response = await self._in_channel(
                    invoke_admitted(),
                    operation=f"model.{method}",
                )
                self._validate_response_completion(response)
            except BaseException as exc:
                self._emit(record, started, status="cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                           error=exc, message=getattr(exc, "message", None) if isinstance(exc, IncompleteModelResponse) else None)
                if attempt < self._max_retries and self._retryable(exc):
                    await await_model_operation(asyncio.sleep(min(0.5 * 2 ** attempt, 8)),
                                                operation=f"model.{method}.retry_wait")
                    continue
                raise
            self._emit(record, started, message=response, output_text=estimate_output_text(response))
            return response
        raise AssertionError("unreachable")

    async def ainvoke(self, messages: List[Dict[str, Any]], **kwargs: Any) -> str:
        kwargs, output_limit = self._apply_output_token_limit(kwargs)
        dropped_schema = _downgraded_json_schema(kwargs, capabilities=self.capabilities)
        kwargs = _normalize_response_format(kwargs, capabilities=self.capabilities)
        messages = _satisfy_json_object_prompt_requirement(
            messages, kwargs, dropped_schema=dropped_schema
        )
        response = await self._invoke_message(
            messages, kwargs, method="ainvoke", output_limit=output_limit,
        )
        return _coerce_text(response.content).strip()

    async def ainvoke_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from .task_routing import chat_tool_protocol_supported
        if not chat_tool_protocol_supported(self.model_name):
            raise ValueError("gpt-6.1-sol tool requests require a Responses adapter")
        kwargs, output_limit = self._apply_output_token_limit(kwargs)
        dropped_schema = _downgraded_json_schema(kwargs, capabilities=self.capabilities)
        kwargs = _normalize_response_format(kwargs, capabilities=self.capabilities)
        messages = _satisfy_json_object_prompt_requirement(
            messages, kwargs, dropped_schema=dropped_schema
        )
        response = await self._invoke_message(
            messages, kwargs, method="ainvoke_with_tools", output_limit=output_limit, tools=tools,
        )
        result = {
            "content": _coerce_text(response.content).strip(),
            "tool_calls": _normalize_tool_calls(getattr(response, "tool_calls", [])),
            "assistant_replay": reasoning_replay(response.additional_kwargs),
        }
        return result

    async def astream(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> AsyncIterator[str]:
        kwargs, output_limit = self._apply_output_token_limit(kwargs)
        dropped_schema = _downgraded_json_schema(kwargs, capabilities=self.capabilities)
        kwargs = _normalize_response_format(kwargs, capabilities=self.capabilities)
        messages = _satisfy_json_object_prompt_requirement(messages, kwargs, dropped_schema=dropped_schema)
        logical_id = generate_call_id()
        for attempt in range(self._max_retries + 1):
            self._guard_budget("model.astream", messages, output_tokens=output_limit)
            record = None
            started = time.perf_counter()
            full: Any = None
            last_usage = None
            ttft_ms = None
            collected: List[str] = []
            status, error, retry = "ok", None, False

            async def consume_stream() -> AsyncIterator[str]:
                nonlocal full, last_usage, ttft_ms, record, started
                remaining = remaining_model_seconds("model.astream")
                queue_wait = remaining if remaining is not None else self._queue_wait_seconds()
                async with self._channel().hold(wait_seconds=queue_wait):
                    remaining_model_seconds("model.astream")
                    record = self._start_record("astream", stream=True)
                    if record is not None:
                        record.logical_call_id, record.attempt_number = logical_id, attempt + 1
                    self._request_estimate(record, messages, kwargs)
                    if record is not None:
                        self._recorder().admit(record)
                    started = time.perf_counter()
                    async for chunk in self._client.astream(_to_langchain_messages(messages), **kwargs):
                        sample = extract_usage(chunk)
                        if sample is not None:
                            # API usage samples are cumulative snapshots. Summing
                            # repeated snapshots double-charges the same output.
                            last_usage = sample
                        full = chunk if full is None else full + chunk
                        text = _coerce_text(getattr(chunk, "content", ""))
                        if text:
                            if ttft_ms is None:
                                ttft_ms = (time.perf_counter() - started) * 1000
                            collected.append(text)
                            yield text

            try:
                remaining = remaining_model_seconds("model.astream")
                if remaining is None:
                    async for text in consume_stream():
                        yield text
                else:
                    try:
                        async with asyncio.timeout(remaining):
                            async for text in consume_stream():
                                yield text
                    except asyncio.TimeoutError as exc:
                        _deadline, observation = observe_current_run_deadline()
                        if observation is None:
                            raise
                        raise ModelWindowClosed("model.astream", observation, current_model_window.get()) from exc
                self._validate_response_completion(full)
            except (GeneratorExit, asyncio.CancelledError) as exc:
                status, error = "cancelled", exc
                raise
            except BaseException as exc:
                status, error = "error", exc
                retry = attempt < self._max_retries and not collected and self._retryable(exc)
                if not retry:
                    raise
            finally:
                self._emit(record, started, status=status, error=error, message=full,
                           reported_usage=last_usage, output_text="".join(collected), ttft_ms=ttft_ms)
            if not retry:
                return
            await await_model_operation(asyncio.sleep(min(0.5 * 2 ** attempt, 8)),
                                        operation="model.astream.retry_wait")

    async def astream_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        # 为了保证接口稳定，这里优先返回完整 finish 事件；主流程仍能正确执行，不依赖
        # 复杂的 tool chunk 解析。计量随委托的 ainvoke_with_tools 记一条非流式记录即可。
        result = await self.ainvoke_with_tools(messages, tools, **kwargs)
        content = str(result.get("content") or "")
        for piece in _chunk_text(content):
            yield {"type": "text_delta", "content": piece}
        yield {
            "type": "finish",
            "content": content,
            "tool_calls": result.get("tool_calls", []),
            "assistant_replay": result.get("assistant_replay", {}),
        }


class ModelRouter:
    """统一管理 primary / fast 两档模型。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._clients: Dict[ModelTier, BaseLLM] = {}
        self._scope_client: Optional[BaseLLM] = None

    def _effective_fast_config(self) -> FastModelConfig:
        fast = self._settings.fast_model.model_copy(deep=True)
        if not fast.api_key:
            fast.api_key = self._settings.primary_model.api_key
        if not fast.base_url:
            fast.base_url = self._settings.primary_model.base_url
        if not fast.model_name:
            fast.model_name = self._settings.primary_model.model_name
        return fast

    def _build_client(self, tier: ModelTier, *, max_retries: int = 2) -> BaseLLM:
        if tier == ModelTier.PRIMARY:
            config = self._settings.primary_model
        else:
            config = self._effective_fast_config()

        api_key = str(config.api_key or "").strip()
        model_name = str(config.model_name or "").strip()
        base_url = str(config.base_url or "").strip()

        missing = [
            name for name, value in (
                ("api_key", api_key),
                ("model_name", model_name),
                ("base_url", base_url),
            ) if not value
        ]
        if missing:
            raise RuntimeError(
                f"未配置 {tier.value}_model: {', '.join(missing)} 必须齐全（请检查 config.yaml）"
            )

        return OpenAICompatibleLLM(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            temperature=float(config.temperature),
            max_tokens=int(config.max_tokens),
            timeout=int(getattr(config, "timeout", 60)),
            max_retries=max_retries,
            tier=tier,
            reasoning_effort=config.reasoning_effort,
            usage_recorder=get_usage_recorder(),
            use_responses_api=config.use_responses_api,
            responses_streaming=config.responses_streaming,
            token_limit_field=config.token_limit_field,
        )

    def _get_or_create(self, tier: ModelTier) -> BaseLLM:
        client = self._clients.get(tier)
        if client is None:
            client = self._build_client(tier)
            self._clients[tier] = client
        return client

    def get_primary(self) -> BaseLLM:
        return self._get_or_create(ModelTier.PRIMARY)

    def get_fast(self) -> BaseLLM:
        return self._get_or_create(ModelTier.FAST)

    def get_for_task(self, task, feedback=None, *, has_tools=False):
        from .task_routing import TaskLLM, select_task_route
        route = select_task_route(
            task, self._settings.primary_model.model_name, self._settings.fast_model.model_name,
            feedback, has_tools=has_tools,
            primary_effort=self._settings.primary_model.reasoning_effort,
            fast_effort=self._settings.fast_model.reasoning_effort,
            primary_protocol="responses" if self._settings.primary_model.use_responses_api else "chat_completions",
            fast_protocol="responses" if self._settings.fast_model.use_responses_api else "chat_completions",
        )
        logger.info("task_model_route task=%s tier=%s model=%s reasoning=%s protocol=%s reason=%s action=%s",
                    route.task.value, route.tier, route.model_name, route.reasoning_effort,
                    route.protocol, route.reason, route.action)
        return TaskLLM(self, route, self._get_or_create(ModelTier(route.tier)))

    def get_scope(self) -> BaseLLM:
        """Scope owns one visible retry, so its transport must perform exactly one request per attempt."""
        if self._scope_client is None:
            self._scope_client = self._build_client(ModelTier.FAST, max_retries=0)
        return self._scope_client

    def update_model(
        self,
        *,
        tier: ModelTier,
        api_key: str,
        model_name: str,
        base_url: str,
        max_tokens: int,
        temperature: float,
    ) -> None:
        target: PrimaryModelConfig | FastModelConfig
        if tier == ModelTier.PRIMARY:
            target = self._settings.primary_model
        else:
            target = self._settings.fast_model

        target.api_key = api_key
        target.model_name = model_name
        target.base_url = base_url
        target.max_tokens = max_tokens
        target.temperature = temperature

        self._clients.pop(tier, None)
        if tier == ModelTier.FAST:
            self._scope_client = None


_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
