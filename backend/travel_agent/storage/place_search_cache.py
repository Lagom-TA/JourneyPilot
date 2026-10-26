"""Nominatim /search 原始响应的 Redis 缓存。"""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from travel_agent.config.loader import get_settings
from travel_agent.integrations.places.contracts import NominatimSearchObservation
from travel_agent.integrations.places.normalization import logger
from travel_agent.storage.redis_client import get_redis
from typing import Any
from typing import Dict
from typing import Optional
import asyncio
import hashlib
import json


_SEARCH_CACHE_SCHEMA_VERSION = "nominatim.search.raw.v1"


def _search_cache_digest(base_url: str, params: Dict[str, Any]) -> str:
    """一次 provider 请求的完整身份：endpoint 加全部参数。

    ``params`` 已包含归一化查询、国家过滤、数量与 accept-language，整体哈希后
    一个缓存项只服务参数完全相同的请求。
    """
    payload = json.dumps(
        {
            "schema_version": _SEARCH_CACHE_SCHEMA_VERSION,
            "base_url": base_url.rstrip("/"),
            "params": {str(key): params[key] for key in sorted(params)},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NominatimSearchCache:
    """原始 ``/search`` 响应的 Redis 复用。Redis 不可用只算未命中，不是故障。

    只保存非空的成功响应。空结果只描述某一时刻的某一种查询措辞（authored-place
    查询序列会尝试多种写法，intake 也可能收到半截输入），把「没有此地」缓存一周会
    掩盖新索引的 OSM 对象。provider 失败同样不保存：一次上游性能下降不能变成答案。
    """

    def __init__(self, *, redis: Any = None) -> None:
        self._redis = redis

    def _client(self) -> Any:
        return self._redis if self._redis is not None else get_redis()

    def _key(self, digest: str) -> str:
        return f"{get_settings().geocoding.search_cache_key_prefix}:{digest}"

    def _timeout(self) -> float:
        return max(0.01, get_settings().geocoding.search_cache_redis_timeout_seconds)

    async def get(self, digest: str) -> Optional[NominatimSearchObservation]:
        try:
            raw = await asyncio.wait_for(
                self._client().get(self._key(digest)),
                timeout=self._timeout(),
            )
        except Exception as exc:
            logger.info("nominatim search cache read unavailable: %s", exc)
            return None
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if payload.get("schema_version") != _SEARCH_CACHE_SCHEMA_VERSION:
                return None
            items = payload["items"]
            observed_at = datetime.fromisoformat(payload["observed_at"])
        except Exception:
            return None
        if (
            not isinstance(items, list)
            or not items
            or any(not isinstance(item, dict) for item in items)
            or observed_at.tzinfo is None
        ):
            return None
        return NominatimSearchObservation(
            items=[dict(item) for item in items],
            observed_at=observed_at,
            origin="cache",
        )

    async def set(self, digest: str, observation: NominatimSearchObservation) -> None:
        if not observation.items:
            return
        settings = get_settings().geocoding

        expires_at = observation.observed_at + timedelta(
            seconds=settings.search_cache_ttl_seconds
        )
        ttl_seconds = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl_seconds <= 0:
            return
        payload = json.dumps(
            {
                "schema_version": _SEARCH_CACHE_SCHEMA_VERSION,
                "observed_at": observation.observed_at.isoformat(),
                "items": observation.items,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            await asyncio.wait_for(
                self._client().set(self._key(digest), payload, ex=ttl_seconds),
                timeout=self._timeout(),
            )
        except Exception as exc:
            logger.info("nominatim search cache write unavailable: %s", exc)


_SEARCH_CACHE = NominatimSearchCache()
