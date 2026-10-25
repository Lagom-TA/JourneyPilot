"""Knowledge grounding, upstream snapshot and export diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from travel_agent.config.loader import get_settings


async def _probe_knowledge_corpus() -> Dict[str, Any]:
    """Report manifest/count disagreement without gating a service that can still answer."""

    if not get_settings().embedding.enabled:
        return {
            "enabled": False,
            "ready": False,
            "message": "向量知识库已由配置关闭",
            "collections": {},
        }

    from travel_agent.knowledge import factory_seed

    try:
        counts = await factory_seed.factory_collection_counts()
    except Exception as exc:
        return {
            "ready": False,
            "message": f"读不到 knowledge_chunks: {exc}",
            "collections": {},
        }

    manifest = factory_seed.read_manifest()
    if manifest is None:
        return {
            "ready": False,
            "message": "未提供本地出厂语料种子（data/corpus/seed/）；公开仓库默认不包含该可选数据",
            "collections": counts,
        }

    probed = factory_seed.seeded_factory_collections()
    empty = sorted(name for name in probed if counts.get(name, 0) == 0)
    unprobed_with_content = sorted(
        name for name, total in counts.items() if total > 0 and name not in probed
    )

    complaints = []
    if empty:
        complaints.append(f"出厂集合仍然是空的: {', '.join(empty)}")
    if unprobed_with_content:
        complaints.append(
            "这些出厂集合库里有货但种子没声明，接地检索不会查它们: "
            f"{', '.join(unprobed_with_content)}（重新导出种子）"
        )
    return {
        "ready": not complaints,
        "message": "ok" if not complaints else "；".join(complaints),
        "collections": counts,
        "seeded": manifest.collections,
        "probed": list(probed),
        "unprobed_with_content": unprobed_with_content,
    }


def _probe_data_snapshots(settings: Any) -> Dict[str, Any]:
    """Report the age of every committed upstream snapshot, blocking nothing."""

    from travel_agent.integrations.rail.snapshot_diagnostics import (
        station_snapshot_fingerprint_drift,
        station_snapshot_metadata,
    )
    from travel_agent.integrations.rail.snapshot_freshness import (
        station_snapshot_freshness,
    )

    freshness = station_snapshot_freshness(
        station_snapshot_metadata(),
        now=datetime.now(timezone.utc).date(),
        max_age_days=settings.data_snapshots.station_max_age_days,
    )
    try:
        drift = station_snapshot_fingerprint_drift()
    except OSError as exc:  # unreadable snapshot file
        drift = [f"站表快照不可读：{exc}"]
    return {
        "ready": True,
        "station_table": {
            "verdict": freshness.verdict,
            "criterion": freshness.criterion,
            "message": freshness.detail,
            "age_days": freshness.age_days,
            "fingerprint_drift": drift,
        },
    }


def _probe_pdf_export() -> Dict[str, Any]:
    """Missing fonts degrade export, not planning and conversation readiness."""

    from travel_agent.integrations.pdf_readiness import last_pdf_probe

    probe = last_pdf_probe()
    if probe is None:
        return {
            "ready": True,
            "available": False,
            "message": "启动时未执行 PDF 渲染预检（详见启动日志）",
        }
    return {
        "ready": True,
        "available": probe.available,
        "font": probe.font,
        "message": probe.problem or "ok",
    }
