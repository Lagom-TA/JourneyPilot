"""交付来源的数据环境视图。"""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.integrations.provider_environment import SANDBOX_EVIDENCE_NOTE
from travel_agent.integrations.provider_environment import _declared
from typing import Any
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from travel_agent.planning.delivery.bundle import DeliveryBundle


@dataclass(frozen=True)
class ProviderEnvironmentView:
    """一次 Run 的数据环境事实，各展示面共用同一结果。

    判定放在 Run 级而非单段交通级：对读者有意义的陈述是「本计划的部分交通证据
    来自测试环境，不要据此预订」，逐段标记不会改变读者的行动。
    """

    has_sandbox_evidence: bool

    @classmethod
    def from_bundle(cls, bundle: "DeliveryBundle") -> "ProviderEnvironmentView":
        """归约所有声明了环境的来源记录。

        ``cache_provenance`` 覆盖 provider 快照缓存命中的工具，provider 自身的
        sanitized payload 覆盖其余来源；同一次响应中两者必须一致，披露结果才不
        取决于缓存是否命中。已存储的 Bundle 必须能归约而不抛异常，环境声明义务
        由写入记录的一侧保证。
        """

        return cls(
            has_sandbox_evidence=any(
                _source_data_environment(source) == "sandbox"
                for source in bundle.fact_snapshot.source_records
            )
        )

    @property
    def sandbox_note(self) -> Optional[str]:
        """需要说明的文案；全部响应来自生产环境时返回 ``None``。"""

        return SANDBOX_EVIDENCE_NOTE if self.has_sandbox_evidence else None


def _source_data_environment(source: Any) -> Optional[str]:
    provenance = getattr(source, "cache_provenance", None)
    if provenance is not None:
        return provenance.data_environment
    return _declared(getattr(source, "snapshot", None))
