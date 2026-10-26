"""旅行规划产品配置的持久化。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from travel_agent.config.seeds.trip_planner import validated_trip_planner_seed
from travel_agent.planning.requirements.product_contracts import (
    TRIP_PLANNER_CONFIG_KEY,
    TripPlannerConfiguration,
)
from travel_agent.storage.database import get_db_session


class ProductConfigurationStore:
    async def ensure_seed(self) -> None:
        """配置缺失时写入种子；已有配置不覆盖。"""
        payload = validated_trip_planner_seed().model_dump(mode="json")
        async with get_db_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO product_configurations (config_key, config, created_at, updated_at)
                    VALUES (:config_key, CAST(:config AS jsonb), NOW(), NOW())
                    ON CONFLICT (config_key) DO NOTHING
                    """
                ),
                {
                    "config_key": TRIP_PLANNER_CONFIG_KEY,
                    "config": json.dumps(payload, ensure_ascii=False),
                },
            )

    async def publish_seed(self) -> None:
        """把已校验的种子显式发布到现有环境。

        与 ``ensure_seed`` 分开：应用启动时可以为空库写入初始配置，但只有发布
        命令可以替换已有产品数据。
        """
        payload = validated_trip_planner_seed().model_dump(mode="json")
        async with get_db_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO product_configurations (config_key, config, created_at, updated_at)
                    VALUES (:config_key, CAST(:config AS jsonb), NOW(), NOW())
                    ON CONFLICT (config_key) DO UPDATE
                    SET config = EXCLUDED.config, updated_at = NOW()
                    """
                ),
                {
                    "config_key": TRIP_PLANNER_CONFIG_KEY,
                    "config": json.dumps(payload, ensure_ascii=False),
                },
            )

    async def get_trip_planner(self) -> TripPlannerConfiguration:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    "SELECT config FROM product_configurations WHERE config_key = :config_key"
                ),
                {"config_key": TRIP_PLANNER_CONFIG_KEY},
            )
            row = result.mappings().first()
        if row is None:
            raise LookupError("trip_planner product configuration is not seeded")
        raw: Any = row["config"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return TripPlannerConfiguration.model_validate(raw)
