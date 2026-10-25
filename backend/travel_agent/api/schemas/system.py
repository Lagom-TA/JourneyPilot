from __future__ import annotations

from typing import Any
from typing import Dict
from pydantic import BaseModel
from pydantic import Field
from travel_agent.config import MAX_COMPLETION_TOKENS


class ModelConfigRequest(BaseModel):
    """更新主力模型配置"""

    api_key: str
    model_name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    # Read from ``config.MAX_COMPLETION_TOKENS`` rather than restated here: this
    # default is written straight into settings and persisted, so a POST that
    # omits the field must not quietly lower a running deployment's ceiling — and
    # a second copy of the number is exactly how that happens.
    max_tokens: int = Field(default=MAX_COMPLETION_TOKENS, ge=1)
    temperature: float = 0.7
    tier: str = "primary"


class SystemStatus(BaseModel):
    status: str
    version: str = "2.0"
    tools_count: int = 0
    db_connected: bool = False
    redis_connected: bool = False
    # 记忆抽取管线累计计数（CB-05）：attempted/succeeded/failed/facts_written/portraits_written/last_error。
    # 让 fire-and-forget 抽取链路的健康在演示前可 curl 确认，不必翻日志。
    memory_extraction: Dict[str, Any] = Field(default_factory=dict)
