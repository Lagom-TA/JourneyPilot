"""系统产品配置的显式发布，只在发布流程中使用。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from travel_agent.config.seeds.travel_presets import validated_system_preset_seeds
from travel_agent.config.seeds.trip_planner import validated_trip_planner_seed
from travel_agent.planning.requirements.product_contracts import TRIP_PLANNER_CONFIG_KEY
from travel_agent.storage.preset_store import PresetStore
from travel_agent.storage.product_configuration_store import ProductConfigurationStore

from ..storage.maintenance.report import require_database_contract


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_publication_summary() -> Dict[str, Any]:
    """校验发布数据并返回稳定、可核对的发布摘要。"""
    trip_planner = validated_trip_planner_seed().model_dump(mode="json")
    system_presets = [
        preset.model_dump(mode="json", exclude_unset=True)
        for preset in validated_system_preset_seeds()
    ]
    return {
        "trip_planner": {
            "config_key": TRIP_PLANNER_CONFIG_KEY,
            "digest": _digest(trip_planner),
        },
        "system_presets": {
            "count": len(system_presets),
            "ids": [preset["id"] for preset in system_presets],
            "digest": _digest(system_presets),
        },
    }


async def publish_seed() -> Dict[str, Any]:
    """校验并显式替换数据库中由发布流程管理的产品数据。

    发布只写入行，不创建表。数据库尚未迁移时直接拒绝并给出修复命令，而不是在
    第一次 INSERT 时中途失败。
    """
    summary = build_publication_summary()
    await require_database_contract()
    await ProductConfigurationStore().publish_seed()
    await PresetStore().publish_system_presets()
    return summary
