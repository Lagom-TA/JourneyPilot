"""需求归一化提示词。"""

from __future__ import annotations

from travel_agent.llm.strict_json_schema import as_strict_schema
from travel_agent.planning.requirements.normalization.contracts import (
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from typing import Dict
from typing import List
import json


def _normalization_prompt(
    clauses: List[SourceClause], controlled_identity: Dict[str, object]
) -> List[Dict[str, str]]:
    payload = [
        {
            "clause_id": item.clause_id,
            "source_kind": item.source_kind,
            "text": item.source_text,
        }
        for item in clauses
    ]
    wire_contract = (
        "线协议（字段名和值必须逐字使用）：每行固定为"
        '{"clause_id":"复制输入ID","disposition":"...","reason_code":null,'
        '"intents":[],"constraints":[]}。disposition 只能是 mapped_to_intent、'
        "mapped_to_constraint、controlled_identity、background_context、"
        "non_actionable、unsupported、unresolved；仅 unsupported/unresolved 的"
        "reason_code 使用非空字符串。Intent 固定字段为 kind、target、strength、"
        "priority、value、verification_mode、impact_stages、public_summary。"
        "kind/target/strength 必须使用 schema 中的小写枚举，禁止 intent_type 或 type。"
        "value 必须是带 value_type 的对象：scalar/value，category/categories，"
        "count/operator/count/unit，cadence/frequency/count/time_window/"
        "required_attributes，time_window/window/applies_to，sequence/ordered_items，"
        "geographic/area/relation，output_requirement/required_field/applies_to，或"
        "alternative/count/distinction。Constraint 固定为 category、value、params；"
        "category 只能取 schema 枚举，params 只能取 schema 已声明字段，禁止"
        "itinerary_preference 等自造类别。controlled_identity/background_context 行的"
        "intents 与 constraints 均为空数组。"
    )
    system = (
        "你是 JourneyPilot 请求合同规范化器。逐条处理输入 clause，不得遗漏、合并或新增 clause。"
        "仅把本次任务要求写成 Intent；目的地、日期、出发地等已经存在于 controlled identity 的事实标记为 controlled_identity。"
        "旅行安全、预算、交通、住宿和行动能力要求同时写入 constraints；数量、频率、主题、排除、"
        "顺序、输出字段和多方案要求属于 Intent。冲突和无法可靠理解的指令标记 unresolved，不得猜测。"
        "明确要求必须包含多个命名事项时，每个事项分别输出一个 hard MUST_INCLUDE Intent，不得合并成 objective。"
        "例如“必须安排甲地、乙地”要输出两个 Intent，两个 category value 分别只含甲地、乙地。"
        "预算金额只能来自含预算、费用、货币或上限语义的原文，并原样保留 amount、currency、per。"
        "只有约束、没有 Intent 的 clause 使用 mapped_to_constraint；同时含 Intent 和约束时使用 mapped_to_intent。"
        "跨城去程、返程、往返或指定高铁/航班的要求使用 hard Intent，target=long_distance_transport；"
        "住宿安排使用 target=lodging；逐日时间和逐日交通的呈现要求使用 output_requirement。"
        "locked_local_mode 只表示市内接驳方式，禁止写入高铁、航班等跨城方式。"
        "明确要求备选方案时输出 hard ALTERNATIVES，target=delivery；未写数量表示主方案之外至少一个备选，count=2。"
        "source_kind 只用于确定优先级，不得改写。"
        f"{wire_contract}只输出符合 JSON Schema 的对象，不要解释。"
    )
    user = json.dumps(
        {"controlled_identity": controlled_identity, "clauses": payload},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalization_response_format(
    clauses: List[SourceClause],
    *,
    supports_native_schema: bool,
) -> Dict[str, object]:
    """把通用契约 schema 绑定到本次调用的分句清单。"""

    model_schema = RequestContractNormalizationResult.model_json_schema()
    clause_array = model_schema["properties"]["clauses"]
    clause_array["minItems"] = len(clauses)
    clause_array["maxItems"] = len(clauses)
    clause_definition = model_schema["$defs"]["NormalizedClauseDraft"]
    clause_definition["properties"]["clause_id"]["enum"] = [
        clause.clause_id for clause in clauses
    ]
    schema = as_strict_schema(model_schema) if supports_native_schema else model_schema
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "request_contract_normalization",
            "strict": supports_native_schema,
            "schema": schema,
        },
    }
