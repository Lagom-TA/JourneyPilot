"""Typed Itinerary Planner: composition decisions only, no generic activities."""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from travel_agent.planning.itinerary.checks import validate_placement_skeleton
from travel_agent.planning.itinerary.connectors import (
    LocalConnectorGap,
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
    unfilled_connector_gaps,
)
from travel_agent.planning.itinerary.draft import (
    AUTHORED_ROUTE_CLASS_BY_MODE,
    AuthoredPlaceBase,
    AuthoredRoute,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    authored_place_key,
    authored_places,
    map_authored_places,
)
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.workspace import TripWorkspaceV2

from ...entities.candidate_selection import CandidateSelectionPlan
from ...entities.composition_rules import COMPOSITION_PROMPT_VERSION, CompositionRule
from ...entities.intent_coverage import IntentContractSnapshot
from ...entities.provider_evidence import (
    build_required_long_distance_legs,
    explicit_cross_day_return_required,
    provider_evidence_scope_id,
)
from ...entities.state import TravelAgentState, bounded_repair_context
from ...llm.router import get_model_router
from ...llm.strict_json_schema import as_strict_schema
from ...llm.task_routing import TaskKind, llm_for_task
from ...memory.agent_context import render_agent_context
from ...services.authored_place_resolution import (
    AuthoredPlaceScope,
    AuthoredPlaceToolAccess,
    authored_place_scopes,
    resolve_authored_place,
)
from ...services.candidate_selection import (
    catalog_for_candidate_selection,
    catalog_for_workspace_materialization,
    selected_candidate_capabilities,
)
from ...services.composition_rule_compiler import compile_composition_rules
from ...services.day_design import apply_day_design
from ...services.day_planning import (
    daily_planning_windows,
    default_walking_days,
    disclose_default_walking,
)
from ...services.geo_dispersion import itinerary_dispersion
from ...tools.registry import get_tool_registry
from ...utils.brief_helpers import build_assignment_context
from travel_agent.runtime.operations import ModelWindowClosed, await_model_operation
from travel_agent.runtime.deadlines import observe_run_deadline
from travel_agent.agents.utils import (
    append_recent_history,
    build_tool_context_from_state,
    execute_tool,
)
from travel_agent.planning.assignments import resolve_agent_assignment

logger = logging.getLogger(__name__)

_NODE_NAME = "itinerary_planner"


_AUTHORED_PLACE_DEFS = ("AuthoredVisitPlace", "AuthoredDiningPlace")
_SERVER_OWNED_PLACE_FIELDS = (
    "resolved_place_id",
    "resolved_address",
    "resolved_latitude",
    "resolved_longitude",
)


def selected_ids_by_kind(
    catalog: RecommendationCatalog,
    *,
    skeleton_only: bool = False,
) -> Dict[str, list[str]]:
    """List selected candidate ids per domain, ordered by descending fit."""
    candidate_index = catalog.candidate_index()
    fit_by_id: Dict[str, float] = {}
    for result in catalog.admission_results:
        if result.status != "passed" or result.candidate_id not in candidate_index:
            continue
        scores = result.fit_scores
        fit = min(scores.budget_fit, scores.weather_fit, scores.constraint_fit)
        fit_by_id[result.candidate_id] = min(fit_by_id.get(result.candidate_id, 1.0), fit)
    return {
        kind: sorted(
            (
                candidate_id
                for candidate_id in fit_by_id
                if candidate_index[candidate_id].candidate_kind == kind
                and not (
                    skeleton_only
                    and kind == "transport"
                    and isinstance(candidate_index[candidate_id], TransportCandidate)
                    and candidate_index[candidate_id].transport_class != "long_distance"
                )
            ),
            key=lambda candidate_id: (-fit_by_id[candidate_id], candidate_id),
        )
        for kind in ("visit", "dining", "transport", "lodging")
    }


def controlled_day_dates(state: TravelAgentState) -> List[date]:
    """Exactly which days the composition has to fill, read off the controlled window.

    The count and the dates are one fact, so they are read in one place.  Empty
    when the run has no window to read — then there is nothing to check a
    composition against, which is different from a composition being right.
    """
    identity = state.controlled_trip_identity or {}
    start = end = None
    if isinstance(identity, dict):
        try:
            start = date.fromisoformat(str(identity.get("start_date") or "")[:10])
            end = date.fromisoformat(str(identity.get("end_date") or "")[:10])
        except ValueError:
            start = end = None
    if (start is None or end is None or end < start) and state.weather_context is not None:
        start = state.weather_context.trip_start_date
        end = state.weather_context.trip_end_date
    if start is None or end is None or end < start:
        return []
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def itinerary_day_count(state: TravelAgentState) -> int:
    """How many days the composition has to fill, read off the controlled window."""
    return len(controlled_day_dates(state))


def _verify_day_window(
    draft: ItineraryCompositionDraft,
    state: TravelAgentState,
) -> ItineraryCompositionDraft:
    """The composition covers the controlled window exactly, or it is not this trip.

    Nothing else checked this: ``validate_placement_skeleton`` verifies the Day
    dates are *contiguous* — starting from whatever the model wrote as day one —
    and ``ItineraryCompositionDraft`` verifies ``duration_days == len(days)``.  So
    a four-day trip drafted as five days only ever surfaces when the model also
    mis-filled ``duration_days``, and a trip drafted starting on the wrong date
    surfaces not at all.  Both would ship.  Found while root-causing a run where
    one such draft cost the Run a repair round with the useless message
    「composition duration must equal day count」 — this one says the dates.
    """
    expected = controlled_day_dates(state)
    if not expected:
        return draft
    actual = [day.date for day in draft.days]
    if actual != expected:
        raise ValueError(
            "itinerary must cover the controlled window exactly: "
            f"{len(expected)} 天 {expected[0].isoformat()}..{expected[-1].isoformat()}，"
            f"当前 {len(actual)} 天 "
            f"{actual[0].isoformat() if actual else '(空)'}"
            f"..{actual[-1].isoformat() if actual else '(空)'}"
        )
    return draft


def authoring_domains(
    catalog: RecommendationCatalog,
    *,
    day_count: int,
    skeleton_only: bool = False,
) -> set[str]:
    """Allow authored places where selected supply is sparse across the trip."""
    ids_by_kind = selected_ids_by_kind(catalog, skeleton_only=skeleton_only)
    domains = {
        kind
        for kind in ("visit", "dining")
        if len(ids_by_kind[kind]) < max(day_count, 1)
    }
    if not skeleton_only and not ids_by_kind["transport"]:
        domains.add("transport")
    return domains


def _composition_response_schema(
    catalog: RecommendationCatalog | None = None,
    *,
    skeleton_only: bool = False,
    strict_wire: bool = True,
) -> Dict[str, Any]:
    """Bind each placement branch to the selected candidates of the same kind.

    A domain with an empty catalog drops its ``candidate_id`` branch and opens
    the authoring branch instead, which requires a name, an address, and a city.
    """
    schema = ItineraryCompositionDraft.model_json_schema()
    definitions = schema.get("$defs", {})

    def remove_branch(value: Any, ref: str, mapping_key: str) -> None:
        if isinstance(value, dict):
            for key in ("oneOf", "anyOf", "allOf"):
                branches = value.get(key)
                if isinstance(branches, list):
                    value[key] = [
                        branch
                        for branch in branches
                        if not (isinstance(branch, dict) and branch.get("$ref") == ref)
                    ]
            discriminator = value.get("discriminator")
            if isinstance(discriminator, dict) and isinstance(
                discriminator.get("mapping"), dict
            ):
                discriminator["mapping"].pop(mapping_key, None)
            for child in value.values():
                remove_branch(child, ref, mapping_key)
        elif isinstance(value, list):
            for child in value:
                remove_branch(child, ref, mapping_key)

    # The place-provider resolution step owns every ``resolved_*`` field; it is
    # never model input.
    for def_name in _AUTHORED_PLACE_DEFS + ("AuthoredRoute",):
        authored_schema = definitions.get(def_name)
        if not isinstance(authored_schema, dict):
            continue
        properties = authored_schema.get("properties", {})
        for field_name in _SERVER_OWNED_PLACE_FIELDS:
            properties.pop(field_name, None)
        if strict_wire:
            authored_schema["required"] = list(properties)

    ids_by_kind = (
        selected_ids_by_kind(catalog, skeleton_only=skeleton_only)
        if catalog is not None
        else None
    )
    for model_name, candidate_kind in (
        ("VisitPlacement", "visit"),
        ("DiningPlacement", "dining"),
        ("TransportPlacement", "transport"),
    ):
        placement_schema = definitions.get(model_name)
        if not isinstance(placement_schema, dict):
            continue
        if model_name == "TransportPlacement":
            placement_schema.get("properties", {}).pop("connector_gap_id", None)
        properties = placement_schema.get("properties", {})
        if candidate_kind == "transport" and skeleton_only:
            # The skeleton carries no local connectors at all.
            properties.pop("authored_route", None)
        if ids_by_kind is not None:
            selected = ids_by_kind[candidate_kind]
            may_author = "authored_place" in properties or "authored_route" in properties
            if selected:
                properties["candidate_id"] = {
                    "anyOf": [
                        {"type": "string", "enum": selected},
                        {"type": "null"},
                    ]
                }
            elif may_author:
                properties["candidate_id"] = {"type": "null"}
            else:
                remove_branch(
                    schema, f"#/$defs/{model_name}", candidate_kind
                )
                continue
        if strict_wire:
            placement_schema["required"] = list(properties)
        else:
            # The discriminator remains semantic payload even though Pydantic
            # supplies a class default.  Optional origin branches stay optional:
            # forcing both candidate_id and authored_* to appear is what makes a
            # json_object model emit one useful value plus one redundant null.
            required = set(placement_schema.get("required") or [])
            required.add("placement_kind")
            placement_schema["required"] = [
                field_name for field_name in properties if field_name in required
            ]

    if ids_by_kind is not None:
        lodging_ids = ids_by_kind["lodging"]
        schema["properties"]["lodging_candidate_ids"] = (
            {"type": "array", "items": {"type": "string", "enum": lodging_ids}}
            if lodging_ids
            else {"type": "array", "items": {"type": "string"}, "maxItems": 0}
        )
    # The same schema goes on the wire and into the prompt, so legalize once
    # here: a strict provider rejects the discriminated union outright, and a
    # lenient one reads ``anyOf`` exactly as it read ``oneOf``.  Placement kinds
    # stay selectable either way — every branch pins ``placement_kind`` to its
    # own ``const`` — and the authoritative check is still the Pydantic union in
    # ``_parse_exact_llm_composition``.
    return as_strict_schema(schema) if strict_wire else schema


def _placement_capabilities(
    catalog: RecommendationCatalog,
    *,
    skeleton_only: bool = False,
    selection_plan: CandidateSelectionPlan | None = None,
) -> list[dict[str, Any]]:
    """Expose only typed placement facts needed to compose a legal topology."""
    if selection_plan is not None:
        selected, _alternatives = selected_candidate_capabilities(
            catalog=catalog,
            selection_plan=selection_plan,
        )
        return [
            capability.model_dump(mode="json", exclude_none=True)
            for capability in selected
            if not (
                skeleton_only
                and capability.candidate_kind == "transport"
                and capability.schedule_capabilities.get("transport_class")
                != "long_distance"
            )
        ]
    candidate_index = catalog.candidate_index()
    fit_by_id: dict[str, Any] = {}
    for result in catalog.admission_results:
        if result.status != "passed" or result.selection_slot_id is not None:
            continue
        fit_by_id[result.candidate_id] = result.fit_scores
    capabilities: list[dict[str, Any]] = []
    for candidate_id in sorted(fit_by_id):
        candidate = candidate_index[candidate_id]
        if (
            skeleton_only
            and isinstance(candidate, TransportCandidate)
            and candidate.transport_class != "long_distance"
        ):
            continue
        scores = fit_by_id[candidate_id]
        item: dict[str, Any] = {
            "candidate_id": candidate_id,
            "candidate_kind": candidate.candidate_kind,
            "destination_id": candidate.destination_id,
            "budget_fit": round(scores.budget_fit, 2),
            "weather_fit": round(scores.weather_fit, 2),
            "constraint_fit": round(scores.constraint_fit, 2),
        }
        if isinstance(candidate, VisitCandidate):
            item.update(name=candidate.name, place_id=candidate.place_id)
        elif isinstance(candidate, DiningCandidate):
            item.update(
                name=candidate.branch_name,
                place_id=candidate.place_id,
                meal_types=candidate.meal_types,
            )
        elif isinstance(candidate, TransportCandidate):
            item.update(
                transport_class=candidate.transport_class,
                from_place_id=candidate.from_endpoint.place_id,
                to_place_id=candidate.to_endpoint.place_id,
                departure_date=(
                    candidate.departure_at.date().isoformat()
                    if candidate.departure_at is not None
                    else None
                ),
                arrival_date=(
                    candidate.arrival_at.date().isoformat()
                    if candidate.arrival_at is not None
                    else None
                ),
            )
        elif isinstance(candidate, LodgingCandidate):
            item.update(
                name=candidate.property_name,
                check_in_date=candidate.check_in_date.isoformat(),
                check_out_date=candidate.check_out_date.isoformat(),
            )
        capabilities.append(item)
    return capabilities


# A Pydantic failure lists every violated field; the leading entries name the
# shape of the mistake and the tail repeats it once per placement.
_COMPOSITION_FAILURE_VALIDATION_ERRORS = 3

# How many blocking delivery-quality gaps a repair prompt restates.
_COMPOSITION_REPAIR_GAP_LIMIT = 8

# What an output-ceiling truncation looks like coming back through the SDK.  The
# provider does not raise a typed error for it: the completion simply stops at the
# ceiling and the parser fails on the half-written JSON.
_OUTPUT_TRUNCATION_MARKERS = ("length limit was reached", "finish_reason=length")


def _is_output_truncation(exc: BaseException) -> bool:
    """Whether this composition failed because the completion hit its ceiling."""
    text = str(exc)
    return any(marker in text for marker in _OUTPUT_TRUNCATION_MARKERS)


def _composition_failure_detail(exc: BaseException) -> str:
    """The part of a composition failure worth replaying to the model.

    A repair round's *only* new input is this string, so it has to be something
    the model can act on.  Every other failure here already is — a day that ends
    after the traveller leaves, a dining candidate placed at a meal it does not
    serve — but an output-ceiling truncation arrives as the SDK's own token
    accounting (``Could not parse response content as the length limit was
    reached - CompletionUsage(completion_tokens=8192, prompt_tokens=81110)``).
    Replayed verbatim that tells the model **nothing about what to change**, so
    the round is spent restating a number and the next attempt is the same length.
    Measured: ``trip_de0e806baee64ddc`` spent two of its four repair rounds this
    way and then died with the budget exhausted.

    Retrying is not useless here — completion length varies run to run (78
    measured completions span 67..7103 tokens) — it is only useless while the
    instruction is missing.  So this names the one thing that fixes it, and
    deliberately names what must **not** shrink: dropping days or required
    placements to fit is a wrong itinerary, which is worse than a failed one.
    """
    if _is_output_truncation(exc):
        return (
            "OutputTruncated: 上一轮 composition 输出超出单次补全长度上限被截断，"
            "因此不是一份完整 JSON。请输出更紧凑的同一份行程：压缩 theme、"
            "selection_reason 等自由文本字段的长度，不要重复叙述。"
            "**天数、每天的必需落位与所有 candidate_id 一个都不许减** —— "
            "为了变短而删掉行程内容会产出一份错的行程。"
        )
    if isinstance(exc, ValidationError):
        detail = "；".join(
            "{path}: {message}".format(
                path=".".join(str(part) for part in error.get("loc", ())) or "(root)",
                message=str(error.get("msg", "")),
            )
            for error in exc.errors()[:_COMPOSITION_FAILURE_VALIDATION_ERRORS]
        )
    else:
        detail = str(exc)
    return f"{type(exc).__name__}: {detail}"


def _composition_repair_section(state: TravelAgentState) -> str:
    """The repair round's only new input: why the previous attempt failed.

    Empty whenever nothing failed yet, so a first composition prompt is
    unchanged.  Each writer owns its own channel: the planner's own failures,
    the Candidate Gate's verdict on the previous skeleton, and the blocking
    delivery-quality gaps all arrive separately and are restated together here.
    """
    lines: List[str] = []
    if state.composition_failure_context:
        lines.append(f"- 组合失败原因：{state.composition_failure_context}")
    if state.placement_skeleton_failure_context:
        lines.append(
            "- 候选门对上一轮 skeleton 的裁定："
            f"{state.placement_skeleton_failure_context}"
        )
    blocking = [gap for gap in state.delivery_quality_gaps if gap.blocking]
    for gap in blocking[:_COMPOSITION_REPAIR_GAP_LIMIT]:
        detail = f"{gap.gate} / {gap.reason}（{gap.field_path}）"
        locator = gap.entity_id or gap.candidate_id
        if locator:
            detail += f"，涉及 {locator}"
        lines.append(f"- 质量门阻塞项：{detail}")
    fidelity_gaps = [gap for gap in state.intent_fidelity_gaps if gap.blocking]
    for gap in fidelity_gaps[:_COMPOSITION_REPAIR_GAP_LIMIT]:
        missing_days = gap.repair_context.get("missing_days") or []
        detail = f"{gap.reason}（intent={gap.intent_id}）"
        if missing_days:
            detail += f"，缺失 Day {missing_days}"
        lines.append(f"- 意图验收阻塞项：{detail}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"""

<previous_attempt_failure>
上一轮组合失败的确切原因如下，这一轮必须修正它：
{body}
只针对上面点出的问题做最小改动：其余已经合法的候选选择、日期、顺序与当地时间保持原样，不要连带改写。
</previous_attempt_failure>"""


def _required_leg_scope_ids(
    required_legs: Optional[List[Any]],
    run_id: str,
    constraint_pack_revision: int,
) -> Dict[str, str]:
    """Map each required long-distance leg to its authoritative Provider scope id.

    The transport researcher builds one candidate per required leg and tags it
    with ``provider_evidence_scope_id`` (a deterministic hash of the leg's
    from/to/service_date/leg_role).  The placement skeleton must verify *each*
    leg is placed by that id — the date-only view lets a same-day outbound
    satisfy the return's service date and the return never reaches the itinerary
    (the same-day two-long-distance-leg case).
    """
    if not required_legs:
        return {}
    return {
        f"{leg.leg_role}@{leg.service_date.isoformat()}": provider_evidence_scope_id(
            run_id=run_id,
            constraint_pack_revision=constraint_pack_revision,
            worker_kind="transport_researcher",
            research_domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
            candidate_kind=None,
            transport_class="long_distance",
            target_identity=None,
            route_leg=leg,
        )
        for leg in required_legs
    }


def _composition_schema_json(
    state: TravelAgentState, *, skeleton_only: bool, strict_wire: bool = True
) -> str:
    """The response schema exactly as the prompt carries it."""
    return json.dumps(
        _composition_response_schema(
            state.recommendation_catalog,
            skeleton_only=skeleton_only,
            strict_wire=strict_wire,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_catalog_json(state: TravelAgentState) -> str:
    """Selected candidate facts exactly as the prompt carries them."""
    if state.candidate_selection_plan is None:
        raise ValueError("itinerary composition requires a Candidate Selection Plan")
    candidate_index = state.recommendation_catalog.candidate_index()
    candidate_ids = state.candidate_selection_plan.composition_candidate_ids()
    return json.dumps(
        {
            "generation_id": state.recommendation_catalog.generation_id,
            "intent_spec_revision": state.recommendation_catalog.intent_spec_revision,
            "candidates": [
                candidate_index[candidate_id].model_dump(mode="json", exclude_none=True)
                for candidate_id in sorted(candidate_ids)
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_capabilities_json(
    state: TravelAgentState, *, skeleton_only: bool
) -> str:
    """Placement Capabilities exactly as the prompt carries them."""
    return json.dumps(
        _placement_capabilities(
            state.recommendation_catalog,
            skeleton_only=skeleton_only,
            selection_plan=state.candidate_selection_plan,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _alternative_capabilities_json(state: TravelAgentState) -> str:
    if state.candidate_selection_plan is None:
        raise ValueError("itinerary composition requires a Candidate Selection Plan")
    _selected, alternatives = selected_candidate_capabilities(
        catalog=state.recommendation_catalog,
        selection_plan=state.candidate_selection_plan,
    )
    return json.dumps(
        [item.model_dump(mode="json", exclude_none=True) for item in alternatives],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_rules(state: TravelAgentState) -> list[CompositionRule]:
    if state.intent_spec is None:
        raise ValueError("itinerary composition requires an IntentSpec")
    return compile_composition_rules(state.intent_spec)


def _composition_rules_json(state: TravelAgentState) -> str:
    return json.dumps(
        [rule.model_dump(mode="json") for rule in _composition_rules(state)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _intent_contract_json(state: TravelAgentState) -> str:
    if state.intent_spec is None:
        raise ValueError("itinerary composition requires an IntentSpec")
    return json.dumps(
        {
            "schema_version": state.intent_spec.schema_version,
            "intent_spec_id": state.intent_spec.intent_spec_id,
            "revision": state.intent_spec.revision,
            "generation_id": state.intent_spec.generation_id,
            "content_hash": state.intent_spec.content_hash,
            "objective_summary": state.intent_spec.objective_summary,
            "active_items": [
                item.model_dump(
                    mode="json",
                    exclude={"source_text", "source_span_start", "source_span_end"},
                )
                for item in state.intent_spec.active_items
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _minimum_delivery_json(state: TravelAgentState) -> str:
    draft = state.minimum_delivery_draft
    if draft is None:
        raise ValueError("itinerary composition requires a Minimum Delivery Draft")
    return json.dumps(
        {
            "generation_id": draft.planning_generation_id,
            "intent_spec_revision": draft.intent_spec_revision,
            "constraint_pack_revision": draft.constraint_pack_revision,
            "day_shells": [item.model_dump(mode="json") for item in draft.day_shells],
            "preserved_hard_intent_ids": draft.preserved_hard_intent_ids,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _previous_mutations_json(state: TravelAgentState) -> str:
    return json.dumps(
        [
            mutation.model_dump(mode="json")
            for mutation in state.composition_mutations[-20:]
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class CompositionPrompt:
    system: str
    runtime: str


def _current_draft_context(state: TravelAgentState) -> str:
    context = {}
    if state.placement_skeleton is not None:
        context["placement_skeleton"] = state.placement_skeleton.model_dump(mode="json")
    if state.trip_workspace_v2 is not None:
        itinerary = state.trip_workspace_v2.itinerary
        entries = {
            entity.item_id: entity.model_dump(mode="json", include={
                "item_id", "day_id", "place_id", "name", "meal_type", "note",
                "planned_start", "planned_end", "duration_minutes", "selection_reason",
            })
            for entity in [*itinerary.visit_stops, *itinerary.dining_stops,
                           *itinerary.custom_blocks]
        }
        entries.update({
            leg.transport_leg_id: leg.model_dump(mode="json", include={
                "transport_leg_id", "transport_class", "selected_mode", "from_endpoint",
                "to_endpoint", "departure_at", "arrival_at", "duration_minutes",
            })
            for leg in itinerary.transport_legs
        })
        entries.update({
            stay.stay_id: stay.model_dump(mode="json", include={
                "stay_id", "place_id", "name", "check_in_date", "check_out_date",
            })
            for stay in itinerary.lodging_stays
        })
        context["workspace_days"] = [
            {"day_id": day.day_id, "date": day.date.isoformat(),
             "destination_id": day.destination_id,
             "timeline": [entries[ref.entity_id] for ref in day.timeline
                          if ref.entity_id in entries]}
            for day in itinerary.day_plans
        ]
    return json.dumps(context, ensure_ascii=False)


def _build_composition_prompt(
    state: TravelAgentState,
    task_desc: str,
    *,
    skeleton_only: bool = False,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list] = None,
    strict_wire_schema: bool = True,
) -> CompositionPrompt:
    """Assemble the composition prompt.

    There is no ``Weather Context`` line in ``<context>`` any more.  This
    prompt used to render ``WeatherContext.model_dump_json()`` there *and* then
    get ``format_weather_context_for_planning``'s block appended by
    ``inject_agent_context`` — the same day records twice, 36% of the prompt
    measured, paid on every call and every repair round.  The injected block is
    the survivor, so the hard contract points at 【规划前天气事实】 by name.  The
    line it used to point at, "已有 Weather Impact", named a field that is empty
    in all 200 measured runs — ``WeatherContext.impacts`` is never populated; the
    impacts live in ``state.weather_impacts`` and reach the composer as
    ``weather_fit`` on Placement Capabilities.
    """
    if state.recommendation_catalog is None:
        raise ValueError("itinerary composition requires an admitted Recommendation Catalog")
    schema = _composition_schema_json(
        state,
        skeleton_only=skeleton_only,
        strict_wire=strict_wire_schema,
    )
    catalog = _composition_catalog_json(state)
    capabilities = _composition_capabilities_json(state, skeleton_only=skeleton_only)
    alternatives = _alternative_capabilities_json(state)
    rules = _composition_rules_json(state)
    intent_contract = _intent_contract_json(state)
    minimum_delivery = _minimum_delivery_json(state)
    previous_mutations = _previous_mutations_json(state)
    _, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, _NODE_NAME
    )
    brief = build_assignment_context(
        assignment=assignment,
        brief=state.research_brief,
        intent_spec=state.intent_spec,
        constraint_pack=state.constraint_pack,
    )
    transport_contract = (
        "- 这是 placement skeleton 阶段：禁止引用任何 public_transit 或 flexible candidate，"
        "只确定 Visit/Dining 的 Day、顺序、当地时间以及日期匹配的 long_distance 主方案。"
        "相邻实体之间暂时不插入路线，后续只从这个顺序确定性提取 connector gaps。"
        if skeleton_only
        else "- 同一 Day 内相邻两个 Visit/Dining placement 之间必须插入一个 Transport placement："
        "这一对端点上只要有已准入的 public_transit / flexible 候选，就**必须**引用那个候选——"
        "它是 Provider 实测的线路、时长与票价，你写的是估计值，估计值不得顶替实测值。"
        "只有这一对端点上没有任何已选主方案时，才用 authored_route 写出出行方式与门到门分钟数"
        "（端点由服务器按前后两个停留点自动填写）。候选只给时长不给时刻表是正常的——"
        "中国大陆的公交地铁按时长作答，时长本身就是这段路的事实。"
        "authored_route 的端点来自它前后紧邻的两个停留点，所以它只能作为这一段相邻关系里"
        "的唯一一条路线：同一段相邻关系内不得再放第二条 Transport placement，也不得把 "
        "authored_route 放在 Day 开头、Day 结尾或 long_distance 旁边这类没有前后两个停留点的位置。"
        "long_distance 只能作为远距离锚点，不能冒充市内连接，也不得输出没有连接段的路线。"
    )
    repair_section = _composition_repair_section(state)
    authoring_kinds = authoring_domains(
        state.recommendation_catalog,
        day_count=itinerary_day_count(state),
        skeleton_only=skeleton_only,
    )
    authoring_contract = ""
    if authoring_kinds:
        kind_labels = "、".join(sorted(authoring_kinds))
        authoring_contract = (
            f"\n- 下列领域的已选主方案不足以覆盖整份行程，缺口由你直接撰写具名条目补足：{kind_labels}。"
            "优先使用其中符合当天区域、兴趣与可用时间的已选主方案；除用户必去义务外，"
            "不要求全部用上，不得为了用完候选而牺牲节奏。撰写条目仅补真实体验缺口。"
            "撰写条目必须是真实存在、可被地图检索到的地点，"
            "并同时给出 local_name、name、address（街道级地址）、city（所在城市），"
            "以及一句 selection_reason 说明为什么放在这一天这个时段。"
            "local_name 写这家店/这个景点门口招牌上的当地语言原名，逐字照写、不加译名不加拼音；"
            "name 写给旅行者看的常用名称。"
            "地点库是按当地语言原名收录的，local_name 写对与否直接决定这个条目能不能落地，"
            "所以字形必须与当地实际书写一致：中国大陆写简体，不写繁体或异体；"
            "日本写日文汉字与假名，按招牌上的假名写法，不改写成中文汉字也不换用别的假名拼法；"
            "韩国写韩文，泰国写泰文。"
            "服务器会逐个核对坐标，查不到的地点会被退回要求你换一个；"
            "所以只写你确信真实存在的地点，不要写泛指区域、连锁品牌统称或臆造门店。"
            "价格、营业时间、评分这类实时字段一律留空，不要编造。"
        )
    required_kinds_contract = ""
    if required_candidate_kinds:
        kind_labels = "、".join(sorted(required_candidate_kinds))
        required_kinds_contract = (
            f"\n- 整份行程必须为下列每一种物理类型各放置至少一个已选主方案：{kind_labels}。"
            "“每个 Day 至少含一个 Visit/Dining”指的是“非空”，绝不等于可以整份省略某一类型；"
            "只要 required 类型含 dining，就必须至少出现一个 DiningCandidate（用户明确要求美食），"
            "同理 visit 也必须至少出现一个。宁可减少同日停留点，也不得整类缺席。"
        )
    system = f"""<role>
你是 JourneyPilot 的旅行规划师。先设计每一天的区域、核心体验、取舍与节奏，再决定已选主方案的日期、顺序、当地时间与停留时长；事实不足的条目不能编造营业、预约或价格。
</role>

<daily_design>
- 每个Day填写day_design：focus用一行说当天主要区域和体验；rationale说明为什么这样走、怎样适合用户、取舍了什么。说明只能引用实际placements里的地点；不写候选ID、责任锚点、准入、合同等内部词。
- 按已选候选坐标/区域把邻近体验放在同一天，餐馆顺路嵌入，住宿作为每日出入基地；优先有价值的核心体验，不按候选顺序或分数简单填满。用户明确文化专题时允许多个不同主题场馆；一般慢游不能因下雨就机械全部变为同类馆。
- 根据Daily Planning Windows的可用时段和固定交通安排首尾日；这些是默认规划假设，用户时段、真实路线和预约优先。预留进出站/机场、行李、用餐、步行与休息，交通窗口必须足够容纳真实门到门路线。
- 长途抵达后，先预留下车出站时间（飞机45分钟，其他长途15分钟，均为规划假设），再加真实市内接驳时长；不能把到站时刻直接当成开始市内接驳的时刻。
- 主动休息填写day_design.free_time，仅给出带时区的起止时间；系统将其明确定位在上一站所在区域。必须在已完成的Visit/Dining之后、离开该站的交通之前，不能与活动或交通重叠。返回酒店、取行李、跨区移动不能算作free_time；需在实际路线中安排。rationale里的休息地点也必须与此一致，不能假定可在店内长坐或退房后使用客房。无主动留白时输出空数组。
- 非美食专题的可用游玩日应有符合兴趣的核心体验；不能只安排一顿饭便视为一整天已规划。较长空白应说明具体用途和时段，慢游留白不等于漏项，也不必为填时间强加景点。
- 不为迎合模板压缩核心游览时长。行程太满时删可选项或换近处候选，保留用户必去、固定订单和已核验开放条件。用餐时间应合理且与店家营业事实一致。
- 除用户明确另有饮食作息外，先为午餐留出当地11:30–13:30之间的开始时间，再排其他可选活动。不要为了塞进第二个景点把午餐推到14点以后；必要时把景点移到午餐后或删去。
- rationale必须逐项对照placements和真实路线：只有实际经过酒店的交通才可写“回酒店取行李”。退房后默认随身携带行李，寄存条件未知时列为待确认，不能凭空插入取行李旅程。当天无酒店中途停靠的路线，不得在说明中暗示已安排。
- 每个Visit/Dining placement填写selection_reason，解释它在实际当天时段、顺序和区域中的作用。候选调研理由只是备选推荐，不要原样复制其中“第一站”“午后”等与最终排程冲突的说法；不要用“消磨时间”替代具体体验价值。
</daily_design>

<hard_contract>
- 只输出一个可直接 json.loads 的 ItineraryCompositionDraft JSON 对象；禁止 Markdown、解释、旧通用信封或 activities[]。
- 引用候选时只能引用 CandidateSelectionPlan 选入主方案、且由 JSON Schema 对当前 placement_kind 开放的 candidate_id：visit 只能选 VisitCandidate，dining 只能选 DiningCandidate，transport 只能选 TransportCandidate，lodging_candidate_ids 只能选 LodgingCandidate；禁止跨类型引用，也禁止复制或改写 candidate 的名称、价格、来源、交通 segments、营业事实或天气事实。
- Composition Rules 是本轮可执行意图合同。never_violate 规则不得违反；repair_then_deviate 规则无法落实时留给 Fidelity Gate 形成明确偏差；nonblocking_preference 只参与选择和排程，不得伪装成硬事实。
- Placement Capabilities 给出每个候选的 budget_fit / weather_fit / constraint_fit（0–1）。同一领域内优先选择分值高的候选；weather_fit 低的户外项排到天气更好的一天，budget_fit 低的项让位给分值更高的同类。
- 主方案直接适应【规划前天气事实】里的逐日 data_kind、降水概率与风力：forecast 日的恶劣条件必须反映在排序、时间或交通选择上。
- 本轮必须覆盖的领域、允许撰写的不足领域与精确 candidate_id 合同见最新 composition_runtime；禁止扩大授权领域。
- 每个 Dining placement 必须选择具体门店并填写餐次；每个需要住宿的入住区间必须在 lodging_candidate_ids 选择具体 property。
- 同一 Day 内每个条目（candidate 或撰写地点）只出现一次；同一个具体 Visit/Dining 在整份行程中也只能出现一次；同一个入住区间在 lodging_candidate_ids 也只选一家 property。候选不够时撰写新的具名地点，不得跨日重复门店或景点凑数。
- 每个 Day 的 placements 必须非空。除已准入 long_distance 构成的真实 travel-only day 外，每个 Day 必须至少包含一个在整份行程中唯一的 Visit/Dining；先给每个 Day 分配一个唯一条目，再考虑给某天增加第二个停留点。不得把多个实体挤在前几天后再跨日复制其中一个填满剩余天。
- **带长途锚点的 Day 允许同时安排 Visit/Dining**，条件是这些停留点必须给出 planned_start 与 planned_end，并且**全部落在锚点的同一侧**。长途锚点不是一段「忙碌时间」，它把旅行者从一座城市搬到另一座：出发前他在出发城市，抵达后他才在这个 Day 的目的地。所以只有一侧可能安排本地停留，另一侧他根本不在这座城市——
  - **抵达日**（锚点把旅行者送到这个 Day 的目的地，含跨夜锚点落在其 arrival 日期的那一天）：锚点必须写成这个 Day 的**第一个** placement，所有停留点排在它后面，且每个 planned_start 都不早于锚点的 arrival_at。
  - **离开日**（锚点把旅行者带离这个 Day 的目的地，含跨夜锚点落在其 departure 日期的那一天）：锚点必须写成这个 Day 的**最后一个** placement，所有停留点排在它前面，且每个 planned_end 都不晚于锚点的 departure_at。
  - placements 的书写顺序就是服务器读取锚点方向的依据，写反了会被当成反方向的锚点，并据此向反方向的端点索取一段市内接驳（例如把抵达高铁写在停留点之后，服务器就会去要一段「深圳的餐厅 → 上海虹桥」的市内路线）。顺序与方向必须一致。
  **锚点与停留点之间要留出符合路线时长的通行窗口及上下车缓冲**——从站台到景点、从餐厅回车站都是真实路程，需要这段时间才能排出接驳。当整份行程的每一天都被长途锚点占据（最典型的是两天往返）时，**必须**用这个办法把 required kinds 安排进去——此时不存在没有锚点的空闲 Day，把所有天都做成 travel-only 会导致 required kinds 无处安放、整份组合被拒。
- Catalog 中存在已准入 long_distance 时，每一段**必需移动**（出发、逐对 inter_destination、返程）各选择一个主方案即可；"每个 service window 只选一个主方案" 指的是**同一段必需移动的同方向备选互斥**，不禁止同一天既到达又离开（例如 1 天同日往返，或末日既要交接又要返程）。若是后者那种同一天同时欠「到达腿」与「离开腿」的日子：**必须把到达腿放这一天第一个 placement、离开腿放这一天最后一个 placement**，所有 Visit/Dining 停留在两腿**之间**（planned_start 不早于到达腿 arrival_at、planned_end 不晚于离开腿 departure_at，且留足符合路线时长的通行窗口及上下车缓冲），不得只放一段而漏另一段。长途锚点只能放在 Placement Capabilities 给出的 departure_date 或 arrival_date 对应 Day；行程还有不带锚点的 Day 时它可以单独构成 travel-only Day。禁止把同日备选航班分配到其它日期凑行程，也禁止为了同日追加停留点而把端点不一致的市内路线硬接到长距离锚点。
{transport_contract}
- 不生成第二份晴雨行程；局部 Plan B 由后续 typed contingency 合同处理。
- Visit/Dining 必须同时输出 planned_start 与 planned_end 两个键：有排期时两者都是带 IANA 对应 UTC offset、且落在 DayComposition.date 当地日期内的 ISO-8601 datetime；不排具体时间时两者都为 null，禁止只输出一端。
- 同一 Day 内已排期的 Visit/Dining 必须按时间先后书写。不同地点之间预留符合路线实际时长的通行窗口；允许短而可行的转场，不统一套用固定时长，不得重叠或由服务器平移日程。
</hard_contract>"""
    runtime = f"""<composition_runtime>
<task_contract>{authoring_contract}{required_kinds_contract}</task_contract>
<context>
组合提示版本：{COMPOSITION_PROMPT_VERSION}
任务：{task_desc}
Intent Contract Snapshot：{intent_contract}
Composition Rules：{rules}
Minimum Delivery Day Shell：{minimum_delivery}
Daily Planning Windows（默认假设，非实测交通）：{json.dumps(daily_planning_windows(state, state.recommendation_catalog, state.candidate_selection_plan), ensure_ascii=False)}
Previous Composition Mutations：{previous_mutations}
Current Daily Draft：{_current_draft_context(state)}
Required Long-distance Legs：{json.dumps([leg.model_dump(mode='json') for leg in required_long_distance_legs or []], ensure_ascii=False)}
{brief}
Selected Candidate Facts：{catalog}
Selected Candidate Capabilities：{capabilities}
Alternative Candidate Capabilities（只供修复路由判断，不得直接放入本轮行程）：{alternatives}
</context>{repair_section}

<json_schema>{schema}</json_schema>
{render_agent_context(state, _NODE_NAME)}
</composition_runtime>"""
    return CompositionPrompt(system, runtime)


def _composition_prompt(state, task_desc, **kwargs) -> str:
    """Legacy diagnostic rendering; production preserves message boundaries."""
    prompt = _build_composition_prompt(state, task_desc, **kwargs)
    return prompt.system + "\n\n" + prompt.runtime


# An authored place must resolve to a real map location before it can enter the
# itinerary.  When the provider has no match the planner is asked for a
# different named place once, and the composition fails after that. The
# resolution ladder itself is what raises the hit rate; a second model round
# costs more wall clock than it recovers entries.
_AUTHORED_PLACE_REPLACEMENT_ROUNDS = 1

# One entry's whole resolution ladder. A place every provider knows answers in a
# few seconds; a place none of them knows costs a full-bbox scan per alias, and
# the composition window has other entries to place.
_AUTHORED_ENTRY_BUDGET_SECONDS = 20.0

# The tools the authored-place ladder's CN rung calls, and therefore the whole
# allowlist the gateway enforces on this deterministic path.
_AUTHORED_PLACE_TOOL_NAMES = frozenset({"maps_text_search", "maps_search_detail"})


class _AuthoredEntryBudgetSpent(RuntimeError):
    """One entry's resolution ladder ran its full slice and found nothing.

    Distinct from :class:`ModelWindowClosed`: the run still has window left, so
    this entry is disproved while the ones after it keep their own slice.  A
    bare ``asyncio.TimeoutError`` cannot carry that difference — the window
    guard turns any timeout inside the awaitable into a closed window.
    """


# Separators an authored name can gain or lose between attempts without naming
# a different place: spacing, the katakana middle dot, hyphen variants.
_NAME_SEPARATORS = str.maketrans({ch: "" for ch in " \t　・·‧•‐-–—_/"})


def _name_key(value: str) -> str:
    """Match key for one authored name, tolerant of how it was typed.

    NFKC folds the full-width and half-width forms of the same characters
    together; dropping separators and case covers the rest of the respellings
    that still ask for the place the ladder already searched for.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text.translate(_NAME_SEPARATORS).casefold()


def _names_disproved(name: str, local_name: str, disproved: set[str]) -> bool:
    """Whether either name of an entry is one this run already disproved."""
    if not disproved:
        return False
    keys = {_name_key(value) for value in (name, local_name) if str(value or "").strip()}
    return bool(keys & {_name_key(value) for value in disproved})


def _place_names(place: AuthoredPlaceBase) -> set[str]:
    return {
        str(value)
        for value in (place.name, place.local_name)
        if str(value or "").strip()
    }


def _composition_window_closed(state: TravelAgentState) -> bool:
    if state.run_deadline is None:
        return False
    _observed, observation = observe_run_deadline(state.run_deadline)
    return observation.composition_closed


def _authored_place_tool_access(state: TravelAgentState) -> AuthoredPlaceToolAccess:
    """Bind the authored-place ladder to this run's audited tool gateway.

    The ladder resolves an authored entry's identity against a live provider, and
    that provider answer is what makes an authored identity more trustworthy than
    a candidate's own claim. So its calls travel the same chokepoint as every
    other tool call in the run — ``execute_tool``, which applies the gateway
    allowlist, the provider snapshot cache and the research-window boundary, and
    persists the durable ``tool_execution_audits`` row.

    The allowlist is the ladder's own two tools rather than this node's
    model-facing tool policy: that policy denies the composer's LLM every tool,
    and this path has no model in the loop. ``allow_fallback=False`` for the same
    reason a deterministic binder sets it — a web-search substitute must never
    stand in for a provider identity.
    """
    tool_context = build_tool_context_from_state(state)

    async def execute(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_tool(
            tool_name,
            arguments,
            allowed_tool_names=_AUTHORED_PLACE_TOOL_NAMES,
            node_name=_NODE_NAME,
            activation_source="authored_place_resolution",
            allow_fallback=False,
            **tool_context,
        )

    def has_tool(tool_name: str) -> bool:
        # Whether this deployment registered the tool at all. The gateway decides
        # whether this path may call it; the registry is the only thing that knows
        # whether it exists to be called.
        return get_tool_registry().has_tool(tool_name)

    return AuthoredPlaceToolAccess(execute=execute, has_tool=has_tool)


async def _locate_authored_places(
    composition: ItineraryCompositionDraft,
    scopes: Dict[str, AuthoredPlaceScope],
    unlocatable: set[str],
    tools: AuthoredPlaceToolAccess,
) -> tuple[ItineraryCompositionDraft, list[AuthoredPlaceBase]]:
    """Fill the resolved identity of every authored place a provider knows.

    ``unlocatable`` carries the names earlier attempts disproved and grows with
    the ones this pass disproves. Only a ladder that actually ran counts: an
    entry the composition window cut short was never searched for, so it stays
    open for the next attempt.
    """
    pending = [ref for ref in authored_places(composition) if not ref.place.is_located]
    if not pending:
        return composition, []
    located: Dict[str, AuthoredPlaceBase] = {}
    unresolved: List[AuthoredPlaceBase] = []
    for index, ref in enumerate(pending):
        place = ref.place
        key = authored_place_key(place)
        if key in located:
            continue
        if _names_disproved(place.name, place.local_name, unlocatable):
            logger.info(
                "authored place already disproved this run name=%s", place.name
            )
            unresolved.append(place)
            continue
        try:
            # The ladder walks several provider phrasings per entry, and an entry
            # no provider knows pays for every one of them. Each entry gets a
            # slice rather than the rest of the composition window, so one
            # unknown place cannot spend the budget the other entries need.
            async def _resolve_within_budget(
                place: AuthoredPlaceBase = place,
                kind: str = ref.kind,
                scope: AuthoredPlaceScope = scopes.get(
                    ref.destination_id, AuthoredPlaceScope()
                ),
            ) -> Optional[Dict[str, Any]]:
                try:
                    return await asyncio.wait_for(
                        resolve_authored_place(
                            name=place.name,
                            local_name=place.local_name,
                            city=place.city,
                            address=place.address,
                            kind=kind,
                            scope=scope,
                            tools=tools,
                        ),
                        timeout=_AUTHORED_ENTRY_BUDGET_SECONDS,
                    )
                except asyncio.TimeoutError as spent:
                    raise _AuthoredEntryBudgetSpent(place.name) from spent

            resolved = await await_model_operation(
                _resolve_within_budget(),
                operation="place.resolve_authored",
            )
        except _AuthoredEntryBudgetSpent:
            # The ladder had its full slice and produced nothing; a place every
            # provider knows answers in a few seconds.
            logger.warning(
                "authored place resolution budget spent name=%s", place.name
            )
            unlocatable |= _place_names(place)
            unresolved.append(place)
            continue
        except ModelWindowClosed as closed:
            # The window, not this entry, is what ran out; the rest go unresolved
            # so the itinerary still ships the entries that did resolve.
            logger.warning(
                "%s window closed at elapsed=%.1fs with %s authored entries unresolved",
                closed.window,
                closed.observation.elapsed_seconds,
                len(pending) - index,
            )
            unresolved.extend(item.place for item in pending[index:])
            break
        if resolved is None:
            unlocatable |= _place_names(place)
            unresolved.append(place)
            continue
        located[key] = place.model_copy(
            update={
                "resolved_place_id": resolved["place_id"],
                "resolved_address": resolved["address"],
                "resolved_latitude": resolved["latitude"],
                "resolved_longitude": resolved["longitude"],
            }
        )
    if located:
        composition = map_authored_places(
            composition,
            lambda place: _reuse_place_location(
                place, located.get(authored_place_key(place)),
            ),
        )
    return composition, unresolved


def _replacement_place_schema(original_names: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "replacements": {
                "type": "array",
                "minItems": len(original_names),
                "maxItems": len(original_names),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "original_name": {"type": "string", "enum": original_names},
                        "name": {"type": "string", "minLength": 1},
                        "local_name": {"type": "string", "minLength": 1},
                        "address": {"type": "string", "minLength": 1},
                        "city": {"type": "string", "minLength": 1},
                        "selection_reason": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "original_name",
                        "name",
                        "local_name",
                        "address",
                        "city",
                        "selection_reason",
                    ],
                },
            }
        },
        "required": ["replacements"],
    }


async def _request_replacement_places(
    llm: Any,
    unresolved: List[AuthoredPlaceBase],
    unlocatable: set[str],
) -> Dict[str, Dict[str, str]]:
    """Ask for one different named place per entry the map could not find.

    A replacement that names something already disproved is discarded here, so
    a round that only respells the dead entry costs no resolution budget.
    """
    originals = [
        {
            "name": place.name,
            "local_name": place.local_name,
            "city": place.city,
            "address": place.address,
        }
        for place in unresolved
    ]
    original_names = [place.name for place in unresolved]
    # Names an earlier composition attempt already disproved. Naming them keeps
    # the round from spending itself rediscovering the same dead entries.
    pending_keys = {
        _name_key(value) for place in unresolved for value in _place_names(place)
    }
    already_disproved = sorted(
        value for value in unlocatable if _name_key(value) not in pending_keys
    )
    exclusion = (
        f"\n本次运行已确认检索不到、禁止再次使用的名称："
        f"{json.dumps(already_disproved, ensure_ascii=False)}"
        if already_disproved
        else ""
    )
    response = await llm.ainvoke(
        [
            {
                "role": "system",
                "content": (
                    "你是 JourneyPilot 的行程组合器。下列地点在地点库中检索不到，"
                    "为每一个换一个同城、同类型、真实存在且能在地图上检索到的地点。"
                    "换的必须是另一个地点：改写法、换假名拼法、换繁简字形、加减分店后缀"
                    "都算同一个地点，一律不接受。"
                    "只返回替换项：local_name 逐字写当地语言的招牌原名（地点库按它收录，"
                    "字形与当地实际书写一致：中国大陆写简体，日本按招牌上的假名写法），"
                    "name 写旅行者读的常用名称，address 写街道级地址，city 保持同城，"
                    "selection_reason 一句话说明适配理由。不要解释，不要返回完整行程。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"检索不到的地点：{json.dumps(originals, ensure_ascii=False)}"
                    f"{exclusion}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "authored_place_replacements",
                "strict": True,
                "schema": _replacement_place_schema(original_names),
            },
        },
        temperature=0,
    )
    content = response.content if hasattr(response, "content") else response
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    payload = json.loads(content)
    items = payload.get("replacements") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("place replacement must return one replacements list")
    by_original: Dict[str, Dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original_name") or "")
        name = str(item.get("name") or "")
        if not original or not name:
            continue
        local_name = str(item.get("local_name") or name)
        if _names_disproved(name, local_name, unlocatable):
            logger.info(
                "discarding replacement that renames a disproved place name=%s",
                name,
            )
            continue
        by_original[original] = {
            "name": name,
            "local_name": local_name,
            "address": str(item.get("address") or ""),
            "city": str(item.get("city") or ""),
            "selection_reason": str(item.get("selection_reason") or ""),
        }
    return by_original


class AuthoredPlaceLocationError(ItineraryCompositionError):
    def __init__(self, message: str, composition: ItineraryCompositionDraft):
        super().__init__(message)
        self.composition = composition


def _reuse_place_location(place, located):
    if located is None:
        return place
    return place.model_copy(update={
        field: getattr(located, field) for field in _SERVER_OWNED_PLACE_FIELDS
    })


async def locate_authored_composition(
    composition: ItineraryCompositionDraft,
    llm: Any,
    state: TravelAgentState,
    unlocatable: set[str],
) -> ItineraryCompositionDraft:
    """Return a composition whose every authored entry has a map location.

    ``unlocatable`` is the run's growing record of names no provider knows; the
    caller carries it into the state update so a composition repair attempt
    starts from what this one proved.
    """
    scopes = authored_place_scopes(state.controlled_trip_identity)
    tools = _authored_place_tool_access(state)
    composition, unresolved = await _locate_authored_places(
        composition, scopes, unlocatable, tools
    )
    for _round in range(_AUTHORED_PLACE_REPLACEMENT_ROUNDS):
        if not unresolved:
            break
        if _composition_window_closed(state):
            # Past the boundary a replacement round would spend the model call
            # that composition repair still needs.
            break
        replacements = await _request_replacement_places(llm, unresolved, unlocatable)
        by_key = {
            authored_place_key(place): replacements[place.name]
            for place in unresolved
            if place.name in replacements
        }
        if not by_key:
            break
        composition = map_authored_places(
            composition,
            lambda place: (
                place.model_copy(update=by_key[authored_place_key(place)])
                if authored_place_key(place) in by_key
                else place
            ),
        )
        composition, unresolved = await _locate_authored_places(
            composition, scopes, unlocatable, tools
        )
    if unresolved:
        raise AuthoredPlaceLocationError(
            "authored places could not be located; revise these entries without deleting other content: "
            + "; ".join(f"{place.name} ({place.local_name}, {place.city}, {place.address})" for place in unresolved),
            composition,
        )
    return composition


def _authored_connector_schema(gap_ids: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "connectors": {
                "type": "array",
                "minItems": len(gap_ids),
                "maxItems": len(gap_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "gap_id": {"type": "string", "enum": gap_ids},
                        "mode": {
                            "type": "string",
                            "enum": sorted(AUTHORED_ROUTE_CLASS_BY_MODE),
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 360,
                        },
                        "selection_reason": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "gap_id",
                        "mode",
                        "duration_minutes",
                        "selection_reason",
                    ],
                },
            }
        },
        "required": ["connectors"],
    }


async def _author_connector_routes(
    llm: Any,
    gaps: List[LocalConnectorGap],
) -> Dict[str, AuthoredRoute]:
    """Write one door-to-door connector per adjacency with no Provider route."""
    gap_ids = [gap.gap_id for gap in gaps]
    described = [
        {
            "gap_id": gap.gap_id,
            "day_date": gap.day_date.isoformat(),
            "from_place_id": gap.from_place_id,
            "to_place_id": gap.to_place_id,
            "from_endpoint": gap.from_endpoint.model_dump(mode="json") if gap.from_endpoint else None,
            "to_endpoint": gap.to_endpoint.model_dump(mode="json") if gap.to_endpoint else None,
            "leave_after": gap.departure_time.isoformat(),
            "arrive_before": gap.latest_arrival_time.isoformat(),
            "requested_modes": [] if gap.compare_default_walk else gap.requested_flexible_modes,
            "forbidden_modes": ["walk"] if gap.compare_default_walk else [],
        }
        for gap in gaps
    ]
    schema = _authored_connector_schema(gap_ids)
    # Do not expose a comparison-only walk request as authorization to invent a
    # walking route. Enforce this per gap even in mixed explicit-mode batches.
    item_schema = schema["properties"]["connectors"]["items"]
    variants = []
    for gap in gaps:
        variant = json.loads(json.dumps(item_schema))
        variant["properties"]["gap_id"]["enum"] = [gap.gap_id]
        if gap.compare_default_walk:
            variant["properties"]["mode"]["enum"] = [
                mode for mode in variant["properties"]["mode"]["enum"] if mode != "walk"
            ]
        variants.append(variant)
    schema["properties"]["connectors"]["items"] = {"anyOf": variants}
    response = await llm.ainvoke(
        [
            {
                "role": "system",
                "content": (
                    "你是 JourneyPilot 的行程组合器。为下列相邻停留点之间各写一段市内交通："
                    "选一个出行方式，并给出门到门分钟数与一句选择理由。"
                    "根据真实端点名称和位置信息估算合理门到门耗时，不得为了装进时间窗压缩分钟数。"
                    "若合理耗时超过时间窗，仍返回真实估算，由草稿修订调整安排。"
                    "必须遵守每段forbidden_modes；步行比较没有实测结果时不能猜测步行。"
                    "端点由服务器按前后两个停留点填写，你不要写地点、线路号或票价。"
                ),
            },
            {
                "role": "user",
                "content": f"待补的相邻段：{json.dumps(described, ensure_ascii=False)}",
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "authored_local_connectors",
                "strict": True,
                "schema": schema,
            },
        },
        temperature=0,
    )
    content = response.content if hasattr(response, "content") else response
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    payload = json.loads(content)
    items = payload.get("connectors") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("connector authoring must return one connectors list")
    routes: Dict[str, AuthoredRoute] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        gap_id = str(item.get("gap_id") or "")
        if gap_id not in gap_ids or gap_id in routes:
            continue
        routes[gap_id] = AuthoredRoute(
            mode=item.get("mode"),
            duration_minutes=int(item.get("duration_minutes") or 0),
            selection_reason=str(item.get("selection_reason") or ""),
        )
    missing = [gap_id for gap_id in gap_ids if gap_id not in routes]
    if missing:
        raise ValueError(f"connector authoring skipped adjacencies: {missing}")
    return routes


def _parse_exact_llm_composition(
    raw: str,
    state: TravelAgentState,
) -> ItineraryCompositionDraft:
    payload = json.loads(raw)
    if isinstance(payload, dict):
        for day in payload.get("days", []) or []:
            if not isinstance(day, dict):
                continue
            for placement in day.get("placements", []) or []:
                if not isinstance(placement, dict):
                    continue
                place = placement.get("authored_place")
                if isinstance(place, dict):
                    for field in _SERVER_OWNED_PLACE_FIELDS:
                        place.pop(field, None)
    return _verify_day_window(parse_itinerary_composition(json.dumps(payload)), state)


def _log_composition_dispersion(workspace: TripWorkspaceV2) -> None:
    """Print how spread out each Day is: local connector minutes, and stop span.

    Measurement only.  Nothing here filters a candidate, moves a stop or fails a
    Day — "how far is too far" is a threshold nobody can pick before the
    distribution exists, and this line is what makes every run contribute to it.

    It belongs to the ``Composition …`` family above (``grep "Composition "``
    collects all of them) but cannot be *emitted* up there: the placement
    skeleton carries no local connectors at all — they are materialized one pass
    later — so half the measurement does not exist yet.  Which stop sits on
    which Day, which is what the span measures, is settled by the backfill above
    and left untouched by connector materialization, so the span printed here is
    the span of the composition those two lines describe.

    Coordinates come from the two layers that own them, the same pair the map
    the traveller sees is drawn from: an authored entry carries its resolved
    point on the stop, a candidate-backed stop carries verified coordinate facts
    in its lineage.  ``pts=`` reports how many of the Day's stops resolved, so a
    span computed over fewer points than the Day has cannot read as a full one.
    """
    fact_index = {
        fact.fact_assertion_id: fact
        for packet in workspace.recommendation_catalog.research_packets
        for fact in packet.fact_assertions
    }
    measured = []
    for day_id, dispersion in itinerary_dispersion(workspace.itinerary, fact_index):
        legs = f"{dispersion.local_leg_minutes}min/{dispersion.local_leg_count}legs"
        if dispersion.untimed_local_leg_count:
            legs += f"(+{dispersion.untimed_local_leg_count} untimed)"
        if dispersion.span_km is None:
            span = "span=n/a"
        else:
            pair = dispersion.farthest_pair or ("", "")
            span = f"span={dispersion.span_km:.2f}km[{pair[0]}↔{pair[1]}]"
        measured.append(
            f"{day_id}:local={legs} {span} "
            f"pts={dispersion.located_point_count}/{dispersion.point_count}"
        )
    logger.info("Composition dispersion: %s", " | ".join(measured))


def _restore_full_catalog(
    workspace: TripWorkspaceV2,
    full_catalog: RecommendationCatalog | None,
) -> TripWorkspaceV2:
    if full_catalog is None:
        return workspace
    admissions = {
        (result.candidate_id, result.selection_slot_id): result
        for result in full_catalog.admission_results
    }
    admissions.update(
        {
            (result.candidate_id, result.selection_slot_id): result
            for result in workspace.recommendation_catalog.admission_results
            if result.selection_slot_id is not None
        }
    )
    restored_catalog = full_catalog.model_copy(
        update={"admission_results": list(admissions.values())}
    )
    return workspace.model_copy(
        update={"recommendation_catalog": restored_catalog}
    )


def _draft_user_input_anchors(state: TravelAgentState) -> List[UserInputAnchor]:
    """Carry the Draft's controlled anchors into the composed Workspace.

    The report projection resolves every itinerary destination id to its public
    name through these anchors, and the cost summary reads the budget cap from
    them.  Both are authored once in the minimum delivery draft.
    """
    draft = state.minimum_delivery_draft
    if draft is None:
        return []
    return list(draft.user_input_anchors)


def _composition_phase(state: TravelAgentState) -> str:
    if (
        state.placement_skeleton is None
        or state.trip_workspace_v2 is not None
        or state.composition_failure_context
        or state.placement_skeleton_failure_context
    ):
        return "placement_skeleton"
    return "materialize_connectors"


def _reuse_located_places(
    draft: ItineraryCompositionDraft,
    previous: Optional[ItineraryCompositionDraft],
) -> ItineraryCompositionDraft:
    if previous is None:
        return draft
    located = {
        (ref.destination_id, ref.kind, ref.place.name, ref.place.local_name,
         ref.place.address, ref.place.city): ref.place
        for ref in authored_places(previous)
        if ref.place.is_located
    }
    days = []
    for day in draft.days:
        placements = []
        for placement in day.placements:
            if placement.placement_kind in {"visit", "dining"} and placement.authored_place:
                place = placement.authored_place
                key = (day.destination_id, placement.placement_kind, place.name,
                       place.local_name, place.address, place.city)
                original = located.get(key)
                if original is not None:
                    placement = placement.model_copy(update={
                        "authored_place": _reuse_place_location(place, original),
                    })
            placements.append(placement)
        days.append(day.model_copy(update={"placements": placements}))
    return draft.model_copy(update={"days": days})


async def _compose_draft(
    state: TravelAgentState,
    task_desc: str,
    llm: Any,
    required_candidate_kinds: set[str],
    required_legs: list,
    unlocatable: set[str],
) -> ItineraryCompositionDraft:
    native_schema = bool(
        getattr(getattr(llm, "capabilities", None), "supports_json_schema", False)
    )
    prompt = _build_composition_prompt(
        state, task_desc, skeleton_only=True,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_legs,
        strict_wire_schema=native_schema,
    )
    messages = [{"role": "system", "content": prompt.system}]
    append_recent_history(messages, state, limit=4)
    messages.append({"role": "user", "content": prompt.runtime})
    kwargs = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "itinerary_composition_draft", "strict": native_schema,
                "schema": _composition_response_schema(
                    state.recommendation_catalog, skeleton_only=True,
                    strict_wire=native_schema,
                ),
            },
        },
        "temperature": 0,
    }
    previous = state.placement_skeleton
    for attempt in range(2):
        response = await llm.ainvoke(messages, **kwargs)
        content = response.content if hasattr(response, "content") else response
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        draft = None
        try:
            draft = _reuse_located_places(_parse_exact_llm_composition(content, state), previous)
            draft = await locate_authored_composition(draft, llm, state, unlocatable)
            previous = draft
            validate_placement_skeleton(
                draft, state.recommendation_catalog,
                required_candidate_kinds=required_candidate_kinds,
                required_long_distance_legs=required_legs,
                required_leg_scope_ids=_required_leg_scope_ids(
                    required_legs, state.run_id, state.constraint_pack_revision,
                ),
            )
            requests, required_pairs = connector_mode_requests_from_constraint_pack(
                draft, state.constraint_pack, state.recommendation_catalog,
            )
            extract_local_connector_gaps(
                draft, state.recommendation_catalog,
                weather_data_revision=state.recommendation_catalog.weather_data_revision,
                flexible_mode_requests=requests, required_flexible_mode_pairs=required_pairs,
                default_walk_day_ids=default_walking_days(state, draft),
                required_candidate_kinds=required_candidate_kinds,
            )
            return draft
        except ValueError as exc:
            draft = getattr(exc, "composition", None) or draft
            if draft is not None:
                previous = draft
            if attempt:
                exc.composition = previous
                raise
            messages.extend([
                {"role": "assistant", "content": (
                    draft.model_dump_json() if draft is not None else content
                )},
                {"role": "user", "content": (
                    "修订以上完整草稿，只解决以下具体问题并保留未受影响的地点、活动、餐次、休息与固定长途。"
                    "仍返回不含市内交通的完整草稿，不得由服务器删除或机械移动内容。"
                    f"具体问题：{exc}"
                )},
            ])
    raise AssertionError("composition attempt budget exhausted")


async def itinerary_planner_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    full_catalog = state.recommendation_catalog
    if full_catalog is not None:
        if state.candidate_selection_plan is None:
            raise ValueError("itinerary composition requires a Candidate Selection Plan")
        state = state.model_copy(update={
            "recommendation_catalog": catalog_for_candidate_selection(
                full_catalog, state.candidate_selection_plan,
            ),
        })
    output_key, assignment = resolve_agent_assignment(state.agent_assignments or {}, _NODE_NAME)
    phase = _composition_phase(state)
    stage = phase
    unlocatable = set(state.unlocatable_authored_places)
    required_kinds = {
        str(kind) for kind in assignment.get("required_candidate_kinds", [])
        if str(kind) in {"visit", "dining"}
    }
    required_legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(state.user_query or ""),
    )
    deadline_update = {}
    try:
        if state.run_deadline is not None:
            observed, observation = observe_run_deadline(state.run_deadline)
            deadline_update["run_deadline"] = observed
            if observation.phase == "expired":
                raise ValueError("delivery deadline elapsed before itinerary composition")
        if state.recommendation_catalog is None:
            raise ValueError("composition requires an admitted Recommendation Catalog")
        if phase == "placement_skeleton":
            draft = await _compose_draft(
                state, str(assignment["objective"]),
                llm_for_task(get_model_router(), TaskKind.COMPOSITION),
                required_kinds, required_legs, unlocatable,
            )
            from ...services.state_invalidation import workspace_acceptance_invalidation

            return {
                **deadline_update,
                **workspace_acceptance_invalidation(),
                "messages": [AIMessage(content="完整行程草稿已完成，接着核对相邻路线")],
                "agent_status": {output_key: "pending"},
                "placement_skeleton": draft,
                "trip_workspace_v2": None,
                "local_connector_gaps": [],
                "candidate_gate_status": "needs_research",
                "candidate_gate_route": "candidate_gate",
                "unlocatable_authored_places": sorted(unlocatable),
                "composition_failure_context": None,
                "placement_skeleton_failure_context": None,
            }
        if state.candidate_gate_status != "passed":
            raise ValueError("connector materialization requires a passed Gate")
        skeleton = state.placement_skeleton
        requests, required_pairs = connector_mode_requests_from_constraint_pack(
            skeleton, state.constraint_pack, state.recommendation_catalog,
        )
        gaps = extract_local_connector_gaps(
            skeleton, state.recommendation_catalog,
            weather_data_revision=state.recommendation_catalog.weather_data_revision,
            flexible_mode_requests=requests, required_flexible_mode_pairs=required_pairs,
            default_walk_day_ids=default_walking_days(state, skeleton),
            required_candidate_kinds=required_kinds,
        )
        unfilled = unfilled_connector_gaps(state.recommendation_catalog, gaps)
        authored = await _author_connector_routes(
            llm_for_task(get_model_router(), TaskKind.COMPOSITION), unfilled,
        ) if unfilled else {}
        composition = materialize_skeleton_connectors(
            skeleton, state.recommendation_catalog, gaps, authored,
            required_candidate_kinds=required_kinds,
            required_long_distance_legs=required_legs,
            required_leg_scope_ids=_required_leg_scope_ids(
                required_legs, state.run_id, state.constraint_pack_revision,
            ),
        )
        stage = "materialize_connectors/workspace_materialization"
        workspace = materialize_trip_workspace(
            run_id=state.run_id, workspace_revision=0, composition=composition,
            catalog=catalog_for_workspace_materialization(full_catalog, state.candidate_selection_plan),
            intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(state.intent_spec),
            candidate_selection_plan=state.candidate_selection_plan,
            composition_mutations=list(state.composition_mutations),
            user_input_anchors=_draft_user_input_anchors(state),
            reference_services=list(state.provider_reference_services),
            required_candidate_kinds=required_kinds,
            required_long_distance_legs=required_legs,
            required_leg_scope_ids=_required_leg_scope_ids(
                required_legs, state.run_id, state.constraint_pack_revision,
            ),
        )
        workspace = _restore_full_catalog(workspace, full_catalog)
        workspace = apply_day_design(workspace, composition)
        workspace = disclose_default_walking(workspace, gaps)
        _log_composition_dispersion(workspace)
        return {
            **deadline_update,
            "messages": [AIMessage(content="精确相邻路线已物化为正式行程")],
            "agent_status": {output_key: "completed"},
            "trip_workspace_v2": workspace,
            "recommendation_catalog": workspace.recommendation_catalog,
            "local_connector_gaps": gaps,
            "unlocatable_authored_places": sorted(unlocatable),
            "composition_failure_context": None,
            "placement_skeleton_failure_context": None,
        }
    except Exception as exc:
        logger.error("ItineraryPlanner v2 failed: %s", exc, exc_info=True)
        return {
            **deadline_update,
            "messages": [AIMessage(content="行程草稿需要修订")],
            "last_error": str(exc),
            "agent_status": {output_key: "failed"},
            "unlocatable_authored_places": sorted(unlocatable),
            "composition_failure_context": bounded_repair_context(stage, _composition_failure_detail(exc)),
            **({"placement_skeleton": exc.composition}
               if getattr(exc, "composition", None) is not None else {}),
        }
