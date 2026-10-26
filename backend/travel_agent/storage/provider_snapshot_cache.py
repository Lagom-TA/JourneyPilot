"""可复用的 Provider 事实快照缓存（Redis）。

范围刻意比工作流 ``tool_cache`` 窄：只保存清洗后的 Provider 响应及其请求范围与
有效期，不保存 ToolExecutionEnvelope、Candidate、Selection 或 Delivery Bundle。
Redis 不可用只相当于缓存未命中，不影响工作流。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_agent.planning.research.evidence import ProviderSnapshotProvenance

from ..config.loader import get_settings
from travel_agent.integrations.provider_environment import snapshot_data_environment
from ..utils.coordinates import within_china_coordinate_box
from .redis_client import get_redis

logger = logging.getLogger(__name__)

_REDACTED = "[redacted]"
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|passport|"
    r"id[_-]?card|phone|mobile|email|payment|credit[_-]?card|证件|身份证|护照|"
    r"手机号|邮箱|支付|银行卡)",
    re.IGNORECASE,
)
_FORBIDDEN_SNAPSHOT_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_kind",
        "selection_slot_id",
        "selected_option_id",
        "research_packet_id",
        "delivery_bundle_id",
        "workspace",
        "tool_execution_envelope",
        "audit_id",
        "sanitized_result",
        "args_digest",
        "result_summary",
    }
)
# 回答「地点身份」的工具：变动性低，且同一问题对所有人答案相同。amap 的两个 POI
# 查询与 Nominatim 同理：酒店 id、名称与地址不会频繁变化。别名序列让缓存更有价值：
# 一次 authored place 可能发起多次调用，都是已答过的问题的重复。
_IDENTITY_TOOLS = frozenset(
    {"global_place_search", "maps_text_search", "maps_search_detail"}
)
_SUPPORTED_TOOLS = _IDENTITY_TOOLS | frozenset({"global_route_search"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_snapshot_hash(snapshot: Any) -> str:
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _redact_snapshot(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY_RE.search(key):
        return _REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): _redact_snapshot(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_snapshot(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_redact_snapshot(item, key=key) for item in value]
    return copy.deepcopy(value)


def _contains_sensitive_scope_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)) or _contains_sensitive_scope_key(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_scope_key(item) for item in value)
    return False


def _contains_forbidden_snapshot_shape(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("schema_version") == "tool_execution_envelope.v1":
            return True
        for key, item in value.items():
            if str(key) in _FORBIDDEN_SNAPSHOT_KEYS:
                return True
            if _contains_forbidden_snapshot_shape(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_snapshot_shape(item) for item in value)
    return False


class ProviderSnapshotScope(BaseModel):
    """复用 Provider 事实快照所需的全部语义维度。"""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    provider_endpoint: Optional[str] = None
    query: Optional[str] = None
    date_window: Optional[str] = None
    endpoints: tuple[Any, ...] = ()
    mode: Optional[str] = None
    party: Optional[int | str] = None
    currency: Optional[str] = None
    provider_contract_version: str = Field(min_length=1)
    payload_schema_version: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    auth_boundary: str = "none"

    @field_validator("provider_name", "tool_name", "provider_contract_version", "payload_schema_version")
    @classmethod
    def _required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("provider snapshot cache scope requires non-empty identifiers")
        return normalized

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = " ".join(str(value).split()).casefold()
        return normalized or None

    @field_validator("provider_endpoint", "date_window", "mode", "currency")
    @classmethod
    def _normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = " ".join(str(value).split())
        if not normalized:
            return None
        return normalized.rstrip("/") if value is not None and str(value).startswith(("http://", "https://")) else normalized

    @field_validator("arguments")
    @classmethod
    def _normalize_material_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("provider snapshot cache arguments must be an object")
        normalized = copy.deepcopy(value)
        query = normalized.get("query")
        if query is not None:
            normalized["query"] = " ".join(str(query).split()).casefold()
        country_code = normalized.get("country_code")
        if country_code is not None:
            normalized["country_code"] = str(country_code).strip().casefold()
        aliases = normalized.get("aliases")
        if isinstance(aliases, list):
            normalized["aliases"] = [
                " ".join(str(alias).split()).casefold() for alias in aliases
            ]
        return normalized

    @model_validator(mode="after")
    def _validate_reuse_boundary(self) -> "ProviderSnapshotScope":
        if self.auth_boundary not in {"none", "server_managed"}:
            raise ValueError("auth-scoped data is not eligible for a shared provider snapshot cache")
        if _contains_sensitive_scope_key(self.arguments):
            raise ValueError("sensitive arguments cannot enter a provider snapshot cache scope")
        return self

    @property
    def cache_key_digest(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class ProviderSnapshotRecord(BaseModel):
    """清洗后的 Provider 响应及其重新验证边界。"""

    model_config = ConfigDict(extra="forbid")

    scope: ProviderSnapshotScope
    snapshot: dict[str, Any]
    observed_at: datetime
    retrieved_at: datetime
    provider_valid_until: Optional[datetime] = None
    cache_valid_until: datetime
    volatility: Literal["identity", "route", "schedule", "weather", "price", "inventory"] = "identity"
    origin: Literal["live"] = "live"
    status: str = "success"
    evidence_eligible: bool = True
    quarantined: bool = False
    fallback_from: Optional[str] = None
    fallback_to: Optional[str] = None
    content_hash: str = ""

    @model_validator(mode="after")
    def _validate_snapshot_shape_and_times(self) -> "ProviderSnapshotRecord":
        self.observed_at = _ensure_aware(self.observed_at, field_name="observed_at")
        self.retrieved_at = _ensure_aware(self.retrieved_at, field_name="retrieved_at")
        self.cache_valid_until = _ensure_aware(
            self.cache_valid_until,
            field_name="cache_valid_until",
        )
        if self.provider_valid_until is not None:
            self.provider_valid_until = _ensure_aware(
                self.provider_valid_until,
                field_name="provider_valid_until",
            )
        if self.cache_valid_until <= self.retrieved_at:
            raise ValueError("provider snapshot cache validity must follow retrieval")
        if self.provider_valid_until is not None and self.provider_valid_until < self.observed_at:
            raise ValueError("provider snapshot validity cannot predate observation")
        if self.volatility in {"price", "inventory", "weather"} and self.provider_valid_until is None:
            raise ValueError("high-volatility provider snapshots require explicit provider validity")
        if not isinstance(self.snapshot, dict) or not self.snapshot:
            raise ValueError("provider snapshot must be a non-empty object")
        if _contains_forbidden_snapshot_shape(self.snapshot):
            raise ValueError("candidate, selection, bundle, or tool envelope is not a provider snapshot")
        self.snapshot = _redact_snapshot(self.snapshot)
        computed_hash = canonical_snapshot_hash(self.snapshot)
        if self.content_hash and self.content_hash != computed_hash:
            raise ValueError("provider snapshot content hash does not match its sanitized payload")
        self.content_hash = computed_hash
        return self

    def to_provenance(
        self,
        *,
        origin: Literal["live", "provider_snapshot_cache"],
    ) -> ProviderSnapshotProvenance:
        return ProviderSnapshotProvenance(
            origin=origin,
            data_environment=snapshot_data_environment(
                self.snapshot, provider_name=self.scope.provider_name
            ),
            provider_name=self.scope.provider_name,
            tool_name=self.scope.tool_name,
            cache_key_digest=self.scope.cache_key_digest,
            content_hash=self.content_hash,
            observed_at=self.observed_at,
            retrieved_at=self.retrieved_at,
            provider_valid_until=self.provider_valid_until,
            cache_valid_until=self.cache_valid_until,
            provider_contract_version=self.scope.provider_contract_version,
            payload_schema_version=self.scope.payload_schema_version,
        )

    def trace_metadata(
        self,
        *,
        origin: Literal["live", "provider_snapshot_cache"],
        outcome: str,
    ) -> dict[str, Any]:
        """返回可安全审计的元数据，不含查询文本与 Provider 载荷。"""
        return {
            "origin": origin,
            "outcome": outcome,
            "cache_key_digest": self.scope.cache_key_digest,
            "content_hash": self.content_hash,
            "observed_at": self.observed_at.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "valid_until": (
                self.provider_valid_until.isoformat()
                if self.provider_valid_until is not None
                else None
            ),
            "cache_valid_until": self.cache_valid_until.isoformat(),
            "contract_version": self.scope.provider_contract_version,
            "payload_schema_version": self.scope.payload_schema_version,
        }


class ProviderSnapshotLookup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    outcome: Literal["hit", "miss", "expired", "unavailable", "disabled"]
    record: Optional[ProviderSnapshotRecord] = None
    provenance: Optional[ProviderSnapshotProvenance] = None


class ProviderSnapshotCache:
    """Redis 缓存；不可用时返回明确的实时未命中。"""

    def __init__(
        self,
        *,
        redis: Any = None,
        clock: Callable[[], datetime] = utc_now,
        enabled: Optional[bool] = None,
        key_prefix: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        settings = get_settings().provider_snapshot_cache
        self._redis = redis
        self._clock = clock
        self._enabled = settings.enabled if enabled is None else enabled
        self._key_prefix = key_prefix or settings.redis_key_prefix
        self._timeout_seconds = (
            settings.redis_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )

    def _now(self) -> datetime:
        return _ensure_aware(self._clock(), field_name="provider snapshot cache clock")

    def _key(self, scope: ProviderSnapshotScope) -> str:
        return f"{self._key_prefix}:{scope.cache_key_digest}"

    def _client(self) -> Any:
        return self._redis if self._redis is not None else get_redis()

    async def _delete_best_effort(self, key: str) -> None:
        try:
            await asyncio.wait_for(
                self._client().delete(key),
                timeout=max(0.01, self._timeout_seconds),
            )
        except Exception:
            return

    async def lookup(self, scope: ProviderSnapshotScope) -> ProviderSnapshotLookup:
        if not self._enabled:
            return ProviderSnapshotLookup(outcome="disabled")
        key = self._key(scope)
        try:
            raw = await asyncio.wait_for(
                self._client().get(key),
                timeout=max(0.01, self._timeout_seconds),
            )
        except Exception as exc:
            logger.info("provider snapshot cache read unavailable: %s", exc)
            return ProviderSnapshotLookup(outcome="unavailable")
        if raw is None:
            return ProviderSnapshotLookup(outcome="miss")
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw) if isinstance(raw, str) else raw
            record = ProviderSnapshotRecord.model_validate(payload)
        except Exception:
            await self._delete_best_effort(key)
            return ProviderSnapshotLookup(outcome="miss")
        if record.scope.cache_key_digest != scope.cache_key_digest:
            await self._delete_best_effort(key)
            return ProviderSnapshotLookup(outcome="miss")
        now = self._now()
        if (
            record.cache_valid_until <= now
            or (
                record.provider_valid_until is not None
                and record.provider_valid_until <= now
            )
        ):
            await self._delete_best_effort(key)
            return ProviderSnapshotLookup(outcome="expired")
        safe_record = record.model_copy(deep=True)
        return ProviderSnapshotLookup(
            outcome="hit",
            record=safe_record,
            provenance=safe_record.to_provenance(origin="provider_snapshot_cache"),
        )

    async def write(self, record: ProviderSnapshotRecord) -> bool:
        """调用方确认证据资格后才写入快照。"""
        if not self._enabled:
            return False
        if record.status != "success":
            raise ValueError("only successful provider snapshots are cacheable")
        if not record.evidence_eligible:
            raise ValueError("only evidence-eligible provider snapshots are cacheable")
        if record.quarantined:
            raise ValueError("quarantined provider snapshots are not cacheable")
        if record.fallback_from or record.fallback_to:
            raise ValueError("fallback provider snapshots are not cacheable")
        if not _provider_snapshot_has_content(record.snapshot):
            raise ValueError("empty provider snapshots are not cacheable")
        now = self._now()
        valid_until = record.cache_valid_until
        if record.provider_valid_until is not None:
            valid_until = min(valid_until, record.provider_valid_until)
        ttl_seconds = math.ceil((valid_until - now).total_seconds())
        if ttl_seconds <= 0:
            return False
        try:
            serialized = _canonical_json(record.model_dump(mode="json"))
            outcome = await asyncio.wait_for(
                self._client().set(self._key(record.scope), serialized, ex=ttl_seconds),
                timeout=max(0.01, self._timeout_seconds),
            )
            return outcome is not False
        except Exception as exc:
            logger.info("provider snapshot cache write unavailable: %s", exc)
            return False


def _provider_snapshot_has_content(snapshot: dict[str, Any]) -> bool:
    if (
        snapshot.get("success") is not True
        or snapshot.get("error")
        or snapshot.get("degradation_reason")
        or snapshot.get("fallback_from")
        or snapshot.get("fallback_to")
    ):
        return False
    for key in ("results", "routes", "data", "content"):
        value = snapshot.get(key)
        if isinstance(value, (list, dict, str)) and len(value) > 0:
            return True
    return False


def _iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _ensure_aware(value, field_name="Provider timestamp")
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return _ensure_aware(parsed, field_name="Provider timestamp")
    return None


def provider_snapshot_scope_for_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> Optional[ProviderSnapshotScope]:
    """为一个受支持的 Provider 工具构造精确的缓存范围。"""
    if tool_name not in _SUPPORTED_TOOLS or not isinstance(arguments, dict):
        return None
    if tool_name in {"maps_text_search", "maps_search_detail"}:
        # amap 仅按工具参数确定范围：请求不携带我们的 endpoint（URL 由 MCP server
        # 持有），也没有 party 或 currency。``id`` 是详情查询的全部问题；
        # ``keywords``/``city`` 是文本搜索的输入。``arguments`` 也进入摘要，因此
        # server 开始使用的新参数会导致缓存未命中，而不是返回旧结果。
        return ProviderSnapshotScope(
            provider_name="amap",
            tool_name=tool_name,
            provider_endpoint=None,
            query=arguments.get("keywords") or arguments.get("id"),
            date_window=None,
            endpoints=tuple(
                item
                for item in (arguments.get("city"), arguments.get("id"))
                if item is not None
            ),
            mode="identity",
            party=None,
            currency=None,
            provider_contract_version="amap.v3",
            payload_schema_version=f"{tool_name}.v1",
            arguments=copy.deepcopy(arguments),
            auth_boundary="server_managed",
        )
    if tool_name == "global_place_search":
        return ProviderSnapshotScope(
            provider_name="nominatim",
            tool_name=tool_name,
            provider_endpoint=get_settings().geocoding.nominatim_base_url,
            query=arguments.get("query"),
            date_window=None,
            endpoints=tuple(
                item
                for item in (
                    arguments.get("destination_place_id"),
                    arguments.get("destination_latitude"),
                    arguments.get("destination_longitude"),
                )
                if item is not None
            ),
            mode=str(arguments.get("candidate_kind") or "identity"),
            party=arguments.get("party") or arguments.get("party_size"),
            currency=arguments.get("currency"),
            provider_contract_version="nominatim.jsonv2",
            # v2：相同参数现在会产生不同的 Provider 请求——目的地坐标变成主搜索的
            # ``viewbox``。范围摘要包含这个版本串，因此所有 v1 快照会同时失效。
            #
            # v3：每条结果新增 ``destination_distance_km``，判断 worker 可选地点的
            # 层会读取它。v2 的响应没有该键，而「键缺失」表示「距离不可判定」，
            # 重放低版本响应会让该问题重新出现。这里硬切换，不读取低版本。
            payload_schema_version="global_place_search.v3",
            arguments=copy.deepcopy(arguments),
            auth_boundary="none",
        )
    # ``global_route_search`` 有两个按地理范围分工的上游（中国坐标框内为 amap，
    # 其余为 Transitous），范围必须标注实际回答的那个。读取同一个坐标判断保持
    # 单一定义；若这里写死 "transitous"，中国大陆路线记录会带上错误的 provider
    # 名称、endpoint 与合同版本。
    china_route = all(
        within_china_coordinate_box(longitude, latitude)
        for longitude, latitude in (
            (arguments.get("from_longitude"), arguments.get("from_latitude")),
            (arguments.get("to_longitude"), arguments.get("to_latitude")),
        )
        if isinstance(longitude, (int, float)) and isinstance(latitude, (int, float))
    ) and all(
        isinstance(arguments.get(key), (int, float))
        for key in ("from_longitude", "from_latitude", "to_longitude", "to_latitude")
    )
    routing = get_settings().routing
    return ProviderSnapshotScope(
        provider_name="amap" if china_route else "transitous",
        tool_name=tool_name,
        provider_endpoint=routing.amap_base_url if china_route else routing.transitous_base_url,
        query=None,
        date_window=str(arguments.get("departure_time") or "").strip() or None,
        endpoints=tuple(
            arguments.get(key)
            for key in (
                "from_name",
                "from_place_id",
                "from_latitude",
                "from_longitude",
                "to_name",
                "to_place_id",
                "to_latitude",
                "to_longitude",
            )
        ),
        mode=str(arguments.get("mode") or "").strip() or None,
        party=arguments.get("party") or arguments.get("party_size"),
        currency=arguments.get("currency"),
        provider_contract_version="amap.direction-v3" if china_route else "transitous.motis-v6",
        # v2：中国大陆路线改由 amap 回答并按不同的 Provider 结构归一化，因此在
        # 相同参数下重放 v1 响应会得到 Transitous 对一条它已无法回答的查询的答案。
        # 两个分支同时硬切换，不读取低版本。
        payload_schema_version="global_route_search.v2",
        arguments=copy.deepcopy(arguments),
        auth_boundary="none",
    )


def build_provider_snapshot_record(
    *,
    scope: ProviderSnapshotScope,
    envelope: dict[str, Any],
) -> Optional[ProviderSnapshotRecord]:
    """从 Gateway 处理后的 envelope 构建记录；不满足条件时返回 None。"""
    metadata = envelope.get("metadata") if isinstance(envelope.get("metadata"), dict) else {}
    result = envelope.get("sanitized_result")
    if (
        envelope.get("status") != "success"
        or metadata.get("evidence_allowed") is not True
        or metadata.get("quarantine_result") is True
        or envelope.get("fallback_from")
        or envelope.get("fallback_to")
        or envelope.get("degradation_reason")
        or not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("error")
        or result.get("identity_fallback_failure")
        # Provider 回答「没有找到」也是成功答案（tools/result.py:
        # ToolResultOutcome.EMPTY_SUCCESS），这类 envelope 会到达这里。它不可缓存，
        # 但也不是错误：在此拒绝，``write`` 无需为普通空结果抛异常。
        or not _provider_snapshot_has_content(result)
    ):
        return None
    provider_name = str(result.get("provider") or "").strip()
    if provider_name != scope.provider_name:
        return None
    settings = get_settings().provider_snapshot_cache
    ttl_seconds = (
        settings.place_identity_ttl_seconds
        if scope.tool_name in _IDENTITY_TOOLS
        else settings.route_ttl_seconds
    )
    retrieved_at = _iso_datetime(result.get("retrieved_at")) or _iso_datetime(
        envelope.get("retrieved_at")
    )
    observed_at = _iso_datetime(result.get("observed_at")) or retrieved_at
    if retrieved_at is None or observed_at is None:
        return None
    provider_valid_until = _iso_datetime(result.get("provider_valid_until"))
    if provider_valid_until is None:
        provider_valid_until = observed_at + timedelta(seconds=ttl_seconds)
    cache_valid_until = min(
        retrieved_at + timedelta(seconds=ttl_seconds),
        provider_valid_until,
    )
    try:
        return ProviderSnapshotRecord(
            scope=scope,
            snapshot=copy.deepcopy(result),
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            provider_valid_until=provider_valid_until,
            cache_valid_until=cache_valid_until,
            volatility="identity" if scope.tool_name in _IDENTITY_TOOLS else "route",
            origin="live",
            status="success",
            evidence_eligible=True,
            quarantined=False,
            fallback_from=None,
            fallback_to=None,
        )
    except ValueError:
        return None


_provider_snapshot_cache: Optional[ProviderSnapshotCache] = None


def get_provider_snapshot_cache() -> ProviderSnapshotCache:
    global _provider_snapshot_cache
    if _provider_snapshot_cache is None:
        _provider_snapshot_cache = ProviderSnapshotCache()
    return _provider_snapshot_cache
