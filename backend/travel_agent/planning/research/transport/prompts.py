from __future__ import annotations


def build_transport_task_prompt(*, task_desc: str, user_query: str) -> str:
    return f"""你负责调研适合这次旅行的交通，按任务和现有条件选择工具与查询。目的地研究已经完成，上游研究视图里有它的候选、区域分布与取舍建议。

任务：{task_desc}
用户需求和回答：{user_query}

结合上游的区域分布研究重要衔接与时间成本：先保证体验、餐饮与可能的住宿位置之间走得通、时间合理，再补充有差异的备选方案。区分真实班次、参考路线和未知信息，不编造时刻或价格。跨日需求以用户的最新表达为准。
返回系统提示要求的 Research Packet JSON。"""
