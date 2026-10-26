"""公开交付 Bundle 投影。"""

from __future__ import annotations

from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.provider_environment import ProviderEnvironmentView
from travel_agent.planning.delivery.public.itinerary import _timestamp
from travel_agent.planning.delivery.public.report import _public_map
from travel_agent.planning.delivery.public.report import _public_report
from travel_agent.planning.delivery.public.report import _public_source_index
from travel_agent.planning.delivery.public.workspace import _public_workspace
from typing import Any
from typing import Dict
from typing import Mapping


_PUBLIC_MANIFEST_KEYS = (
    "contract_version",
    "run_id",
    "generation_id",
    "bundle_id",
    "workspace_revision",
    "fact_data_revision",
    "weather_data_revision",
    "created_at",
)


def public_manifest(bundle: DeliveryBundle) -> Dict[str, Any]:
    manifest = bundle.manifest
    return {
        "contract_version": manifest.contract_version,
        "run_id": manifest.run_id,
        "generation_id": manifest.generation_id,
        "bundle_id": manifest.bundle_id,
        "workspace_revision": manifest.workspace_revision,
        "fact_data_revision": manifest.fact_data_revision,
        "weather_data_revision": manifest.weather_data_revision,
        "created_at": _timestamp(manifest.created_at),
    }


def public_event_manifest(manifest: Any) -> Dict[str, Any]:
    """把持久化事件里的 manifest 载荷收敛为公开子集。

    输入是持久化事件载荷而非类型化模型，因此只读取已知字段，忽略其余内容。
    """

    if not isinstance(manifest, Mapping):
        return {}
    return {key: manifest[key] for key in _PUBLIC_MANIFEST_KEYS if key in manifest}


def public_delivery_bundle(bundle: DeliveryBundle) -> Dict[str, Any]:
    """返回产品界面唯一允许的 DeliveryBundle 形状。

    持久化的 ``EntityLineage`` 不跨越该边界；``evidence_basis`` 用产品语言说明
    条目由研究候选支撑还是由规划器依据公开资料写入，并在此统一派生，避免
    workspace 卡片与正式报告对同一实体给出不同说法。
    """

    view = EvidenceBasisView.from_itinerary(bundle.workspace.itinerary)
    return {
        "manifest": public_manifest(bundle),
        "workspace": _public_workspace(bundle.workspace, bundle, view),
        "report_projection": _public_report(bundle.report_projection, view),
        "map_projection": _public_map(bundle.map_projection),
        "source_index": _public_source_index(bundle.source_index),
        "provider_environment": {
            "sandbox_note": ProviderEnvironmentView.from_bundle(bundle).sandbox_note
        },
    }
