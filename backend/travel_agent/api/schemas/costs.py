from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class LLMCallCostResponse(BaseModel):
    id: str
    run_id: str
    node: Optional[str] = None
    agent: Optional[str] = None
    tier: Optional[str] = None
    provider: Optional[str] = None
    model_request: str = ""
    model_response: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    cache_write_input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    usage_complete: bool = False
    usage_source: str = "legacy"
    logical_call_id: Optional[str] = None
    attempt_number: int = 1
    request_input_tokens_estimate: Optional[int] = None
    tool_schema_tokens_estimate: Optional[int] = None
    finish_reason: Optional[str] = None
    reasoning_output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    estimated: bool = False
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    ttft_ms: Optional[float] = None
    latency_ms: Optional[float] = None
    status: str = "ok"
    stream: bool = False


class RunCostSummaryResponse(BaseModel):
    run_id: str
    record_failed: int = 0
    pending_call_count: int = 0
    spool_write_failed: int = 0
    capture_complete: bool = True
    call_count: int = 0
    priced_call_count: int = 0
    unpriced_call_count: int = 0
    estimated_call_count: int = 0
    error_call_count: int = 0
    estimated_ratio: float = 0.0
    cost_coverage_ratio: float = 0.0
    total_input_tokens: Optional[int] = 0
    total_output_tokens: Optional[int] = 0
    total_cached_input_tokens: Optional[int] = 0
    total_cache_write_input_tokens: Optional[int] = 0
    total_request_input_tokens_estimate: Optional[int] = 0
    total_tool_schema_tokens_estimate: Optional[int] = 0
    token_usage_complete: bool = False
    cache_read_usage_complete: bool = False
    cache_write_usage_complete: bool = False
    reasoning_usage_complete: bool = False
    cache_hit_ratio: Optional[float] = None
    cost_complete: bool = False
    partial_usage_call_count: int = 0
    missing_usage_call_count: int = 0
    logical_call_count: int = 0
    total_reasoning_output_tokens: Optional[int] = 0
    total_tokens: Optional[int] = 0
    total_cost_usd: Optional[float] = None
    currency: str = "USD"
    total_latency_ms: float = 0.0
    wall_ms: Optional[float] = None
    by_agent: List[Dict[str, Any]] = Field(default_factory=list)
    by_node: List[Dict[str, Any]] = Field(default_factory=list)
    bottleneck_by_cost: List[Dict[str, Any]] = Field(default_factory=list)
    bottleneck_by_latency: List[Dict[str, Any]] = Field(default_factory=list)
    # Tool Search 上下文节省量：run 终结时随 SSE run_cost_summary 下发实测值
    # {mode, schema_tokens_injected, schema_tokens_full_baseline, tool_context_saving, ...}；
    # DB 台账（REST 事后查询）不持有进程内曝光计量，故此路径为 null。
    tool_context_saving: Optional[Dict[str, Any]] = None


class RunCostResponse(BaseModel):
    run_id: str
    summary: RunCostSummaryResponse
    calls: List[LLMCallCostResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0
