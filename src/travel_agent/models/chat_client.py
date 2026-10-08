"""Chat client retaining reasoning replay state across tool-call rounds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

REASONING_REPLAY_FIELDS = ("reasoning_content", "reasoning_details", "reasoning")


def reasoning_replay(data: dict[str, Any]) -> dict[str, Any]:
    """Copy opaque model-returned replay fields without rendering them as text."""
    return {key: deepcopy(data[key]) for key in REASONING_REPLAY_FIELDS if data.get(key) is not None}


try:
    from langchain_openai import ChatOpenAI as _ChatOpenAI
except ImportError:
    ReasoningChatOpenAI = None
else:
    class ReasoningChatOpenAI(_ChatOpenAI):
        """Retain Chat Completions reasoning fields that ChatOpenAI omits."""

        def _create_chat_result(self, response: Any, generation_info: Any = None) -> Any:
            result = super()._create_chat_result(response, generation_info)
            raw = response if isinstance(response, dict) else response.model_dump()
            for choice, generation in zip(raw.get("choices", []), result.generations):
                generation.message.additional_kwargs.update(reasoning_replay(choice.get("message") or {}))
            return result

        def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict[str, Any]:
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if "messages" in payload:
                messages = self._convert_input(input_).to_messages()
                for wire, message in zip(payload["messages"], messages):
                    if message.type == "ai":
                        wire.update(reasoning_replay(message.additional_kwargs))
            return payload

        def _convert_chunk_to_generation_chunk(self, chunk: Any, *args: Any, **kwargs: Any) -> Any:
            result = super()._convert_chunk_to_generation_chunk(chunk, *args, **kwargs)
            if result is not None and chunk.get("usage"):
                # Preserve fields the standard LangChain mapping discards,
                # including DeepSeek cache hits and cache-write counts.
                result.message.response_metadata["token_usage"] = deepcopy(chunk["usage"])
            return result
