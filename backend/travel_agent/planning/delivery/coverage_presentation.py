"""Planning delivery coverage presentation."""

from __future__ import annotations

from travel_agent.planning.delivery.bundle import RunCoverageDisclosure
from travel_agent.planning.research.domains import ResearchDomain
from typing import List


_DOMAIN_NAMES = {
    ResearchDomain.VISIT: "景点与体验",
    ResearchDomain.DINING: "餐饮",
    ResearchDomain.LODGING: "住宿",
    ResearchDomain.LOCAL_TRANSPORT: "市内交通",
    ResearchDomain.LONG_DISTANCE_TRANSPORT: "长途交通",
}


def coverage_disclosure_notes(disclosure: RunCoverageDisclosure) -> List[str]:
    """One short sentence per domain that came back with nothing usable."""

    return [
        f"本次规划在{_DOMAIN_NAMES[domain]}上未取得可用结果，方案中相关条目相应减少。"
        for domain in disclosure.domains_without_results
        if domain in _DOMAIN_NAMES
    ]
