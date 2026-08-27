"""图上每个节点都要在三张按名字查的表里有一行。

节点名是图的私有词汇，但有三张表按这个名字查东西：trace 的阶段分组、Agent 中文名、
步骤中文名。三张表都是模块级字面量，谁也没有办法在加节点的时候提醒你回来补一行 ——
`graph.add_node` 不看它们，它们也不看图。

漏掉一行不会报错，只会让界面变差一点：

- `NODE_PHASES` 缺一行，`infer_trace_phase` 落进 `postprocess` 默认档（`trace.py`），
  于是一个 planning 阶段的节点被画到时间线最后一段。
- 两张显示名表缺一行，`get_agent_display_name` / `get_step_display_name` 把英文内部
  名原样返回给界面 —— 用户看到的是 `minimum_delivery_draft_builder`。

这三件事都不会让任何测试变红，也不会写进任何日志。这一份把它们换成红灯。

真源是 `build_travel_workflow()` 构出来的图本身，不是 `node_names.py` 那份常量表：
常量表和图可能一起漂（加常量忘了 add_node，或反过来）。构图是纯构造器 —— 不连库、
不起 MCP、不发模型调用，只是把节点函数挂上去，一秒多一点，可以进单元测试。

不在图上但确实在表里的名字，逐个列在 `_NON_GRAPH_*` 里并写清它是什么。这里不做
「表里多出来的一律放过」的宽松匹配：那样等于只守一半，删掉一个节点之后表里那行
会一直留着，下一个人读表会以为这个节点还在。
"""

from __future__ import annotations

from functools import lru_cache
from typing import AbstractSet, Iterable

import pytest


@lru_cache(maxsize=1)
def _graph_node_names() -> frozenset[str]:
    """图上所有节点名 —— 深研主干加上快答那一个节点。

    缓存到模块级：构图约 1.4 秒，三条断言各构一次就没必要了。
    """

    from travel_agent.workflows.fast_answer import NODE_FAST_ANSWER
    from travel_agent.workflows.travel_planning import build_travel_workflow

    return frozenset(build_travel_workflow().nodes.keys()) | {NODE_FAST_ANSWER}


def _assert_table_covers_the_graph(
    table: Iterable[str],
    *,
    table_name: str,
    non_graph_keys: AbstractSet[str],
    consequence: str,
) -> None:
    """表的键集必须等于「图上的节点」加上「显式登记的非节点键」。

    两个方向分开报，并且把名字直接印出来 —— 一条只说「不一致」的断言，读的人还得
    自己去两个文件里对二十多个名字。
    """

    keys = set(table)
    missing = _graph_node_names() - keys
    stale = keys - _graph_node_names() - set(non_graph_keys)
    assert not missing and not stale, (
        f"{table_name} 与图上的节点不一致：\n"
        f"  图里有、表里没有（{consequence}）：{sorted(missing)}\n"
        f"  表里有、图里没有（节点被删了还是名字写错了？）：{sorted(stale)}\n"
        f"  已登记的非节点键：{sorted(non_graph_keys)}"
    )


# `workflow` 是信封级的 trace 事件源（整个 run 本身），不是图上的节点。
_NON_GRAPH_PHASE_KEYS = frozenset({"workflow"})

# `supervisor` 是 API 层自己发的一个显示名（`api/routes/chat_stream_handlers.py`
# 用它给编排事件署名），没有对应的图节点。
_NON_GRAPH_AGENT_LABEL_KEYS = frozenset({"supervisor"})

# 步骤表除了节点，还收阶段级的四个名字（编排/计划/调研/综合）。
_NON_GRAPH_STEP_LABEL_KEYS = _NON_GRAPH_AGENT_LABEL_KEYS | {
    "orchestrating",
    "planning",
    "researching",
    "synthesizing",
}


def test_trace_phase_table_covers_every_graph_node():
    """缺一行的代价：那个节点的 trace 事件被划进 postprocess，时间线画错位置。"""

    from travel_agent.workflows.trace import NODE_PHASES

    _assert_table_covers_the_graph(
        NODE_PHASES,
        table_name="workflows/trace.py 的 NODE_PHASES",
        non_graph_keys=_NON_GRAPH_PHASE_KEYS,
        consequence="这些节点的 trace 事件会落进 postprocess 默认档",
    )


@pytest.mark.xfail(
    strict=True,
    reason="四个节点还没有中文 Agent 名，表待补齐，见提交 3",
)
def test_agent_display_names_cover_every_graph_node():
    """缺一行的代价：界面上出现英文内部名。"""

    from travel_agent.utils.display_names import AGENT_DISPLAY_NAMES

    _assert_table_covers_the_graph(
        AGENT_DISPLAY_NAMES,
        table_name="utils/display_names.py 的 AGENT_DISPLAY_NAMES",
        non_graph_keys=_NON_GRAPH_AGENT_LABEL_KEYS,
        consequence="这些节点会把英文内部名原样显示给用户",
    )


@pytest.mark.xfail(
    strict=True,
    reason="四个节点还没有中文步骤名，表待补齐，见提交 3",
)
def test_step_display_names_cover_every_graph_node():
    """缺一行的代价：界面上出现英文内部名。"""

    from travel_agent.utils.display_names import STEP_DISPLAY_NAMES

    _assert_table_covers_the_graph(
        STEP_DISPLAY_NAMES,
        table_name="utils/display_names.py 的 STEP_DISPLAY_NAMES",
        non_graph_keys=_NON_GRAPH_STEP_LABEL_KEYS,
        consequence="这些节点会把英文内部名原样显示给用户",
    )
