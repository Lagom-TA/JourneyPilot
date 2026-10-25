"""Planning research transport prompts."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.planning.research.provider_contracts import ProviderEvidenceScope


def build_transport_task_prompt(
    *,
    task_desc: str,
    user_query: str,
    required_transport_classes: List[str] | None,
    connector_gaps: List[Dict[str, Any]] | None,
    require_current_candidate: bool,
    required_route_scopes: List[ProviderEvidenceScope],
) -> str:
    """Keep a scoped Gate retry from falling back to the generic intercity task."""
    if required_transport_classes and "long_distance" in required_transport_classes:
        route_legs = [
            scope.route_leg.model_dump(mode="json")
            for scope in required_route_scopes
            if scope.route_leg is not None
        ]
        return f"""这是 Candidate Gate 发起的精确长途交通 Leg 补研，不是通用交通调研。

当前任务：{task_desc}
权威 required route legs：{json.dumps(route_legs, ensure_ascii=False)}

本轮硬性执行规则：
- 只查询上述 from_place_id → to_place_id、service_date 与 leg_role 对应的责任；不得改方向、改日期或用另一条 Leg 抵消。
- 上文工具消息里若有铁路能力声明说明该 service_date 超出 12306 预售窗（reference_only），本轮必须改用航班 Provider（search_flights）为同一条 Leg 取证：换 Provider 不是换责任，日期与端点一个都不许动。重复同一条铁路查询不会得到新答案。航班同样给不出可核验班次时明确保留缺口。
- cross_day_required=true 时，search_flights 必须传 require_cross_day=true。
- Provider route 的 SourceRecord、facts、provenance 与 scope identity 由系统从完整 Tool Gateway envelope 编译；模型只选择 route_id 和表达取舍，不得自产 evidence。
- 没有匹配当前精确 Leg 的完整 Provider 路线时明确保留缺口，不得退回 start_date 去程或市内路线。
"""
    if required_transport_classes:
        allowed = ", ".join(required_transport_classes)
        return f"""这是 Candidate Gate 发起的市内路线定向补研，不是新一轮通用交通调研。

当前任务：{task_desc}
用户原始需求仅用于理解旅行背景：{user_query}
精确 connector gap：{json.dumps(connector_gaps or [], ensure_ascii=False)}

本轮硬性执行规则：
- 只研究上游 Research Packets 中具体 Visit/Dining 实体之间的真实市内连接，transport_class 只能是 {allowed}。
- from_endpoint / to_endpoint 必须逐字绑定上游候选的真实名称与 place_id；不得改成附近车站、区域或泛化地名。
- 市内路线只调用 global_route_search，并逐字传入上游端点名称、place_id、坐标和带目的地时区的出发时间。它已按端点坐标自动分派 provider（中国大陆及周边走高德，其余地区走 MOTIS/Transitous），你不需要也不能指定 provider；它失败时不要换用别的地图路线工具去回答同一个问题——那类结果不构成本轮可用的路线证据，直接如实失败。
- 禁止查询航班、12306、出发城市到目的地的路线或任何 long_distance 候选；禁止先做城际交通再做市内路线。
- 本轮只收口一个最高质量 current 候选。必须逐字复制 global_route_search.routes[0] 的 route_id、selected_mode、departure_at、arrival_at、duration_minutes 与完整 segments，并分别建立外部 FactAssertion/FieldProvenance；**逐字包括 null**——高德只给时长不给时刻表，所以大陆路线的 departure_at / arrival_at 就是 null，照抄 null，不得用出发时间加时长自己算一个时刻出来。segments 只用一条 field_path=segments 聚合事实，禁止把每个 segment 的叶子字段展开成重复 lineage。整份 Packet 最多 12 条事实与 12 条 provenance。
- 至少一个候选必须由本轮外部结果支持为 freshness_status=current；没有足够事实就明确失败，不得自产 evidence。
"""
    if require_current_candidate:
        return f"""这是 Candidate Gate 发起的候选事实定向补研，不是重跑整份交通研究。

当前任务：{task_desc}
用户原始需求仅用于理解旅行背景：{user_query}

只补当前 gaps 指向的候选或缺失交通类别，优先使用 assignment 推荐工具；不要执行与 gaps 无关的通用“航班、铁路、市内路线”清单。至少一个候选必须由本轮外部结果支持为 freshness_status=current；没有足够事实就明确失败，不得自产 evidence。
"""
    return TASK_TEMPLATE.format(task_desc=task_desc, user_query=user_query)


TASK_TEMPLATE = """请调研当前交通任务。首次完整调研只能使用 12306/航班等长距离 Provider，
核验受控出发地到目的地的城际班次、时刻和价格；此时 placement skeleton 尚未形成，
禁止研究目的地市内路线、附近车站、机场到景点或任意实体对，即使 Planner 文本提到了市内交通也必须忽略。
市内衔接只能留待系统从 placement skeleton 提取精确相邻端点后，再由独立 connector gap 轮次研究。

当前任务：{task_desc}
用户原始需求：{user_query}

如果且仅如果用户明确要求“跨日 / 跨夜 / overnight / red-eye”长途交通，调用航班 Provider 时必须传
require_cross_day=true；没有符合条件的真实 Provider 路线就明确失败。不得改写 Provider 时刻、复制旧候选
或用“夜间”文字把同日路线伪装成跨日。普通请求不得设置该参数。

只有 connector gap 轮次才存在指定 endpoint pair；届时必须使用真实路线 Provider，并逐字保留 Provider endpoints。
只返回系统提示规定的 ResearchPacket JSON 对象。
"""
