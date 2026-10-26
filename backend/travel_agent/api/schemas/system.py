from __future__ import annotations

from typing import Any
from typing import Dict
from pydantic import BaseModel
from pydantic import Field
from travel_agent.config.models import MAX_COMPLETION_TOKENS


class ModelConfigRequest(BaseModel):
    """更新主力模型配置"""

    api_key: str
    model_name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    # 默认值取自 ``config.MAX_COMPLETION_TOKENS``，不在此重复定义：该值会写入
    # 设置并持久化，省略字段的 POST 不应降低运行中部署的上限。
    max_tokens: int = Field(default=MAX_COMPLETION_TOKENS, ge=1)
    temperature: float = 0.7
    tier: str = "primary"


class SystemStatus(BaseModel):
    status: str
    version: str = "2.0"
    tools_count: int = 0
    db_connected: bool = False
    redis_connected: bool = False
    # 记忆抽取累计计数：attempted/succeeded/failed/facts_written/
    # portraits_written/last_error，用于通过 /api/status 检查异步抽取链路状态。
    memory_extraction: Dict[str, Any] = Field(default_factory=dict)
