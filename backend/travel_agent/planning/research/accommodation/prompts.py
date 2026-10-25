"""Planning research accommodation prompts."""

from __future__ import annotations


def build_accommodation_task_prompt(
    *,
    task_desc: str,
    user_query: str,
    require_current_candidate: bool,
) -> str:
    """Prevent an identity repair from restarting generic area and budget research."""
    if require_current_candidate:
        return f"""这是 Candidate Gate 发起的住宿身份定向补研，不是新一轮住宿区域或预算推荐。

当前任务：{task_desc}
用户原始需求仅用于理解旅行背景：{user_query}

本轮硬性执行规则：
- 只补当前 gaps 指向的具体酒店身份字段；先读取上游 Research Packet 中对应 candidate_id、property_name 和缺失字段。
- 优先调用 global_place_search，并使用受控目的地 ISO 国家码；只接受 Provider 原始类别为 hotel/hostel/guest_house 等真实住宿实体的结果。
- 每个保留的 LodgingCandidate 必须有外部事实逐字支持 property_name、place_id、provider_place_type、provider_country_code 与完整街道地址 address；typed 字段、FactAssertion.asserted_value 与 FieldProvenance 必须一致。
- 只返回酒店标题、区域名或官网链接而没有地址的 place-search 结果不足以准入；继续使用推荐网页搜索查到包含真实地址的官方页或可靠外部页。
- 价格、房型或实时余房查不到时使用 null / needs_confirmation，不得因此把已核验的酒店名称和地址写成 unknown。普通网页或搜索摘要支持的价格只能设为 price_kind=reference_estimate；只有按本次日期和入住条件取得的实时 quote 才可设为 live_quote。reference_estimate 必须有同 entity_id 的价格 FactAssertion 支持，供用户作为“约”预算参考，绝不写成当前报价或可订。
- 动态保留 1 至 3 个满足上述合同的高质量酒店；没有任何完整身份候选就明确失败，不得自产地址、place_id、Provider 类别/国家或 evidence。
"""
    return TASK_TEMPLATE.format(task_desc=task_desc, user_query=user_query)


TASK_TEMPLATE = """请调研当前住宿任务。请先推荐住宿区域，再查询符合硬约束的具体真实酒店，
最后根据已核验价格给出预算比较。普通网页或搜索摘要支持的价格只能作为
`price_kind=reference_estimate` 的“约”预算参考，且必须有同一酒店实体的
价格 FactAssertion 支持并标记 `availability_status=needs_confirmation`；不得把
它写成当前报价或可订。只有按本次日期和入住条件取得的实时 quote 才可标为
`live_quote`。用户明确“最多/不超过/上限”的硬预算不能由 reference estimate
声称已满足，必须保留给服务器端的严格价格校验。

当前任务：{task_desc}
用户原始需求：{user_query}

房源身份、硬约束、价格和可用性事实必须来自外部工具。
住宿推荐要服务实际行程：有依据时说明选区与交通、连住、房型或费用取舍，
没有查询接驳就不声称步行可达或位置方便。推荐理由直接面向旅行者，
不要把“承担过夜住宿责任”“受控目的地一致”当推荐理由。
参考价与实时价都不等于用户已预订，缺失的房型/设施/价格保留未知。
只返回系统提示规定的 ResearchPacket JSON 对象。
"""
