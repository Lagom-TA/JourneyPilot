"""Planning requirements constraints loading."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from travel_agent.config import get_settings
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.memory.context_builder import ContextBudget
from travel_agent.memory.memory_store import MemoryStore
from travel_agent.memory.user_profile import UserProfileMemory
from travel_agent.planning.requirements.constraints.assembly import (
    build_constraint_pack,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.local_identity import LOCAL_USER_ID

logger = logging.getLogger(__name__)


class ConstraintSourceLoader:
    """Assemble the sources consumed once by request-contract normalization."""

    def __init__(
        self,
        state: Any,
        fast_llm: Any,
        *,
        user_profile: Any = None,
        manual_memory_facts: Optional[List[Dict[str, Any]]] = None,
        manual_memory_truncated: bool = False,
        memory_facts: Optional[List[Dict[str, Any]]] = None,
        context_status: str,
        missing_source_layers: Optional[List[str]] = None,
        partial_reasons: Optional[List[str]] = None,
        precomputed_free_text_constraints: Optional[
            Dict[str, List[Dict[str, Any]]]
        ] = None,
    ) -> None:
        self.state = state
        self.fast_llm = fast_llm
        self.user_profile = user_profile
        self.manual_memory_facts = manual_memory_facts
        self.manual_memory_truncated = manual_memory_truncated
        self.memory_facts = memory_facts
        self.context_status = context_status
        self.missing_source_layers = missing_source_layers or []
        self.partial_reasons = partial_reasons or []
        self.precomputed_free_text_constraints = precomputed_free_text_constraints

    @classmethod
    def from_loaded(
        cls,
        state: Any,
        fast_llm: Any,
        *,
        user_profile: Any = None,
        manual_memory_facts: Optional[List[Dict[str, Any]]] = None,
        manual_memory_truncated: bool = False,
        memory_facts: Optional[List[Dict[str, Any]]] = None,
        missing_source_layers: Optional[List[str]] = None,
        partial_reasons: Optional[List[str]] = None,
        precomputed_free_text_constraints: Optional[
            Dict[str, List[Dict[str, Any]]]
        ] = None,
    ) -> "ConstraintSourceLoader":
        missing = list(missing_source_layers or [])
        if user_profile is None and "manual_profile" not in missing:
            missing.append("manual_profile")
        if manual_memory_facts is None and "manual_memory" not in missing:
            missing.append("manual_memory")
        if memory_facts is None and "memory_fact" not in missing:
            missing.append("memory_fact")
        status = "complete" if not missing else "partial"
        return cls(
            state,
            fast_llm,
            user_profile=user_profile,
            manual_memory_facts=manual_memory_facts,
            manual_memory_truncated=manual_memory_truncated,
            memory_facts=memory_facts,
            context_status=status,
            missing_source_layers=missing,
            partial_reasons=partial_reasons or [],
            precomputed_free_text_constraints=precomputed_free_text_constraints,
        )

    async def build_pack(self) -> Dict[str, Any]:
        return await build_constraint_pack(
            self.state,
            self.fast_llm,
            user_profile=self.user_profile,
            manual_memory_facts=self.manual_memory_facts,
            manual_memory_truncated=self.manual_memory_truncated,
            memory_facts=self.memory_facts,
            context_status=self.context_status,
            missing_source_layers=self.missing_source_layers,
            partial_reasons=self.partial_reasons,
            precomputed_free_text_constraints=self.precomputed_free_text_constraints,
        )


_GENERIC_CONSTRAINT_QUERY = "出行约束 偏好 预算 过敏 行动 儿童 交通 住宿 节奏"


@dataclass(frozen=True)
class LoadedConstraintSources:
    user_profile: Any
    manual_memory_facts: Optional[List[Dict[str, Any]]]
    manual_memory_truncated: bool
    memory_facts: Optional[List[Dict[str, Any]]]
    missing_layers: List[str]
    partial_reasons: List[str]


def _memory_fact_query(state: TravelAgentState) -> str:
    """本轮真实行程意图 + 约束类词，作为记忆事实的检索词。"""

    terms: List[str] = []
    identity = state.controlled_trip_identity or {}
    if isinstance(identity, dict):
        for destination in identity.get("destinations") or []:
            if isinstance(destination, dict):
                name = str(destination.get("name") or "").strip()
                if name:
                    terms.append(name)
        origin = identity.get("origin")
        if isinstance(origin, dict):
            origin_name = str(origin.get("name") or "").strip()
            if origin_name:
                terms.append(origin_name)
        style = identity.get("style")
        if isinstance(style, dict):
            primary = str(style.get("primary") or "").strip()
            if primary:
                terms.append(primary)
            terms.extend(
                str(interest).strip()
                for interest in style.get("secondary_interests") or []
                if str(interest).strip()
            )
    unique_terms = list(dict.fromkeys(term for term in terms if term))
    if not unique_terms:
        return _GENERIC_CONSTRAINT_QUERY
    return " ".join(unique_terms) + " " + _GENERIC_CONSTRAINT_QUERY


async def load_constraint_sources(state: TravelAgentState) -> LoadedConstraintSources:
    user_profile = None
    manual_memory_facts = None
    manual_memory_truncated = False
    memory_facts = None
    missing_layers: List[str] = []
    partial_reasons: List[str] = []

    user_id = state.user_id or LOCAL_USER_ID
    try:
        user_profile = await UserProfileMemory().get_user_profile(user_id)
        if user_profile is None:
            missing_layers.extend(["manual_profile", "auto_portrait"])
    except Exception as exc:
        logger.warning("ConstraintNormalizer: user profile unavailable: %s", exc)
        missing_layers.extend(["manual_profile", "auto_portrait"])
        partial_reasons.append("user_profile_load_failed")

    try:
        manual_memory_cap = ContextBudget().manual_memory_facts_limit
        probed = await MemoryStore().list_manual_facts(
            user_id,
            limit=manual_memory_cap + 1,
        )
        manual_memory_truncated = len(probed) > manual_memory_cap
        manual_memory_facts = probed[:manual_memory_cap]
    except Exception as exc:
        logger.warning("ConstraintNormalizer: manual memories unavailable: %s", exc)
        missing_layers.append("manual_memory")
        partial_reasons.append("manual_memory_list_failed")

    if get_settings().embedding.enabled:
        try:
            memory_facts = await MemoryStore().search_facts(
                user_id,
                _memory_fact_query(state),
                top_k=8,
            )
        except Exception as exc:
            logger.warning("ConstraintNormalizer: memory facts unavailable: %s", exc)
            missing_layers.append("memory_fact")
            partial_reasons.append("memory_fact_search_failed")
    else:
        memory_facts = []

    if manual_memory_facts and memory_facts is not None:
        carried = {
            str(fact.get("fact_id"))
            for fact in manual_memory_facts
            if isinstance(fact, dict) and fact.get("fact_id") is not None
        }
        memory_facts = [
            fact
            for fact in memory_facts
            if not (isinstance(fact, dict) and str(fact.get("fact_id")) in carried)
        ]

    return LoadedConstraintSources(
        user_profile=user_profile,
        manual_memory_facts=manual_memory_facts,
        manual_memory_truncated=manual_memory_truncated,
        memory_facts=memory_facts,
        missing_layers=list(dict.fromkeys(missing_layers)),
        partial_reasons=partial_reasons,
    )


async def build_run_constraint_pack(
    state: TravelAgentState,
    *,
    loaded: Optional[LoadedConstraintSources] = None,
    precomputed_free_text_constraints: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """本轮 Constraint Pack 的**唯一装配处**，深度与快问快答两条路径共用。"""
    loaded = loaded or await load_constraint_sources(state)

    loader = ConstraintSourceLoader.from_loaded(
        state,
        llm_for_task(get_model_router(), TaskKind.INTENT_NORMALIZE),
        user_profile=loaded.user_profile,
        manual_memory_facts=loaded.manual_memory_facts,
        manual_memory_truncated=loaded.manual_memory_truncated,
        memory_facts=loaded.memory_facts,
        missing_source_layers=loaded.missing_layers,
        partial_reasons=loaded.partial_reasons,
        precomputed_free_text_constraints=precomputed_free_text_constraints,
    )
    return await loader.build_pack()
