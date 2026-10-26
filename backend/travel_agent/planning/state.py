"""Planning state."""

from __future__ import annotations

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator
from travel_agent.conversation.contracts import TaskType
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.projections import MapProjection
from travel_agent.planning.delivery.projections import SourceIndexProjection
from travel_agent.planning.delivery.projections import TripReportProjection
from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.mutation_contracts import CompositionMutation
from travel_agent.planning.outcomes import DeliveryFailureRecord
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.requirements.inputs import MinimumDeliveryDraft
from travel_agent.planning.requirements.intent_contracts import IntentSpec
from travel_agent.planning.requirements.request_contracts import IntentAmendment
from travel_agent.planning.requirements.request_contracts import (
    IntentAmendmentRejection,
)
from travel_agent.planning.requirements.request_contracts import RequestContract
from travel_agent.planning.research.brief_contracts import ResearchBriefV2
from travel_agent.planning.research.capability_contracts import CapabilityPlan
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.evidence import FieldProvenance
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
from travel_agent.planning.research.provider_outcomes import (
    merge_provider_evidence_outcomes,
)
from travel_agent.planning.research.query_contracts import ResearchQueryPlan
from travel_agent.planning.research.reference_service_contracts import (
    ProviderReferenceService,
)
from travel_agent.planning.weather.geography_contracts import DestinationGeoPoint
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherImpact
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.runtime.budget import RunBudgetSnapshot
from travel_agent.runtime.deadlines import RunDeadlineSnapshot
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from typing import Annotated
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


def _merge_dicts(a: Dict, b: Dict) -> Dict:
    """LangGraph fan-in reducer for dict fields.

    Semantics: **last-writer-wins** via ``{**a, **b}`` (right side overwrites
    same keys). Fan-in order is not a business "later completion" clock, so
    concurrent writers must **not** share keys.

    Contract for worker-owned maps (``research_packets``, ``agent_status``,
    …): each parallel branch writes **only its agent
    key** (or a round-suffixed key owned by that branch). Same-key dual write
    is undefined and must not appear in production paths; tests document
    last-wins under both merge orders.
    """
    return {**a, **b}


def _merge_dicts_allow_clear(a: Dict, b: Dict) -> Dict:
    if not b:
        return {}
    return {**a, **b}


def _merge_lists(a: List[Any], b: List[Any]) -> List[Any]:
    """Append-only list reducer for lightweight bridge summaries."""
    return list(a or []) + list(b or [])


def _replace_amendments(
    _a: List[IntentAmendment], b: List[IntentAmendment]
) -> List[IntentAmendment]:
    merged: List[IntentAmendment] = []
    seen: set[str] = set()
    for item in list(b or []):
        amendment = IntentAmendment.model_validate(item)
        command_id = amendment.command_id
        if command_id:
            if command_id in seen:
                continue
            seen.add(command_id)
        merged.append(amendment)
    return merged


def _merge_unique_strings(a: List[str], b: List[str]) -> List[str]:
    return list(dict.fromkeys([*(a or []), *(b or [])]))


def _merge_composition_mutations(
    a: List[CompositionMutation], b: List[CompositionMutation]
) -> List[CompositionMutation]:
    merged: Dict[str, CompositionMutation] = {}
    for item in [*(a or []), *(b or [])]:
        mutation = CompositionMutation.model_validate(item)
        merged[mutation.mutation_id] = mutation
    return list(merged.values())


def _merge_amendment_rejections(
    a: List[IntentAmendmentRejection], b: List[IntentAmendmentRejection]
) -> List[IntentAmendmentRejection]:
    merged: Dict[str, IntentAmendmentRejection] = {}
    for item in [*(a or []), *(b or [])]:
        rejection = IntentAmendmentRejection.model_validate(item)
        merged[rejection.command_id] = rejection
    return list(merged.values())


def _merge_reference_services(
    a: List["ProviderReferenceService"], b: List["ProviderReferenceService"]
) -> List["ProviderReferenceService"]:
    """Keep one reference service per responsibility, latest round wins.

    A later targeted round re-answers the same leg, so appending would leave two
    sentences about one leg on the plan.  The key is the responsibility the
    reference stands in for — leg role and the date the traveller asked about —
    not the service number, which is exactly the value a second round may
    change.
    """
    merged: Dict[Any, "ProviderReferenceService"] = {}
    for item in [*(a or []), *(b or [])]:
        merged[(item.leg_role, item.requested_date)] = item
    return list(merged.values())


def _or_bool(a: bool, b: bool) -> bool:
    """布尔 OR 聚合：任一并行分支为 True 即为 True。"""
    return bool(a or b)


def _prefer_non_empty_str(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """
    字符串聚合：优先保留最新的非空字符串。
    用于并行分支同时写入错误信息时避免并发冲突。
    """
    return b or a


def _prefer_pending_choice(
    a: Optional[Dict[str, Any]],
    b: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    澄清选项聚合：
    - 仅一侧有值：返回该值
    - 双侧都有值：保留先到达的值（避免覆盖造成前端抖动）
    """
    if a and b:
        return a
    return b or a


def _prefer_latest_dict(
    a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Prefer the latest non-empty control payload."""
    return b or a


def _take_latest_value_allow_clear(_a: Any, b: Any) -> Any:
    """Whole-generation replacement reducer, including ``None`` and ``{}``.

    Completion-control values all belong to one Draft generation.  A merge
    would let an edit retain a deadline/budget from an obsolete generation, so
    these fields deliberately use single-writer replacement semantics.
    """
    return b


def _merge_run_deadline_allow_clear(
    a: Optional[RunDeadlineSnapshot],
    b: Optional[RunDeadlineSnapshot],
) -> Optional[RunDeadlineSnapshot]:
    """Merge same-generation parallel observations without rolling time back."""
    if b is None or a is None or a.draft_id != b.draft_id:
        return b
    return b.model_copy(
        update={
            "checkpointed_elapsed_seconds": max(
                a.checkpointed_elapsed_seconds,
                b.checkpointed_elapsed_seconds,
            ),
            "last_observed_at": max(a.last_observed_at, b.last_observed_at),
        }
    )


class TravelAgentState(BaseModel):
    """
    全局工作流状态（LangGraph StateGraph 使用）。

    字段分组：
    - 基础会话：messages, session_id, user_id, user_query
    - 研究主键：run_id
    - Scope 阶段：research_brief（澄清后生成的结构化简报）
    - 基础设施：前置 destination_geo / weather_context
    - 编排：execution_plan, current_plan_step, agent_assignments, next_agent
    - Worker 输出：agent_status 与强类型 Research Packet / Workspace
    - 用户交互：pending_user_choice
    - 系统：current_time, selected_mcp_servers, tool_cache 等
    """

    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    session_id: str = ""
    user_id: str = LOCAL_USER_ID
    user_query: str = ""
    run_id: str = ""

    controlled_trip_identity: Dict[str, Any] = Field(default_factory=dict)
    controlled_trip_identity_revision: int = Field(default=0, ge=0)
    route_decision: Dict[str, Any] = Field(default_factory=dict)

    request_contract: Optional[RequestContract] = None
    intent_spec: Optional[IntentSpec] = None
    intent_spec_revision: int = Field(default=0, ge=0)
    planning_generation: Optional[PlanningGeneration] = None
    research_brief: Optional[ResearchBriefV2] = None
    capability_plan: Optional[CapabilityPlan] = None
    research_query_plan: Optional[ResearchQueryPlan] = None
    previous_selected_candidate_ids: List[str] = Field(default_factory=list)

    trip_summary_card: Dict[str, Any] = Field(default_factory=dict)

    constraint_pack: Dict[str, Any] = Field(default_factory=dict)
    constraint_pack_revision: int = Field(default=0, ge=0)
    fact_data_revision: int = Field(default=0, ge=0)

    minimum_delivery_draft: Annotated[
        Optional[MinimumDeliveryDraft], _take_latest_value_allow_clear
    ] = None
    run_deadline: Annotated[
        Optional[RunDeadlineSnapshot], _merge_run_deadline_allow_clear
    ] = None

    run_budget: Annotated[
        Optional[RunBudgetSnapshot], _take_latest_value_allow_clear
    ] = None

    destination_geo: List[DestinationGeoPoint] = Field(default_factory=list)
    weather_context: Optional[WeatherContextSnapshot] = None
    weather_source_records: List[SourceRecord] = Field(default_factory=list)
    weather_fact_assertions: List[FactAssertion] = Field(default_factory=list)
    weather_field_provenance: List[FieldProvenance] = Field(default_factory=list)

    task_type: Optional[TaskType] = None
    next_agent: Optional[str] = None
    execution_plan: List[List[str]] = Field(default_factory=list)
    current_plan_step: int = 0

    agent_assignments: Dict[str, Any] = Field(default_factory=dict)

    agent_status: Annotated[Dict[str, str], _merge_dicts_allow_clear] = Field(
        default_factory=dict
    )

    research_packets: Annotated[Dict[str, ResearchPacket], _merge_dicts] = Field(
        default_factory=dict
    )
    provider_evidence_outcomes: Annotated[
        Dict[str, ProviderEvidenceOutcome],
        merge_provider_evidence_outcomes,
    ] = Field(default_factory=dict)
    recommendation_catalog: Optional[RecommendationCatalog] = None
    weather_impacts: Annotated[Dict[str, WeatherImpact], _merge_dicts] = Field(
        default_factory=dict
    )

    provider_reference_services: Annotated[
        List[ProviderReferenceService], _merge_reference_services
    ] = Field(default_factory=list)

    composition_failure_context: Optional[str] = None

    placement_skeleton: Optional[ItineraryCompositionDraft] = None
    composition_mutations: Annotated[
        List[CompositionMutation], _merge_composition_mutations
    ] = Field(default_factory=list)
    local_connector_gaps: List[LocalConnectorGap] = Field(default_factory=list)
    trip_workspace_v2: Optional[TripWorkspaceV2] = None
    fact_store_snapshot: Optional[FactStoreSnapshot] = None
    report_projection: Optional[TripReportProjection] = None
    map_projection: Optional[MapProjection] = None
    source_index_projection: Optional[SourceIndexProjection] = None
    delivery_bundle: Optional[DeliveryBundle] = None
    delivery_failure: Optional[DeliveryFailureRecord] = None
    delivery_persisted: bool = False

    retrieved_docs: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_summaries: Annotated[List[Dict[str, Any]], _merge_lists] = Field(
        default_factory=list
    )

    pending_user_choice: Annotated[Optional[Dict[str, Any]], _prefer_pending_choice] = (
        None
    )
    plan_gate_decision: Annotated[Optional[Dict[str, Any]], _prefer_latest_dict] = None
    plan_gate_revision_count: int = 0
    plan_gate_amendment: Annotated[
        Optional[IntentAmendment], _take_latest_value_allow_clear
    ] = None
    pending_intent_amendments: Annotated[List[IntentAmendment], _replace_amendments] = (
        Field(default_factory=list)
    )
    intent_amendment_resume_node: Annotated[
        Optional[str], _take_latest_value_allow_clear
    ] = None
    intent_amendment_route: Annotated[Optional[str], _take_latest_value_allow_clear] = (
        None
    )
    applied_intent_amendment_ids: Annotated[List[str], _merge_unique_strings] = Field(
        default_factory=list
    )
    rejected_intent_amendments: Annotated[
        List[IntentAmendmentRejection], _merge_amendment_rejections
    ] = Field(default_factory=list)
    prompt_versions: Annotated[Dict[str, str], _merge_dicts] = Field(
        default_factory=dict
    )
    policy_versions: Annotated[Dict[str, str], _merge_dicts] = Field(
        default_factory=dict
    )
    model_versions: Annotated[Dict[str, str], _merge_dicts] = Field(
        default_factory=dict
    )

    selected_mcp_servers: List[str] = Field(default_factory=list)

    preset_context: str = ""
    preset_pack_constraints: Dict[str, str] = Field(default_factory=dict)

    session_anchor: Optional[Dict[str, Any]] = None

    session_compressed: bool = False

    session_compacted_this_turn: Annotated[bool, _or_bool] = False

    current_time: str = ""

    tool_cache: Annotated[Dict[str, Any], _merge_dicts] = Field(default_factory=dict)

    synthesis_mode: Optional[str] = None

    is_completed: Annotated[bool, _or_bool] = False

    last_error: Annotated[Optional[str], _prefer_non_empty_str] = None

    @model_validator(mode="after")
    def validate_completion_generation(self) -> "TravelAgentState":
        """Reject checkpoint state that mixes Draft generations.

        This validation is intentionally at the shared-state boundary: a
        malformed or older checkpoint must not resume with a fresh eight-minute
        budget attached to an unrelated Draft.
        """
        if self.request_contract is not None:
            if self.intent_spec is None or self.planning_generation is None:
                raise ValueError(
                    "request contract requires intent and planning generation state"
                )
            if self.request_contract.intent_spec != self.intent_spec:
                raise ValueError(
                    "state intent specification differs from request contract"
                )
            if (
                self.request_contract.generation_id
                != self.planning_generation.generation_id
            ):
                raise ValueError("request contract and planning generation differ")
            if self.intent_spec_revision != self.intent_spec.revision:
                raise ValueError(
                    "state intent revision differs from intent specification"
                )
        if self.research_query_plan is not None:
            if self.planning_generation is None or self.intent_spec is None:
                raise ValueError(
                    "research query plan requires intent and generation state"
                )
            if (
                self.research_query_plan.generation_id
                != self.planning_generation.generation_id
                or self.research_query_plan.intent_spec_revision
                != self.intent_spec_revision
            ):
                raise ValueError(
                    "research query plan belongs to an obsolete intent generation"
                )
        if self.capability_plan is not None:
            if self.research_query_plan is None:
                raise ValueError("capability plan requires a research query plan")
            known_query_ids = set(self.research_query_plan.query_index())
            if any(
                not set(assignment.research_query_ids) <= known_query_ids
                for assignment in self.capability_plan.assignments.values()
            ):
                raise ValueError(
                    "capability assignment references an unknown research query"
                )
        draft = self.minimum_delivery_draft
        dependent_values = (
            self.run_deadline,
            self.run_budget,
        )
        if draft is None:
            if any(value is not None for value in dependent_values):
                raise ValueError("completion state requires a minimum delivery draft")
            return self
        draft_generation_matches = (
            self.planning_generation is not None
            and draft.planning_generation_id == self.planning_generation.generation_id
            and draft.controlled_trip_identity_revision
            == self.controlled_trip_identity_revision
            and draft.constraint_pack_revision == self.constraint_pack_revision
            and draft.plan_revision == self.plan_gate_revision_count
            and draft.intent_spec_revision == self.intent_spec_revision
            and self.intent_spec is not None
            and draft.intent_spec_hash == self.intent_spec.content_hash
        )

        if not draft_generation_matches:
            if draft.planning_authorized or any(
                value is not None for value in dependent_values
            ):
                raise ValueError(
                    "completion state belongs to an obsolete minimum delivery draft"
                )
            return self
        if self.run_deadline is not None:
            if not draft.planning_authorized:
                raise ValueError(
                    "run deadline requires a sealed minimum delivery draft"
                )
            if self.run_deadline.draft_id != draft.draft_id:
                raise ValueError(
                    "run deadline belongs to another minimum delivery draft"
                )
            if self.run_deadline.planning_authorized_at != draft.planning_authorized_at:
                raise ValueError(
                    "run deadline authorization time differs from minimum delivery draft"
                )

        if (self.run_budget is None) != (self.run_deadline is None):
            raise ValueError("run budget and run deadline must be sealed together")
        return self

    model_config = {"arbitrary_types_allowed": True}
