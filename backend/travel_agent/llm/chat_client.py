"""保留工具调用轮次间推理重放状态的 Chat 客户端。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

REASONING_REPLAY_FIELDS = ("reasoning_content", "reasoning_details", "reasoning")


def reasoning_replay(data: dict[str, Any]) -> dict[str, Any]:
    """复制模型返回的不透明重放字段，不将其渲染为文本。"""
    return {key: deepcopy(data[key]) for key in REASONING_REPLAY_FIELDS if data.get(key) is not None}


try:
    from langchain_openai import ChatOpenAI as _ChatOpenAI
except ImportError:
    ReasoningChatOpenAI = None
else:
    class ReasoningChatOpenAI(_ChatOpenAI):
        """保留 ChatOpenAI 未映射的 Chat Completions 推理字段。"""

        # 上游只接受 ``max_tokens`` 时，把 langchain-openai 改名的
        # ``max_completion_tokens`` 换回该字段。
        send_max_tokens: bool = False

        def _create_chat_result(self, response: Any, generation_info: Any = None) -> Any:
            result = super()._create_chat_result(response, generation_info)
            raw = response if isinstance(response, dict) else response.model_dump()
            for choice, generation in zip(raw.get("choices", []), result.generations):
                generation.message.additional_kwargs.update(reasoning_replay(choice.get("message") or {}))
            return result

        def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict[str, Any]:
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if "messages" in payload:
                if self.send_max_tokens and "max_completion_tokens" in payload:
                    payload["max_tokens"] = payload.pop("max_completion_tokens")
                messages = self._convert_input(input_).to_messages()
                for wire, message in zip(payload["messages"], messages):
                    if message.type == "ai":
                        wire.update(reasoning_replay(message.additional_kwargs))
            return payload

        def _convert_chunk_to_generation_chunk(self, chunk: Any, *args: Any, **kwargs: Any) -> Any:
            result = super()._convert_chunk_to_generation_chunk(chunk, *args, **kwargs)
            if result is None:
                return None
            if chunk.get("usage"):
                # 保留标准 LangChain 映射丢弃的字段，包括 DeepSeek 缓存命中与
                # 缓存写入计数。
                result.message.response_metadata["token_usage"] = deepcopy(chunk["usage"])
            # 流式转换与 _create_chat_result 不同，后者会把推理字段放进
            # additional_kwargs；这里必须显式补回，否则工具轮跨轮重放会丢掉
            # reasoning_content / reasoning_details / reasoning。AIMessageChunk
            # 相加时字符串拼接、列表合并，正好等于非流式响应的重放载荷。
            choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                replay = reasoning_replay(delta)
                if replay:
                    result.message.additional_kwargs.update(replay)
            return result
