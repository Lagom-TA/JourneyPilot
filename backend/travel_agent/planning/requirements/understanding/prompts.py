"""旅行理解的固定职责与动态输入。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.llm.token_counting import estimate_message_tokens
from travel_agent.planning.requirements.constraints.presentation import (
    describe_constraint_sources,
    partition_constraint_pack,
)


def understanding_system_prompt() -> str:
    return """你负责在正式研究前理解这趟旅行，综合旅行者的输入和相关背景，整理成交给后续规划角色的完整旅行理解。

<principles>
- 本次自然语言、已提交表单中的值（包括默认值）、围绕这趟旅行的提问和旅行者的回答同属有效输入，同等考虑。结合对话角色和完整的一问一答理解回答，区分助手提问、建议与旅行者的实际表达；同一条消息中的助手提问和旅行者回答按各自标注理解。
- 保留同一趟旅行此前已确认的信息。旅行者后续明确更正时，以更正后的意思为准；仍有真正影响规划且没有更正的关键信息冲突时，中性说明分歧并请旅行者决定。已说清或已回答的内容继续沿用。
- 历史画像、记忆、对话摘要和预设按标注的来源作为背景参考；摘要和约束整理可能包含模型推断。识别其中与这趟旅行有关的已确认信息，同时区分历史偏好、助手建议和本次旅行者的明确表达。
- 本次旅行基础信息可能来自已提交表单，也可能是此前模型整理的结果；已有旅行理解也是整理结果。结合原话和问答理解它们，保留可靠信息，依照其实际来源表述。
- 用自然语言完整保留其他要求，尤其是过敏、人数、预算、行动限制、必去或避开事项。本次没有提供的信息保持未知。
- 相对日期按参考日期理解。日期不明确时询问旅行天数或具体日期；只有月份或季节等不确定表达时先问用户。只给天数没有日期时，以当前日期为暂定出发日，并在 requirements 中说明这是规划假设；用户指定了日期则以用户为准。
- 单独旅行表示一位成人；只知道总人数时，成人和儿童的构成保持未知。
- 需要核实地点或背景时，自主使用可用的地点、网络和知识工具。工具返回作为资料，地点、坐标和来源与实际记录保持一致。
- 基础信息中的已核实地点可直接沿用；其他地点从本次或此前问答轮中地点工具真实返回的记录中选择，尚未核实的地点留空。同名地点在确需旅行者决定时询问。
- 正式安排按天生成，需要已核实的目的地和明确或暂定的起止日期；出发地、人数和风格可以保持未知。地点未核实且查询不可用时，先保留其他已知信息；没有其他需要询问的事项时输出 ready，等待重新查询。
</principles>

<output>
每轮输出一个 JSON 对象：
{"action": "ask 或 ready", "trip_identity": {…}, "requirements": "整理后的完整旅行要求", "questions": […]}
- 无论 ask 或 ready，都输出当前可靠知道的基础信息和整理后的要求。
- questions 仅在 ask 时填写，不必询问时为空，每轮最多 4 题。每题含 id、question、kind（single、multiple 或 date_range）和 options（含 id、label 的数组，可为空，最多 6 个）。询问具体出发与返程日期用 date_range，用户可选日期或写自然语言；只给天数时，回答卡会以当前日期为暂定起点，用户可改选。
- trip_identity 的键：origin、destinations、start_date、end_date、dates_assumed、party、style。未知项用 null，未知目的地用空数组；使用暂定日期时 dates_assumed 为 true，用户指定日期时为 false。
- 地点从基础信息中的已核实记录或工具结果选择并给出 place_id。global_place_search 结果带 trip_identity 时，沿用其原始名称、坐标和地点标识；其他搜索结果用于理解背景，已核实的基础地点以表单或地点工具记录为准。
- 地点 kind 保持工具返回的英文枚举：出发地使用 city、airport、train_station；目的地使用 city、administrative_area、island、scenic_area。地点角色由 origin 或 destinations 表达，途经地或单个景点记录在旅行要求中。
- 日期用 YYYY-MM-DD，目的地按游览顺序列出。总天数 = end_date − start_date + 1；单次最多 14 天，目的地最多 5 个且不超过行程天数。
- party 的 total、adults、children、elderly_companions、accessibility_required 填写已知值，未知为 null；style 有明确风格时填 primary、secondary_interests、source（current 或 suggested）。
</output>"""


def _earlier_followup_exchanges(state: Any) -> str:
    """交付后连续追问里，本次新输入之前的往来；新输入本身已在「用户旅行想法」里。"""
    context = (state.refinement_context or "").strip()
    latest = f"旅行者：{state.user_query}"
    if context.endswith(latest):
        context = context[: -len(latest)].rstrip()
    return context


def _constraint_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries = []
    for item in items:
        entry = {
            "内容": item.get("value"),
            "来源": describe_constraint_sources(item),
            "类别": item.get("category"),
        }
        if item.get("params"):
            entry["补充信息"] = item["params"]
        entries.append(entry)
    return entries


_REFERENCE_MAX_ITEMS = 6
_REFERENCE_TOKEN_BUDGET = 4000
_REFERENCE_OMISSION_NOTE = "部分背景参考未列出；未列出不代表旅行者撤回。"


def _reference_payload(state: Any, *, token_budget: int = _REFERENCE_TOKEN_BUDGET) -> Dict[str, Any]:
    reference: Dict[str, Any] = {}
    pack = state.constraint_pack or {}
    items = partition_constraint_pack(pack)["reference"]
    meta = pack.get("pack_meta") if isinstance(pack, dict) else None
    omitted = len(items) > _REFERENCE_MAX_ITEMS or bool(
        isinstance(meta, dict) and meta.get("manual_memory_truncated")
    )

    def fits(candidate: Dict[str, Any]) -> bool:
        # 预留省略说明的空间，不截断单条资料以免改变原意。
        with_note = {**candidate, "参考资料说明": _REFERENCE_OMISSION_NOTE}
        message = {
            "role": "user",
            "content": json.dumps({"背景参考": with_note}, ensure_ascii=False, default=str),
        }
        return estimate_message_tokens(message) <= token_budget

    if isinstance(state.session_anchor, dict):
        anchor = state.session_anchor
        summary = anchor.get("summary") or ""
        constraints = anchor.get("key_constraints") or []
        anchor_key = "本次会话较早对话摘要（模型整理）"
        kept_anchor: Dict[str, Any] = {"摘要": "", "摘要中的约束": []}
        if summary:
            candidate = {**kept_anchor, "摘要": summary}
            if fits({**reference, anchor_key: candidate}):
                kept_anchor = candidate
            else:
                omitted = True
        if not isinstance(constraints, list):
            omitted = bool(constraints) or omitted
            constraints = []
        for constraint in constraints:
            candidate = {
                **kept_anchor,
                "摘要中的约束": [*kept_anchor["摘要中的约束"], constraint],
            }
            if fits({**reference, anchor_key: candidate}):
                kept_anchor = candidate
            else:
                omitted = True
        if kept_anchor["摘要"] or kept_anchor["摘要中的约束"]:
            reference[anchor_key] = kept_anchor

    entry_key = "画像、记忆与其他参考"
    kept_entries: List[Dict[str, Any]] = []
    for entry in _constraint_entries(items[:_REFERENCE_MAX_ITEMS]):
        candidate_entries = [*kept_entries, entry]
        if fits({**reference, entry_key: candidate_entries}):
            kept_entries = candidate_entries
        else:
            omitted = True
    if kept_entries:
        reference[entry_key] = kept_entries
    if omitted:
        reference["参考资料说明"] = _REFERENCE_OMISSION_NOTE
    return reference


_SUBMITTED_FORM = "本次已提交表单（含默认值）"
_PRIOR_IDENTITY = "此前输入中的基础信息（可能为提交值或模型整理）"
_CURRENT_IDENTITY = "本次旅行已有基础信息（可能包含模型整理）"


def _saved_input_prefix(state: Any) -> Dict[str, Any]:
    """只提取消息前缀中的本次输入，不重放旧的混合来源背景。"""
    saved: Dict[str, Any] = {}
    for message in getattr(state, "understanding_messages", None) or []:
        if message.get("role") in {"assistant", "tool"}:
            break
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in (_PRIOR_IDENTITY, "用户旅行想法"):
            if payload.get(key) and key not in saved:
                saved[key] = payload[key]
        identity = payload.get("已知基础信息") or payload.get(_CURRENT_IDENTITY)
        if isinstance(identity, dict) and identity and _PRIOR_IDENTITY not in saved:
            saved[_PRIOR_IDENTITY] = identity
    return saved


def _has_labeled_exchange(content: str) -> bool:
    return content.lstrip().startswith("助手提问：") and "\n旅行者回答：" in content


def _recent_dialogue(state: Any, *, token_budget: int = 12000) -> tuple[List[Dict[str, str]], bool]:
    # 交付后的追问已有单独的角色标注上下文，避免重复附入原对话。
    history = [] if state.refinement_context else list(state.messages or [])
    if history and getattr(history[-1], "type", "") == "human" and history[-1].content == state.user_query:
        history.pop()
    recent = []
    for message in history:
        role = {"human": "user", "ai": "assistant"}.get(getattr(message, "type", ""))
        content = getattr(message, "content", "")
        if role and isinstance(content, str) and content.strip():
            recent.append({"role": role, "content": content})

    # 已标注的完整问答不依赖前一条助手消息；其他相邻问答作为一组保留。
    selected: List[Dict[str, str]] = []
    used = 0
    index = len(recent) - 1
    while index >= 0:
        start = index
        if (
            recent[index]["role"] == "user"
            and not _has_labeled_exchange(recent[index]["content"])
            and index
            and recent[index - 1]["role"] == "assistant"
        ):
            start -= 1
        group = recent[start:index + 1]
        tokens = sum(estimate_message_tokens(message, "") for message in group)
        last_question = (
            not selected and group[-1]["role"] == "assistant"
            and not _has_labeled_exchange(state.user_query)
        )
        if used + tokens > token_budget and not last_question:
            break
        selected = group + selected
        used += tokens
        index = start - 1
    return selected, index >= 0


def understanding_context_payload(state: Any, *, dialogue_token_budget: int = 12000) -> Dict[str, Any]:
    """按原始请求、问答、后续补充的时间顺序附入本次旅行输入。"""
    payload: Dict[str, Any] = {}
    items = partition_constraint_pack(state.constraint_pack or {})["current"]
    if items:
        payload["本次应用的预设与输入整理"] = _constraint_entries(items)
    if state.preset_context:
        payload["当前启用的预设背景"] = state.preset_context
    saved = _saved_input_prefix(state)
    submitted = getattr(state, "submitted_trip_identity", None)
    if submitted:
        payload[_SUBMITTED_FORM] = submitted
    prior_identity = saved.get(_PRIOR_IDENTITY) if submitted is None else None
    if prior_identity and prior_identity != state.controlled_trip_identity:
        payload[_PRIOR_IDENTITY] = prior_identity
    if state.controlled_trip_identity and state.controlled_trip_identity != submitted:
        payload[_CURRENT_IDENTITY] = state.controlled_trip_identity
    if state.current_requirements:
        payload["已有旅行理解（模型整理）"] = state.current_requirements
    if state.current_time:
        payload["参考日期"] = state.current_time
    recent, omitted = _recent_dialogue(state, token_budget=dialogue_token_budget)
    if recent:
        payload["近期对话（按角色区分，判断是否与本次旅行有关）"] = recent
    if omitted:
        payload["近期对话说明"] = "部分较早的对话未列出。"
    followup = _earlier_followup_exchanges(state)
    if followup:
        payload["本轮追问上下文"] = followup
    saved_query = saved.get("用户旅行想法")
    if saved_query and saved_query != state.user_query:
        payload["此前输入的旅行想法"] = saved_query
    payload["用户旅行想法"] = state.user_query
    if state.understanding_qa:
        payload["此前问答"] = [
            {
                "问题标识": row.get("question_id"),
                "助手提问": row.get("question"),
                "旅行者回答": row.get("answer"),
            }
            for row in state.understanding_qa
        ]
    amendments = [
        item.content for item in state.pending_intent_amendments
        if item.command_id not in state.applied_intent_amendment_ids
    ]
    if state.plan_gate_amendment is not None:
        amendments.append(state.plan_gate_amendment.content)
    if amendments:
        payload["最新补充"] = amendments
    return payload


def initial_understanding_messages(
    state: Any, *, reference_token_budget: int = _REFERENCE_TOKEN_BUDGET, dialogue_token_budget: int = 12000
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": understanding_system_prompt()},
    ]
    reference = _reference_payload(state, token_budget=reference_token_budget)
    if reference:
        messages.append({
            "role": "user",
            "content": json.dumps({"背景参考": reference}, ensure_ascii=False, default=str),
        })
    messages.append({
        "role": "user",
        "content": json.dumps(
            understanding_context_payload(state, dialogue_token_budget=dialogue_token_budget),
            ensure_ascii=False,
            default=str,
        ),
    })
    return messages
