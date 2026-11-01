from __future__ import annotations


def build_accommodation_task_prompt(*, task_desc: str, user_query: str) -> str:
    return f"""你负责研究住宿，按任务、旅行日期和用户需求选择区域及具体候选，并自行选择需要的工具与查询。目的地与交通研究已经完成，上游研究视图里有活动区域分布、餐饮位置和交通衔接时间。

任务：{task_desc}
用户需求和回答：{user_query}

结合上游成果选择住宿区域：让住处靠近主要活动区域、方便已研究出的交通衔接，再围绕真实入住日期、人数和房型比较具体 property。用已有事实说明位置、房型或费用取舍，资料不足时保留未知。参考价不是实时可订报价，不要编造价格或房态。
返回系统提示要求的 Research Packet JSON。"""
