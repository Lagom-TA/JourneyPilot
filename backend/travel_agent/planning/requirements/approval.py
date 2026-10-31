"""计划审批。"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from travel_agent.config.loader import get_settings
from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft
from travel_agent.planning.invalidation import invalidation_update
from travel_agent.planning.nodes import (
    NODE_DISPATCHER,
    NODE_INTENT_AMENDMENT_ROUTER,
    NODE_PLAN_GATE,
    NODE_REQUEST_CONTRACT_NORMALIZER,
    NODE_RESEARCH_PLAN_GENERATOR,
)
from travel_agent.planning.presentation import get_agent_display_name
from travel_agent.planning.requirements.amendments import classify_amendment
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.clarification_questions import (
    necessary_requirement_questions,
    next_exclusion_key,
)
from travel_agent.planning.requirements.request_contracts import (
    AmendmentImpact,
    ClauseDisposition,
    IntentAmendment,
    RequestContract,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled

logger = logging.getLogger(__name__)


_MAX_PLAN_GATE_REVISIONS = 1
_PLAN_GATE_APPROVAL_TOKEN_VERSION = "plan_gate.approval.v1"
_MAX_PLAN_GATE_FALLBACK_RETRIES = 1
_MAX_RESEARCH_PLAN_RETRIES = 2
_PLAN_DOMAIN_LABELS = {
    "visit": "景点与体验",
    "dining": "餐饮",
    "lodging": "住宿",
    "local_transport": "市内交通",
    "long_distance_transport": "跨城交通",
}


def _contract_hash(value: Any) -> Optional[str]:
    content_hash = getattr(value, "content_hash", None)
    return str(content_hash) if content_hash else None


def _plan_gate_approval_material(
    state: TravelAgentState, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Token 绑定的服务端事实：Run、revision、合同/计划哈希与公开计划正文。"""
    material = {
        "schema_version": _PLAN_GATE_APPROVAL_TOKEN_VERSION,
        "run_id": str(getattr(state, "run_id", "") or ""),
        "revision": int(getattr(state, "plan_gate_revision_count", 0) or 0),
        "research_plan_retry_count": int(getattr(state, "research_plan_retry_count", 0) or 0),
        "request_contract_hash": _contract_hash(
            getattr(state, "request_contract", None)
        ),
        "research_brief_hash": _contract_hash(
            getattr(state, "research_brief", None)
        ),
        "research_query_plan_hash": _contract_hash(
            getattr(state, "research_query_plan", None)
        ),
        "capability_plan_hash": _contract_hash(
            getattr(state, "capability_plan", None)
        ),
        "plan": payload.get("plan"),
        "plan_text": payload.get("plan_text"),
        "recognized_requirements": payload.get("recognized_requirements"),
    }
    receipt_hash = getattr(getattr(state, "semantic_receipt", None), "receipt_hash", None)
    if receipt_hash:
        material["semantic_receipt_hash"] = str(receipt_hash)
    if payload.get("phase") == "semantics":
        material["semantic_challenge"] = {
            "challenge_id": payload.get("challenge_id"),
            "revision": payload.get("revision"),
            "assertions": payload.get("assertions"),
        }
    return material


def _plan_gate_approval_token(
    state: TravelAgentState, payload: Dict[str, Any]
) -> str:
    digest = canonical_json_hash(_plan_gate_approval_material(state, payload))
    return f"{_PLAN_GATE_APPROVAL_TOKEN_VERSION}:{digest}"


def _decision_has_current_gate_version(
    decision: Dict[str, Any], payload: Dict[str, Any]
) -> bool:
    supplied = str(decision.get("approval_token") or "").strip()
    expected = str(payload.get("approval_token") or "").strip()
    try:
        return bool(
            supplied
            and expected
            and hmac.compare_digest(
                supplied.encode("utf-8"), expected.encode("utf-8")
            )
        )
    except UnicodeEncodeError:
        return False


def _plan_source(state: TravelAgentState) -> str:
    brief = getattr(state, "research_brief", None)
    source = str(getattr(brief, "research_plan_source", "") or "").strip()
    return source if source in {"model", "deterministic_fallback", "unrecorded"} else "unrecorded"


def _research_plan_retry_available(state: TravelAgentState) -> bool:
    return int(getattr(state, "research_plan_retry_count", 0) or 0) < _MAX_RESEARCH_PLAN_RETRIES


def _retry_available(state: TravelAgentState, revision: int) -> bool:
    """普通修改额度用完后，只有模型计划缺失或历史来源未记录时再给一次重试。"""

    if revision < _MAX_PLAN_GATE_REVISIONS:
        return True
    return (
        _plan_source(state) in {"deterministic_fallback", "unrecorded"}
        and revision <= _MAX_PLAN_GATE_REVISIONS + _MAX_PLAN_GATE_FALLBACK_RETRIES - 1
    )


def _research_scope_rows(state: TravelAgentState) -> List[Dict[str, Any]]:
    brief = getattr(state, "research_brief", None)
    if brief is None or _plan_source(state) != "model":
        return []
    rows: List[Dict[str, Any]] = []
    for objective in getattr(brief, "domain_objectives", []) or []:
        terms = [str(term) for term in getattr(objective, "search_terms", []) or []]
        if not terms:
            continue
        domain = str(getattr(objective.domain, "value", objective.domain))
        rows.append(
            {
                "domain": domain,
                "label": _PLAN_DOMAIN_LABELS.get(domain, "研究范围"),
                "focus": str(getattr(objective, "summary", "") or "").strip(),
                "search_terms": terms,
            }
        )
    return rows


def _generation_note(state: TravelAgentState, revision: int) -> str:
    source = _plan_source(state)
    retry = _retry_available(state, revision)
    retry_text = (
        "可补充调整后重试（需求整理最长 120 秒、独立计划选择最长 30 秒，会产生额外 token），"
        if retry
        else "本次重试次数已用完，"
    )
    if source == "model":
        return (
            "**生成说明**：研究重点与检索词来自独立研究计划模型，"
            "只能使用本次已澄清需求所允许的候选，并已核对执行范围。"
            "确认前的模型调用不计入批准后的运行预算。"
            + (
                "需要修改时会重新整理需求并生成计划（最长分别为 120 秒、30 秒，产生额外 token）。"
                if retry
                else "修改额度已用完，可确认这一版或取消。"
            )
        )
    if source == "unrecorded":
        return (
            "**生成说明**：这是历史计划，未记录研究计划的模型来源；恢复或刷新不会自动调用模型。"
            + retry_text
            + "也可直接确认现有范围或取消。"
        )
    return (
        "**生成说明**：本次模型研究计划缺失或未通过范围校验，未作为确认正文采用；"
        "上面的范围按已识别要求保守整理。确认前的模型调用不计入确认后的运行预算。"
        + retry_text
        + "也可直接确认这份保守范围或取消。"
    )


def _configurable_value(config: Optional[RunnableConfig], key: str) -> Any:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    return configurable.get(key)


def _is_plan_gate_enabled(config: Optional[RunnableConfig]) -> bool:
    request_value = _configurable_value(config, "plan_gate_enabled")
    if request_value is not None:
        return bool(request_value)
    return bool(get_settings().run_control.plan_gate_enabled)


def _assignment_task_text(value: Any) -> str:
    """规范化单个 agent 的任务全文（不截断）。"""
    if isinstance(value, dict):
        text = str(value.get("objective") or "")
    else:
        text = str(value or "")
    return " ".join(text.split())


def _identity_plan_summary(value: Any) -> str:
    """从受控身份投影公开旅行范围；格式不合法时不猜测。"""
    from travel_agent.planning.requirements.identity_contracts import (
        ControlledTripIdentity,
    )

    try:
        identity = ControlledTripIdentity.model_validate(value or {})
    except (TypeError, ValueError):
        return ""
    destinations = " → ".join(place.name for place in identity.destinations)
    party = f"{identity.party.adults}位成人"
    if identity.party.children:
        party += f"、{identity.party.children}位儿童"
    if identity.party.elderly_companions:
        party += "、长辈同行"
    if identity.party.accessibility_required:
        party += "、需要无障碍安排"
    style = identity.style.primary
    if identity.style.secondary_interests:
        style += f"（{'、'.join(identity.style.secondary_interests)}）"
    return (
        f"从{identity.origin.name}出发，按{destinations}的顺序，"
        f"{identity.start_date.isoformat()} 至 {identity.end_date.isoformat()}"
        f"（共{identity.duration_days}天），{party}；偏好：{style}。"
    )


def _plan_gaps(state: TravelAgentState) -> List[str]:
    """只投影合同里真实存在的未决事项，不虚构固定缺口。"""
    spec = getattr(state, "intent_spec", None)
    if spec is None:
        return []
    gaps: List[str] = []
    for clause in getattr(spec, "unresolved_clauses", []) or []:
        text = " ".join(str(getattr(clause, "source_text", "")).split())
        if text:
            gaps.append(text)
    for conflict in getattr(spec, "conflicts", []) or []:
        text = " ".join(
            str(getattr(conflict, "user_visible_summary", "")).split()
        )
        if text:
            gaps.append(text)
    return list(dict.fromkeys(gaps))


def _baseline_intake_preferences(state: TravelAgentState) -> List[Dict[str, str]]:
    """把条件表单基线问题的明确回答投影到确认门的已识别要求。

    归一化模型是 Intent/Constraint 的唯一来源；这里只在模型漏抽取时补一个
    用户可见的保守投影，避免用户明确选过或写下的研究方向在确认前消失。
    选项与自由文本都属于用户回答；默认项（含 ``sensible_default`` 字段或
    默认文案）不投影，不能变成正向要求。
    """

    from travel_agent.conversation.intake import DEFAULT_ANSWER_LABEL

    rows: List[Dict[str, str]] = []
    for source in getattr(state, "intake_evidence_sources", []) or []:
        if not isinstance(source, dict) or source.get("kind") not in {
            "explicit_selection",
            "explicit_supplement",
        }:
            continue
        field = str(source.get("field") or "")
        if not field.startswith("answer:baseline_") or "sensible_default" in field:
            continue
        summary = " ".join(str(source.get("text") or "").split())
        if not summary or summary == DEFAULT_ANSWER_LABEL:
            continue
        rows.append(
            {
                "requirement_id": str(source.get("source_id") or field),
                "summary": summary,
            }
        )
    return rows


def _serialize_plan_text(state: TravelAgentState) -> str:
    """把结构化执行计划序列化为规范化的 markdown 全文（后端单一数据源）。"""
    assignments = state.agent_assignments or {}
    sections: List[str] = []
    identity_summary = _identity_plan_summary(
        getattr(state, "controlled_trip_identity", None)
    )
    if identity_summary:
        sections.append(f"**本次旅行**：{identity_summary}")
    brief = getattr(state, "research_brief", None)
    if brief is not None:
        source = _plan_source(state)
        if source == "model" and brief.research_plan_summary:
            sections.append(f"**研究重点**：{brief.research_plan_summary}")
        scope_rows = _research_scope_rows(state)
        if scope_rows:
            sections.append("**研究范围与检索词**")
            for row in scope_rows:
                sections.append(
                    f"- **{row['label']}**：{row['focus']}；检索词：{'、'.join(row['search_terms'])}"
                )
        sections.append(_generation_note(state, int(state.plan_gate_revision_count or 0)))
    steps: List[str] = []
    for index, group in enumerate(state.execution_plan or [], start=1):
        agents = [
            str(agent) for agent in (group if isinstance(group, list) else [group])
        ]
        agent_labels = "、".join(get_agent_display_name(agent) for agent in agents)
        steps.append(f"### 步骤 {index}：{agent_labels}")
        for agent in agents:
            task = _assignment_task_text(assignments.get(agent)) or "（待补充任务描述）"
            steps.append(f"- **{get_agent_display_name(agent)}**：{task}")
        steps.append("")
    if steps:
        sections.extend(["**执行计划**", *steps])
    gaps = _plan_gaps(state)
    if gaps:
        sections.append("**待核实或需要取舍**：" + "；".join(gaps[:8]))
    user_query = str(getattr(state, "user_query", "") or "")
    if "按合理默认安排，不再补充" in user_query:
        sections.append(
            "**默认安排**：未明确的可选项按合理默认组织；"
            "出发地、目的地、日期和同行人数不使用默认值。"
        )
    return "\n".join(sections).rstrip()


def _build_plan_gate_payload(state: TravelAgentState) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    assignments = state.agent_assignments or {}
    for index, group in enumerate(state.execution_plan or [], start=1):
        agents = [
            str(agent) for agent in (group if isinstance(group, list) else [group])
        ]
        steps.append(
            {
                "step": index,
                "agents": agents,
                "tasks": {
                    agent: _assignment_task_text(assignments.get(agent))
                    for agent in agents
                },
            }
        )

    revision = int(state.plan_gate_revision_count or 0)
    limit_reached = revision >= _MAX_PLAN_GATE_REVISIONS
    retry_available = _retry_available(state, revision)
    constraint_pack = (
        state.constraint_pack if isinstance(state.constraint_pack, dict) else {}
    )
    hard_requirements = [
        {
            "requirement_id": str(item.get("constraint_id") or ""),
            "summary": str(item.get("public_summary") or ""),
        }
        for item in constraint_pack.get("hard_constraints") or []
        if isinstance(item, dict) and item.get("status") in (None, "active")
    ]
    preferences: List[Dict[str, str]] = [
        {
            "requirement_id": str(item.get("constraint_id") or ""),
            "summary": str(item.get("public_summary") or ""),
        }
        for item in constraint_pack.get("soft_preferences") or []
        if isinstance(item, dict)
        and item.get("status") in (None, "active")
        and item.get("visibility") != "internal_only"
    ]
    if state.intent_spec is not None:
        existing_summaries = {item["summary"] for item in hard_requirements}
        for item in state.intent_spec.active_items:
            row = {
                "requirement_id": item.intent_id,
                "summary": item.public_summary,
            }
            if item.strength.value == "hard":
                if row["summary"] not in existing_summaries:
                    hard_requirements.append(row)
                    existing_summaries.add(row["summary"])
            else:
                preferences.append(row)
    known_summaries = {
        item["summary"] for item in [*hard_requirements, *preferences]
    }
    for row in _baseline_intake_preferences(state):
        if row["summary"] in known_summaries:
            continue
        preferences.append(row)
        known_summaries.add(row["summary"])
    payload: Dict[str, Any] = {
        "gate": "plan",
        "revision": revision,
        "revision_limit": _MAX_PLAN_GATE_REVISIONS,
        "revision_limit_reached": limit_reached,
        "plan": {
            "steps": steps,
            "source": _plan_source(state),
            "research_scope": _research_scope_rows(state),
        },
        "plan_text": _serialize_plan_text(state),
        "recognized_requirements": {
            "hard": hard_requirements,
            "preferences": preferences,
        },
        "retry_available": retry_available,
        "decision_options": ["approve", "edit", "supplement", "cancel"]
        if retry_available
        else ["approve", "cancel"],
    }
    # 用户确认的是这一版完整计划；Token 随 payload 一起进 SSE、pending choice
    # 和 checkpoint，恢复时无需重新生成计划即可原样读取。
    payload["approval_token"] = _plan_gate_approval_token(state, payload)
    return payload


def _projection_only_amendment(content: str) -> bool:
    amendment = IntentAmendment(command_id="classification", category="other", content=content, source_kind="plan_gate_amendment")
    return classify_amendment(amendment) is AmendmentImpact.PROJECTION_ONLY


def _needs_clarification(state: TravelAgentState) -> bool:
    contract = getattr(state, "request_contract_candidate", None) or getattr(
        state, "request_contract", None
    )
    return bool(
        contract is not None
        and (
            getattr(contract, "has_blocking_conflicts", False)
            or getattr(contract, "has_unresolved_material_clauses", False)
        )
    )


def _semantic_candidate(state: TravelAgentState):
    candidate = getattr(state, "request_contract_candidate", None)
    return candidate if isinstance(candidate, RequestContract) else None


def _build_clarification_payload(
    state: TravelAgentState, extra_questions=(),
) -> Dict[str, Any]:
    contract = state.request_contract_candidate or state.request_contract
    if contract is None:
        raise ValueError("clarification requires a request contract")
    questions = [
        f"- 请说明「{clause.source_text}」的具体要求。"
        for clause in contract.clause_ledger
        if clause.material and clause.disposition in {
            ClauseDisposition.UNRESOLVED, ClauseDisposition.UNSUPPORTED
        }
    ]
    questions.extend(
        f"- 请确认：{conflict.user_visible_summary}"
        for conflict in contract.intent_spec.conflicts if conflict.blocking
    )
    questions.extend(f"- {question}" for question in extra_questions)
    payload: Dict[str, Any] = {
        "gate": "plan",
        "revision": int(state.plan_gate_revision_count or 0),
        "revision_limit": _MAX_PLAN_GATE_REVISIONS,
        "revision_limit_reached": False,
        "plan": {"steps": []},
        "plan_text": "**需要先补充的信息**\n" + "\n".join(questions),
        "recognized_requirements": {"hard": [], "preferences": []},
        "decision_options": ["supplement", "cancel"],
    }
    payload["approval_token"] = _plan_gate_approval_token(state, payload)
    return payload


def _build_research_plan_failure_payload(state: TravelAgentState) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "gate": "plan",
        "revision": int(state.plan_gate_revision_count or 0),
        "revision_limit": _MAX_PLAN_GATE_REVISIONS,
        "revision_limit_reached": False,
        "plan": {"steps": [], "source": "unrecorded", "research_scope": []},
        "plan_text": (
            "**研究计划尚未生成**\n本次模型未能生成可执行的研究计划。"
            "没有使用固定模板替代，也没有开始查询。你可以重试、补充要求或取消。"
        ),
        "recognized_requirements": {"hard": [], "preferences": []},
        "retry_available": _research_plan_retry_available(state),
        "decision_options": (
            ["retry", "supplement", "cancel"]
            if _research_plan_retry_available(state)
            else ["supplement", "cancel"]
        ),
    }
    payload["approval_token"] = _plan_gate_approval_token(state, payload)
    return payload


def _build_operation_failure_payload(state: TravelAgentState) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "gate": "plan",
        "revision": int(state.plan_gate_revision_count or 0),
        "revision_limit": _MAX_PLAN_GATE_REVISIONS,
        "revision_limit_reached": False,
        "plan": {"steps": [], "source": "unrecorded", "research_scope": []},
        "plan_text": (
            "**研究查询尚未获得执行授权**\n当前计划无法编译出可核验的 Provider 操作。"
            "没有开始查询。你可以重试、补充或缩小研究范围后重新整理，或取消规划。"
        ),
        "recognized_requirements": {"hard": [], "preferences": []},
        "_operation_failure": True,
        "decision_options": (
            ["retry", "supplement", "cancel"]
            if _research_plan_retry_available(state)
            else ["supplement", "cancel"]
        ),
    }
    payload["approval_token"] = _plan_gate_approval_token(state, payload)
    return payload


def _attach_operation_authorization(
    state: TravelAgentState, payload: Dict[str, Any]
) -> Dict[str, Any]:
    from travel_agent.planning.research.operation_compiler import (
        compile_and_approve_research_operations,
    )

    authorized = dict(payload)
    manifest, _approval, limitations = compile_and_approve_research_operations(
        state, approval_token="plan_gate.pending"
    )
    if manifest is None:
        return _build_operation_failure_payload(state)
    if limitations:
        authorized["plan_text"] = (
            f"{authorized.get('plan_text') or ''}\n"
            "**执行边界**：部分需要 Provider 返回后才能确定的补充查询不在本次预授权内，"
            "将被跳过或阻断；上述明确列出的主要研究会按精确参数执行。"
        )
    authorized["approval_token"] = _plan_gate_approval_token(state, authorized)
    manifest, approval, limitations = compile_and_approve_research_operations(
        state, approval_token=authorized["approval_token"]
    )
    if manifest is None or approval is None:
        return _build_operation_failure_payload(state)
    authorized["_operation_manifest"] = manifest
    authorized["_operation_approval"] = approval
    authorized["_operation_limitations"] = list(limitations)
    return authorized


async def plan_gate_node(
    state: TravelAgentState, config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """在规划完成后、Worker 扇出前阻塞，等待用户决定。"""
    if not _is_plan_gate_enabled(config):
        raise RuntimeError("controlled planning requires an enabled approval gate")

    semantic_candidate = _semantic_candidate(state)
    requirement_questions = (
        necessary_requirement_questions(state, semantic_candidate)
        if semantic_candidate is not None and not _needs_clarification(state)
        else ()
    )
    legacy_unplanned = (
        semantic_candidate is None
        and isinstance(getattr(state, "request_contract", None), RequestContract)
        and state.request_contract.research_plan is None
    )
    plan_generation_failed = bool(getattr(state, "research_plan_error", None)) or legacy_unplanned
    clarifying = _needs_clarification(state) or bool(requirement_questions)
    if semantic_candidate is not None and not clarifying:
        return {
            **invalidation_update(AmendmentImpact.RESEARCH_AFFECTING),
            "request_contract": semantic_candidate,
            "request_contract_candidate": None,
            "intent_spec": semantic_candidate.intent_spec,
            "intent_spec_revision": semantic_candidate.intent_spec.revision,
            "constraint_pack": semantic_candidate.constraint_pack,
            "constraint_pack_revision": semantic_candidate.constraint_pack_revision,
            "semantic_receipt": None,
            "semantic_candidate_hash": None,
            "plan_gate_decision": {"action": "requirements_ready"},
        }
    if plan_generation_failed:
        gate_payload = _build_research_plan_failure_payload(state)
    elif clarifying:
        gate_payload = _build_clarification_payload(state, requirement_questions)
    else:
        gate_payload = _build_plan_gate_payload(state)
        if isinstance(getattr(state, "request_contract", None), RequestContract):
            gate_payload = _attach_operation_authorization(state, gate_payload)
    plan_generation_failed = plan_generation_failed or bool(gate_payload.get("_operation_failure"))
    while True:
        decision = interrupt(gate_payload)
        if not isinstance(decision, dict):
            logger.info(
                "plan_gate: non-object decision rejected; waiting for explicit approve/cancel"
            )
            continue

        action = str(decision.get("action") or "").lower()
        revision_count = int(state.plan_gate_revision_count or 0)
        retry_available = _retry_available(state, revision_count)

        if action == "cancel":
            raise RunCancelled(state.run_id, NODE_PLAN_GATE)

        if action not in {"approve", "edit", "supplement", "retry"}:
            logger.info("plan_gate: unsupported action %s rejected", action)
            continue
        if action not in gate_payload.get("decision_options", []):
            logger.info("plan_gate: action %s is not offered by this gate", action)
            continue

        # 非取消决定必须绑定用户看到的 gate 版本。checkpoint 消费处用当前状态
        # 重新构建的 payload 再次校验；旧编辑器的 A 版决定不能授权 B 版计划。
        #
        # 校验失败时不执行决定，而是 ``continue`` 重新 interrupt：这会把同一份
        # state 确定性重投影成带新 token 的 gate（不调模型、不写决定），因此版本
        # 之前写入的无 token 旧 gate 也有一条真实的重新展示→确认路径。
        if not _decision_has_current_gate_version(decision, gate_payload):
            logger.warning(
                "plan_gate: decision not bound to this gate version; re-displaying "
                "versioned gate run_id=%s revision=%s action=%s supplied_token=%s",
                state.run_id,
                revision_count,
                action,
                bool(str(decision.get("approval_token") or "").strip()),
            )
            continue

        if plan_generation_failed and action not in {"retry", "supplement"}:
            continue

        if action == "retry":
            if not plan_generation_failed or not _research_plan_retry_available(state):
                continue
            return {
                "plan_gate_decision": {"action": "retry_research_plan"},
                "research_plan_retry_count": int(
                    getattr(state, "research_plan_retry_count", 0) or 0
                ) + 1,
            }

        if semantic_candidate is not None and action != "supplement":
            continue

        if semantic_candidate is not None:
            content = " ".join(str(decision.get("content") or "").split())[:2000]
            if not content:
                continue
            if revision_count >= 4:
                raise RuntimeError("requirement clarification limit reached")
            amendment = IntentAmendment(
                command_id=f"clarification_{state.run_id}_{state.intent_spec_revision + 1}",
                category="supplement", content=content, source_kind="plan_gate_amendment",
                impact=AmendmentImpact.RESEARCH_AFFECTING,
            )
            answered_exclusion = (
                None
                if _needs_clarification(state)
                else next_exclusion_key(state, semantic_candidate)
            )
            answered_ids = list(dict.fromkeys([
                *(getattr(state, "clarified_exclusion_keys", []) or []),
                *([answered_exclusion] if answered_exclusion else []),
            ]))
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {"action": "clarification"},
                "plan_gate_revision_count": revision_count + 1,
                "clarified_exclusion_keys": answered_ids,
                **invalidation_update(AmendmentImpact.RESEARCH_AFFECTING),
            }

        if clarifying:
            if action != "supplement":
                continue
            content = " ".join(str(decision.get("content") or "").split())[:2000]
            if not content:
                continue
            amendment = IntentAmendment(
                command_id=f"clarification_{state.run_id}_{state.intent_spec_revision + 1}",
                category="supplement", content=content, source_kind="plan_gate_amendment",
                impact=AmendmentImpact.RESEARCH_AFFECTING,
            )
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {"action": "clarification"},
                **invalidation_update(AmendmentImpact.RESEARCH_AFFECTING),
            }

        if action in ("edit", "supplement"):
            if not retry_available:
                logger.info("计划修改次数已达上限，继续等待用户确认或取消")
                continue
            content = " ".join(str(decision.get("content") or "").split())[:2000]

            if not content:
                logger.info("plan_gate: %s 缺少 content，重新 interrupt", action)
                continue
            amendment = IntentAmendment(
                command_id=f"plan_gate_{state.run_id}_{revision_count + 1}",
                category=action,
                content=content,
                source_kind="plan_gate_amendment",
                impact=(
                    AmendmentImpact.PROJECTION_ONLY
                    if _projection_only_amendment(content)
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            )
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {
                    "action": "amendment",
                    "revision": revision_count + 1,
                },
                "plan_gate_revision_count": revision_count + 1,
                **invalidation_update(amendment.impact),
            }

        approve_content = str(decision.get("content") or "").strip()[:2000]
        if approve_content:
            if not retry_available:
                logger.info(
                    "plan_gate: 修改额度已用满，忽略 approve content，重新等待 approve/cancel"
                )
                continue
            projection_only = _projection_only_amendment(approve_content)
            amendment = IntentAmendment(
                command_id=f"plan_gate_{state.run_id}_{revision_count + 1}",
                category=(
                    "projection_only_approve" if projection_only else "approve_content"
                ),
                content=approve_content,
                source_kind="plan_gate_amendment",
                impact=(
                    AmendmentImpact.PROJECTION_ONLY
                    if projection_only
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            )
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {
                    "action": (
                        "projection_amendment_pending"
                        if projection_only
                        else "amendment"
                    ),
                    "revision": revision_count + 1,
                },
                "plan_gate_revision_count": revision_count + 1,
                **invalidation_update(
                    AmendmentImpact.PROJECTION_ONLY
                    if projection_only
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            }
        return {
            "plan_gate_decision": {
                "action": "approve",
                "revision": revision_count,
            },
            "research_operation_manifest": gate_payload.get("_operation_manifest"),
            "research_operation_approval": gate_payload.get("_operation_approval"),
            "research_operation_limitations": list(
                gate_payload.get("_operation_limitations") or []
            ),
            **seal_minimum_delivery_draft(state),
        }


def route_after_plan_gate(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    decision = state.plan_gate_decision or {}
    if decision.get("action") in (
        "amendment", "projection_amendment_pending", "clarification", "semantic_correction",
    ):
        return NODE_REQUEST_CONTRACT_NORMALIZER
    if decision.get("action") in {"requirements_ready", "semantic_confirmed", "retry_research_plan"}:
        return NODE_RESEARCH_PLAN_GENERATOR
    return NODE_DISPATCHER
