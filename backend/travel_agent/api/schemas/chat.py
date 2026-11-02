"""聊天入口的 HTTP 请求合同。"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from travel_agent.conversation.input_safety import MAX_INPUT_LENGTH


class OptimizePromptRequest(BaseModel):
    """提示词优化的请求体；过长、非字符串或缺字段直接 422。"""

    prompt: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
