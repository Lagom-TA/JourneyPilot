"""规划阶段的共享图状态。"""

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
from travel_agent.planning.requirements.natural_language import ResearchPlan
from travel_agent.planning.requirements.amendment_contracts import IntentAmendment
from travel_agent.planning.requirements.amendment_contracts import (
    IntentAmendmentRejection,
)
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
    """字典字段的 fan-in 归并器，按 ``{**a, **b}`` 后写覆盖同键。

    fan-in 顺序不表示业务上的完成先后，因此并发归并的分支不得写同一个 key。
    `research_packets`、`agent_status` 等由 Worker 独占的映射中，每个分支只写
    自己的 agent key 或带该分支轮次后缀的 key。
    """
    return {**a, **b}


def _merge_dicts_allow_clear(a: Dict, b: Dict) -> Dict:
    if not b:
        return {}
    return {**a, **b}


def _merge_lists(a: List[Any], b: List[Any]) -> List[Any]:
    """轻量 bridge 摘要的追加式列表归并器。"""
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
    if not b:
        return []
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
    """按行程和请求日期合并参考班次；空列表清除当前结果。"""
    if not b:
        return []
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
    """优先返回最新的非空控制载荷。"""
    return b or a


def _take_latest_value_allow_clear(_a: Any, b: Any) -> Any:
    """按世代整体替换的归并器，``None`` 与 ``{}`` 也参与替换。

    completion-control 字段都属于同一个 Draft 世代；若用合并，编辑后的状态会
    保留其他世代的 deadline 与 budget，因此这些字段采用单写者替换语义。
    """
    return b


def _merge_run_deadline_allow_clear(
    a: Optional[RunDeadlineSnapshot],
    b: Optional[RunDeadlineSnapshot],
) -> Optional[RunDeadlineSnapshot]:
    """归并同一世代的并行观测，时间不回退。"""
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
    - 需求阶段：current_requirements、planning_generation 与 research_plan
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
    route_decision: Dict[str, Any] = Field(default_factory=dict)

    # 理解阶段的工作记录：代理消息历史（含工具结果）、已发生的问答与当前待答问题。
    understanding_messages: List[Dict[str, Any]] = Field(default_factory=list)
    understanding_qa: List[Dict[str, Any]] = Field(default_factory=list)
    understanding_rounds: int = Field(default=0, ge=0)
    understanding_pending_questions: Optional[List[Dict[str, Any]]] = None

    current_requirements: str = ""
    planning_generation: Optional[PlanningGeneration] = None
    research_plan: Optional[ResearchPlan] = None
    research_plan_error: Optional[Dict[str, str]] = None

    trip_summary_card: Dict[str, Any] = Field(default_factory=dict)

    constraint_pack: Dict[str, Any] = Field(default_factory=dict)
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
    weather_impacts: Annotated[Dict[str, WeatherImpact], _take_latest_value_allow_clear] = Field(
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
        """拒绝混用不同 Draft 世代的 checkpoint 状态。

        校验放在共享状态边界：格式不合法的 checkpoint 不应恢复出与 Draft
        不匹配的预算。
        """
        if self.research_plan is not None and self.planning_generation is None:
            raise ValueError("研究方案需要规划版本")
        draft = self.minimum_delivery_draft
        if (self.run_budget is None) != (self.run_deadline is None):
            raise ValueError("运行预算和期限必须同时存在")
        if draft is None:
            return self
        draft_generation_matches = (
            self.planning_generation is not None
            and draft.planning_generation_id == self.planning_generation.generation_id
            and draft.run_id == self.run_id
        )

        if not draft_generation_matches:
            if draft.planning_authorized:
                raise ValueError("行程框架不属于当前规划版本")
            return self
        if self.run_deadline is not None and draft.planning_authorized:
            if self.run_deadline.draft_id != draft.draft_id:
                raise ValueError(
                    "run deadline belongs to another minimum delivery draft"
                )
            if self.run_deadline.planning_authorized_at != draft.planning_authorized_at:
                raise ValueError(
                    "run deadline authorization time differs from minimum delivery draft"
                )

        return self

    model_config = {"arbitrary_types_allowed": True}
