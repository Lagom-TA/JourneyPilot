"""Research packet finalization responsibilities."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Sequence

from travel_agent.entities.provider_evidence import ProviderEvidenceScope
from travel_agent.llm.task_routing import QualityFeedback, TaskKind, TaskLLM
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket

from .failures import _merge_failed_tool_sources
from .metadata import _controlled_destination_ids, _provider_selection_base_payload
from .model_calls import _bounded_packet_model_call, _is_transient_model_call_failure
from .options import (
    _eligible_place_selection_options,
    _eligible_route_selection_options,
    _has_eligible_place_selection,
)
from .parsing import _parse_packet_lenient_first, parse_research_packet_output
from .place_selection import _repair_from_provider_selection
from .policy import (
    _DESTINATION_IDENTITY_FACTS_PER_CANDIDATE,
    _WORKER_CANDIDATE_MODELS,
    ResearchPacketOutputError,
    ResearchWorkerKind,
    packet_candidate_limit,
)
from .route_selection import _repair_from_provider_route_selection
from .schemas import _research_packet_response_schema
from .sources import _authoritative_external_tool_sources
from .transcript import authoritative_tool_messages

logger = logging.getLogger(__name__)

_SCHEMA_REPAIR_TRANSIENT_RETRIES = 1


async def parse_or_repair_research_packet_output(
    raw: str,
    *,
    expected_worker: ResearchWorkerKind,
    expected_run_id: str,
    llm: Any,
    context_messages: Sequence[Mapping[str, Any]],
    authoritative_tool_results: Sequence[Mapping[str, Any]] = (),
    required_transport_classes: Sequence[str] | None = None,
    excluded_candidate_ids: Sequence[str] | None = None,
    require_current_candidate: bool = False,
    expected_active_constraint_ids: Sequence[str] | None = None,
    expected_active_constraints: Sequence[Mapping[str, Any]] | None = None,
    authoritative_packet_metadata: Mapping[str, Any] | None = None,
    required_candidate_kinds: Sequence[str] | None = None,
    authoritative_source_records: Sequence[SourceRecord] = (),
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
) -> ResearchPacket:
    "Parse once, then perform one bounded schema-only model repair."
    evidence_messages = authoritative_tool_messages(authoritative_tool_results)
    try:
        packet = _parse_packet_lenient_first(
            raw,
            expected_worker=expected_worker,
            expected_run_id=expected_run_id,
            required_transport_classes=required_transport_classes,
            excluded_candidate_ids=excluded_candidate_ids,
            require_current_candidate=require_current_candidate,
            expected_active_constraint_ids=expected_active_constraint_ids,
            context_messages=context_messages,
            authoritative_tool_results=authoritative_tool_results,
            authoritative_packet_metadata=authoritative_packet_metadata,
            required_candidate_kinds=required_candidate_kinds,
            authoritative_source_records=authoritative_source_records,
            required_route_scopes=required_route_scopes,
        )
        return _merge_failed_tool_sources(packet, evidence_messages)
    except ResearchPacketOutputError as initial_error:
        eligible_place_options = _eligible_place_selection_options(
            evidence_messages,
            expected_worker,
            excluded_candidate_ids=excluded_candidate_ids,
        )
        provider_selection_base = _provider_selection_base_payload(
            raw,
            expected_worker=expected_worker,
            expected_run_id=expected_run_id,
            authoritative_packet_metadata=authoritative_packet_metadata,
        )
        eligible_route_options = (
            _eligible_route_selection_options(
                evidence_messages,
                required_transport_classes=required_transport_classes,
                excluded_candidate_ids=excluded_candidate_ids,
                required_route_scopes=required_route_scopes,
            )
            if expected_worker == "transport_researcher"
            else []
        )
        controlled_destination_ids = (
            _controlled_destination_ids(provider_selection_base)
            if provider_selection_base is not None
            else []
        )
        # Discovery may offer extra domains; only targeted repairs narrow to the gap.
        scoped_place_options = eligible_place_options
        if required_candidate_kinds and require_current_candidate:
            required_kinds = set(required_candidate_kinds)
            scoped_place_options = {
                candidate_kind: options
                for candidate_kind, options in eligible_place_options.items()
                if candidate_kind in required_kinds
            }
        if provider_selection_base is not None and _has_eligible_place_selection(
            scoped_place_options
        ):
            planned_repair_branch = "provider_selection"
        elif (
            provider_selection_base is not None
            and eligible_route_options
            and controlled_destination_ids
        ):
            planned_repair_branch = "route_selection"
        else:
            planned_repair_branch = "schema_repair"
        logger.info(
            "Research Packet repair entry | worker=%s raw_len=%d place_options=%d "
            "route_options=%d branch=%s initial_error=%s",
            expected_worker,
            len(raw or ""),
            sum(len(options) for options in scoped_place_options.values()),
            len(eligible_route_options),
            planned_repair_branch,
            initial_error,
        )
        if (
            provider_selection_base is not None
            and planned_repair_branch == "provider_selection"
        ):
            try:
                logger.info(
                    "Provider selection repair | worker=%s options=%s initial_error=%s",
                    expected_worker,
                    sum(len(options) for options in eligible_place_options.values()),
                    initial_error,
                )
                packet = await _repair_from_provider_selection(
                    base_payload=provider_selection_base,
                    expected_worker=expected_worker,
                    expected_run_id=expected_run_id,
                    llm=llm,
                    context_messages=context_messages,
                    evidence_messages=evidence_messages,
                    eligible_place_options=scoped_place_options,
                    excluded_candidate_ids=excluded_candidate_ids,
                    require_current_candidate=require_current_candidate,
                    expected_active_constraint_ids=expected_active_constraint_ids,
                    expected_active_constraints=expected_active_constraints,
                    authoritative_packet_metadata=authoritative_packet_metadata,
                    required_candidate_kinds=required_candidate_kinds,
                )
                return _merge_failed_tool_sources(packet, evidence_messages)
            except Exception as selection_error:
                raise ResearchPacketOutputError(
                    f"worker Provider selection repair failed: {selection_error}"
                ) from initial_error
        if (
            provider_selection_base is not None
            and planned_repair_branch == "route_selection"
        ):
            try:
                logger.info(
                    "Provider route selection repair | options=%s initial_error=%s",
                    len(eligible_route_options),
                    initial_error,
                )
                packet = await _repair_from_provider_route_selection(
                    base_payload=provider_selection_base,
                    expected_run_id=expected_run_id,
                    llm=llm,
                    context_messages=context_messages,
                    evidence_messages=evidence_messages,
                    eligible_route_options=eligible_route_options,
                    destination_ids=controlled_destination_ids,
                    required_transport_classes=required_transport_classes,
                    excluded_candidate_ids=excluded_candidate_ids,
                    require_current_candidate=require_current_candidate,
                    authoritative_packet_metadata=authoritative_packet_metadata,
                    expected_active_constraints=expected_active_constraints,
                    required_route_scopes=required_route_scopes,
                )
                return _merge_failed_tool_sources(packet, evidence_messages)
            except Exception as selection_error:
                raise ResearchPacketOutputError(
                    f"worker Provider route selection repair failed: {selection_error}"
                ) from initial_error
        authoritative_external_tool_sources = _authoritative_external_tool_sources(
            evidence_messages,
            eligible_place_options=eligible_place_options,
            authoritative_source_records=authoritative_source_records,
        )
        packet_schema = _research_packet_response_schema(
            expected_worker,
            required_transport_classes,
            expected_active_constraint_ids,
            eligible_place_options,
            required_candidate_kinds,
            required_route_scopes,
            authoritative_external_tool_source_ids=[
                source["source_record_id"]
                for source in authoritative_external_tool_sources
            ],
        )
        schema = json.dumps(
            packet_schema,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        scoped_transport = expected_worker == "transport_researcher" and bool(
            required_transport_classes
        )
        destination_repair = expected_worker == "destination_researcher"
        transport_scope_instruction = (
            "本次 transport_class 只能是 "
            f"{','.join(required_transport_classes)}；禁止输出 long_distance。"
            "本轮只收口一个最高质量 current 候选；segments 作为一个完整字段用一条 "
            "FactAssertion(field_path=segments) 绑定原始路线结果，禁止为每个 segment 的 mode/name/place_id "
            "分别复制 FactAssertion 与 FieldProvenance；route_id、selected_mode、departure_at、arrival_at、"
            "duration_minutes 与 segments 必须逐字复制 global_route_search.routes[0] 并分别建立外部事实"
            "（逐字包括 null：高德只给时长不给时刻表，大陆路线的 departure_at / arrival_at 就是 null，"
            "照抄 null，不得自己算一个时刻出来）；"
            "整份 Packet 最多 12 条事实与 12 条 provenance。"
            if required_transport_classes
            else ""
        )
        candidate_exclusion_instruction = (
            "本轮禁止再次输出这些已拒绝 candidate_id 或同一实体："
            f"{','.join(excluded_candidate_ids)}；必须使用 transcript 中不同的外部实体事实。"
            if excluded_candidate_ids
            else ""
        )
        current_candidate_instruction = (
            "这是定向补研收口：必须至少保留一个 freshness_status=current 的候选；"
            "只有同实体、同字段的当前外部工具结果或网页事实才能标 verified。"
            "若 transcript 没有这样的事实则不要伪造，收口必须失败。"
            if require_current_candidate
            else ""
        )
        constraint_instruction = (
            "每个候选的 active_constraint_ids 与 constraint_evaluations.constraint_id "
            "都必须恰好覆盖这些权威 active hard constraint IDs："
            f"{','.join(expected_active_constraint_ids) or '[]'}；禁止添加、遗漏或重命名。"
            if expected_active_constraint_ids is not None
            else ""
        )
        destination_repair_candidates = packet_candidate_limit(expected_worker)
        destination_repair_facts = (
            destination_repair_candidates * _DESTINATION_IDENTITY_FACTS_PER_CANDIDATE
        )
        destination_scope_instruction = (
            f"目的地结构化收口最多保留 {destination_repair_candidates} 个候选；"
            "优先保留能由单个完整地点 Provider 响应支持全部五个稳定身份字段的实体，"
            "Visit/Dining 都有合格实体时应同时保留两类。每个候选只输出 name 或 branch_name、place_id、"
            "provider_place_type、provider_country_code、address 这五条准入身份事实及对应 provenance；"
            f"本轮最多 {destination_repair_facts} 条事实、{destination_repair_facts} 条 provenance、"
            f"{destination_repair_candidates} 条 SourceRecord。其它字段没有本轮直接外部支持"
            "（Tool Gateway transcript 中的结果、本轮真检索到的网页，或提示词里印过「引用标识」的参考知识库 chunk）"
            "就留空数组或 null，禁止裁剪 SourceRecord.snapshot 或用摘要替代完整工具返回。"
            if destination_repair
            else ""
        )
        provider_selection_instruction = (
            "本轮 transcript 已有通过 Tool Gateway evidence 边界且与当前 Worker 领域匹配的地点记录；"
            "candidates 不得为空，必须显式选择至少一个下列 typed option，并逐字使用其 place_id。"
            "这只是可选集合，不代表按 Provider 排名自动入选；你仍须根据任务和约束作出选择。"
            f"eligible_place_options={json.dumps(eligible_place_options, ensure_ascii=False, separators=(',', ':'))}。"
            if _has_eligible_place_selection(eligible_place_options)
            else ""
        )
        authoritative_source_instruction = (
            "external_tool SourceRecord 的 source_record_id 必须逐字取自下列权威清单，"
            "按 tool_name 对上 transcript 中的同一次调用；清单之外的成功工具证据一律标 "
            'source_kind="external_web"，禁止自行拼接 external_tool id。'
            "清单只列可以承载候选事实的成功 Provider 身份；失败或降级的调用不在其中，"
            "也不要改写成 external_web 来源，系统会从 transcript 补齐这些记录。"
            f"authoritative_external_tool_sources={json.dumps(authoritative_external_tool_sources, ensure_ascii=False, separators=(',', ':'))}。"
            if authoritative_external_tool_sources
            else (
                "本轮没有任何权威 external_tool source id；所有成功的工具证据一律标 "
                'source_kind="external_web"，禁止输出 external_tool SourceRecord；'
                "失败或降级的调用不要写成任何来源，系统会从 transcript 补齐这些记录。"
            )
        )
        repair_messages = [dict(message) for message in context_messages]
        if raw.strip():
            repair_messages.append({"role": "assistant", "content": raw})
        repair_messages.append(
            {
                "role": "user",
                "content": (
                    "上一次输出没有通过 Research Packet schema gate。现在只做一次结构化收口："
                    "仅使用本对话中已有的外部工具结果和事实，不调用工具，不新增、猜测或补齐现实事实；"
                    "缺失字段按 schema 使用 null、空数组或 unknown，绝不伪造来源。"
                    "若所有候选事实都只来自失败、降级或自产来源，必须输出 candidates=[]、"
                    "fact_assertions=[]、field_provenance=[]；失败 SourceRecord 由系统从 Tool Gateway "
                    "transcript 编译，不要自行输出；"
                    "只输出一个可被 json.loads 直接解析的 JSON 对象，不要 Markdown、代码围栏、解释或旧信封。"
                    f"固定 worker_kind={expected_worker}，run_id={expected_run_id}。"
                    f"校验错误：{initial_error}。"
                    f"{transport_scope_instruction}"
                    f"{candidate_exclusion_instruction}"
                    f"{current_candidate_instruction}"
                    f"{constraint_instruction}"
                    f"{destination_scope_instruction}"
                    f"{provider_selection_instruction}"
                    f"{authoritative_source_instruction}"
                    "candidates 只能包含当前 Worker 的领域类型："
                    f"{','.join(kind for kind, _ in _WORKER_CANDIDATE_MODELS[expected_worker])}；"
                    f"最多保留 {1 if scoped_transport else packet_candidate_limit(expected_worker)} 个有直接外部支持的高质量候选；"
                    "只保留直接支持这些候选的最小 facts/sources/provenance 闭包，"
                    "但入选 SourceRecord.snapshot 仍必须是完整工具返回或完整 RAG chunk，禁止裁剪成模型摘要；"
                    "external_tool SourceRecord 的 identity、snapshot、content_hash 和 cache_provenance "
                    "由系统从 Tool Gateway transcript 编译；禁止复制或修补这些字段，禁止生成 cache_provenance。"
                    "上游 packet 只能作为研究上下文，禁止复制其候选、事实或来源。"
                    "用户输入、旅行日期、人数、偏好、模型输出和确定性计算都不是外部来源；"
                    "禁止创建 User Context/JourneyPilot/Assistant SourceRecord。受控输入直接写 typed candidate，"
                    "不要为它们创建伪外部 FactAssertion/SourceRecord。"
                    "VisitCandidate 的 name/place_id/provider_place_type/provider_country_code/address 与 DiningCandidate 的 branch_name/place_id/provider_place_type/provider_country_code/address "
                    "必须分别有同 entity_id 的外部事实，且 asserted_value 与 typed candidate 对应字段完全一致；"
                    "provider_place_type/provider_country_code 必须逐字来自外部地点 Provider；国家码必须匹配受控目的地，禁止把景点/场馆/市场身份改写成餐馆。"
                    "LodgingCandidate 的 property_name/place_id/provider_place_type/provider_country_code/address 也必须分别有同 entity_id 的外部事实，"
                    "且 asserted_value 与 typed candidate 对应字段完全一致；Provider type/country 必须逐字来自地点 Provider 并匹配受控目的地，只有酒店标题而没有稳定身份和完整地址不足以准入。"
                    "所有 candidate_kind 必须显式输出；候选引用的 fact_assertion_ids 和 source_record_ids "
                    "必须存在于同一 packet，且 source 必须由该候选事实的 supports 链路可达。"
                    "Candidate.research_packet_id、fact_assertion_ids、field_paths、source_record_ids "
                    "会由父 Packet 和同 entity_id 候选事实确定性派生；不得加入其它实体事实或无关来源。"
                    "对每个候选 C：C.fact_assertion_ids 必须恰好等于 entity_id=C.candidate_id 的事实 id 集合；"
                    "C.field_paths 必须恰好等于这些事实的 field_path 集合，禁止多写任何未被事实支持的路径；"
                    "每个 C.field_paths 路径必须有且只有一条相同 entity_id 和 field_path 的 FieldProvenance；"
                    "候选事实与 provenance 的 entity_ref.entity_id 必须等于 candidate_id；"
                    "Candidate.freshness_status 必须与其事实状态一致：全部 verified 时只能是 current；"
                    "含 refreshing 时为 refreshing；其余情况为 stale。"
                    "TransportCandidate.from_endpoint 必须与首个 segment.from_endpoint 完全一致，"
                    "to_endpoint 必须与末个 segment.to_endpoint 完全一致；多段换乘按真实顺序完整保留。"
                    "本轮检索且直接支持稳定实体身份的页面可标 verified，缺少发布时间本身不等于 stale；"
                    "只有明确过期、冲突或不再适用才标 stale。缺少实时价格/余房时使用 null/needs_confirmation，"
                    "并省略对应事实，不要把实体身份事实降为 stale。"
                    "external_fact provenance 的 reference_ids 只能引用同一 packet 的 fact_assertion_ids。"
                    "描述性字段（visit 的 highlights/opening_window/reservation_required、dining 的 "
                    "cuisine_types/recommended_dishes/opening_window/reservation_required、lodging 的 "
                    "room_type/facilities）仅填写来源直接支持的内容，并配同 entity_id、同 field_path 的 FactAssertion。"
                    "没有依据时保留 null 或空数组；禁止按场所常识猜营业、预约、菜品、房型和设施，也不得伪造来源。"
                    f"必须满足此 JSON Schema：{schema}"
                ),
            }
        )
        if isinstance(llm, TaskLLM):
            llm = llm.router.get_for_task(
                TaskKind.SCHEMA_REPAIR, QualityFeedback(schema_failures=1)
            )
        transient_retries = _SCHEMA_REPAIR_TRANSIENT_RETRIES
        while True:
            try:
                repaired = await _bounded_packet_model_call(
                    llm,
                    repair_messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "research_packet",
                            "strict": True,
                            "schema": packet_schema,
                        },
                    },
                    temperature=0,
                )
                break
            except Exception as call_error:
                if transient_retries < 1 or not _is_transient_model_call_failure(
                    call_error
                ):
                    raise ResearchPacketOutputError(
                        f"worker Research Packet schema repair failed: {call_error}"
                    ) from initial_error
                transient_retries -= 1
                logger.info(
                    "Schema repair transient retry | worker=%s call_error=%s",
                    expected_worker,
                    call_error,
                )
        try:
            packet = parse_research_packet_output(
                repaired,
                expected_worker=expected_worker,
                expected_run_id=expected_run_id,
                required_transport_classes=required_transport_classes,
                excluded_candidate_ids=excluded_candidate_ids,
                require_current_candidate=require_current_candidate,
                expected_active_constraint_ids=expected_active_constraint_ids,
                context_messages=context_messages,
                authoritative_tool_results=authoritative_tool_results,
                authoritative_packet_metadata=authoritative_packet_metadata,
                required_candidate_kinds=required_candidate_kinds,
                authoritative_source_records=authoritative_source_records,
                required_route_scopes=required_route_scopes,
            )
            logger.info(
                "Research Packet schema repair parsed | worker=%s repaired_len=%d "
                "candidates=%d facts=%d sources=%d",
                expected_worker,
                len(repaired or ""),
                len(packet.candidates),
                len(packet.fact_assertions),
                len(packet.source_records),
            )
            return _merge_failed_tool_sources(packet, evidence_messages)
        except Exception as repair_error:
            raise ResearchPacketOutputError(
                f"worker Research Packet schema repair failed: {repair_error}"
            ) from initial_error
