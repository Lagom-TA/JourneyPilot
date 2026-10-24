"""Task prompt for the typed accommodation Research Packet worker."""

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
