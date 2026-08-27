"""三个 research worker 的提示词是硬合同，这里给它上守卫。

``build_research_packet_system_prompt`` 是纯函数：十个关键字参数进去，一整段
f-string 出来，此前零测试。而它印出来的那段字不是文档——主 worker 调用不带
``response_format``，直连 DeepSeek 拒 ``response_format=json_schema``，
``models/router.py`` 把它降级成 ``json_object`` 并把 schema 复述成 prose
（见 ``research_packet_output._closed_definitions`` 的 docstring：
"The schema text is therefore the entire contract the model reads"）。所以改一个字
就是改模型读到的合同，而在此之前没有任何东西会因此变红。

这里有四类守卫：

1. 快照比对——提示词改了必须在 diff 里出现（生成器：``journeypilot prompts snapshot``）
2. 三方相等——散文里的数、``packet_candidate_limit`` 和响应 schema 的 maxItems
3. ``_SCOPES`` 的占位符——那句 ``.format()`` 只吃一个键，别的键会在运行期炸
4. 一条 xfail，盖住已知的 6 与 4 不一致
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

import pytest

from travel_agent.agents import research_packet_prompt
from travel_agent.agents.research_packet_output import (
    _research_packet_response_schema,
    packet_candidate_limit,
)
from travel_agent.cli.prompt_snapshot import (
    SCHEMA_PLACEHOLDER,
    WORKER_KINDS,
    fixture_dir,
    render_system_prompt,
    snapshot_artifacts,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def response_schema_candidate_limit(worker_kind: str) -> int:
    """同一次调用的响应 schema 对候选数的上限（赋值点：research_packet_output.py:3056）。"""

    schema = _research_packet_response_schema(worker_kind)
    return schema["properties"]["candidates"]["maxItems"]

# 散文里说出候选上限的三个位置，各配一条正则。它们分别对应
# research_packet_prompt.py 里 `_SCOPES` 的那句、`<hard_contract>` 里"本 Packet
# 最多输出"那条、和"不用低质量候选凑满"那条。
_LIMIT_SITES = {
    "domain_scope": re.compile(r"合格候选动态 1 至 (\d+) 个"),
    "hard_contract_max": re.compile(r"本 Packet 最多输出 (\d+) 个有直接外部支持"),
    "hard_contract_no_padding": re.compile(r"不用低质量候选凑满 (\d+) 个"),
}


# --- 快照比对 ------------------------------------------------------------- #


def test_committed_prompt_snapshots_are_current():
    """改了模型读到的合同却没人看见，不能合入。"""

    target = fixture_dir(_REPO_ROOT)
    for name, expected in snapshot_artifacts().items():
        path = target / name
        relative = path.relative_to(_REPO_ROOT)
        assert path.exists(), (
            f"{relative} 缺失：跑 `journeypilot prompts snapshot` 并提交"
        )
        assert path.read_text(encoding="utf-8") == expected, (
            f"{relative} 与当前提示词代码不一致："
            "跑 `journeypilot prompts snapshot` 并提交"
        )


@pytest.mark.parametrize("worker_kind", WORKER_KINDS)
def test_the_schema_is_injected_verbatim_not_summarized(worker_kind):
    """schema 段必须逐字注入，快照里只留占位符。

    ``render_system_prompt`` 内部断言 schema 文本逐字出现，出现了才替换成占位符。
    占位符出现在结果里，就等于那条断言过了——schema 内容本身由 ``ResearchPacket``
    的类型定义管，不该让三份散文快照跟着 churn。
    """

    rendered = render_system_prompt(worker_kind)
    assert rendered.count(SCHEMA_PLACEHOLDER) == 1
    assert rendered.rstrip().endswith(f"<json_schema>{SCHEMA_PLACEHOLDER}</json_schema>")


# --- 三方相等 ------------------------------------------------------------- #


@pytest.mark.parametrize("worker_kind", WORKER_KINDS)
def test_prose_limit_matches_the_function_and_the_response_schema(worker_kind):
    """散文里的候选上限、``packet_candidate_limit`` 与 schema 的 maxItems 三者相等。

    不写「散文里的数等于入参」：``{candidate_limit}`` 是 f-string 插值，不可能对实参
    说谎，那条断言近乎同义反复。真正会分叉的是这三样——提示词曾经说"最多输出 4 个"
    而同一次调用的 schema 强制 3。
    """

    prompt = render_system_prompt(worker_kind)
    expected = packet_candidate_limit(worker_kind)

    found = {}
    for site, pattern in _LIMIT_SITES.items():
        matches = pattern.findall(prompt)
        if matches:
            found[site] = {int(value) for value in matches}

    # `_SCOPES` 只有 accommodation 那条写了 {candidate_limit}，所以 domain_scope
    # 这个位点是按模板有没有占位符来决定该不该出现的，不是无条件三处。
    scope_template = research_packet_prompt._SCOPES[worker_kind]
    expected_sites = {"hard_contract_max", "hard_contract_no_padding"}
    if "{candidate_limit}" in scope_template:
        expected_sites.add("domain_scope")
    assert set(found) == expected_sites, (
        f"{worker_kind} 说出候选上限的位置变了：这些位点是模型读到的数字，"
        "少一个就是少一条约束"
    )

    # 位点彼此相等，且等于函数，且等于同一次调用的响应 schema。
    values = {value for site_values in found.values() for value in site_values}
    assert values == {expected}, (
        f"{worker_kind} 的散文里出现了不一致的候选上限：{sorted(values)}"
    )
    assert response_schema_candidate_limit(worker_kind) == expected


# --- `_SCOPES` 的占位符守卫 ------------------------------------------------ #


def _placeholders(template: str) -> set[str]:
    """模板里的花括号占位符名。裸括号会让 ``Formatter.parse`` 直接抛。"""

    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name is not None
    }


@pytest.mark.parametrize("worker_kind", WORKER_KINDS)
def test_scope_templates_only_take_candidate_limit(worker_kind):
    """``_SCOPES`` 里除 ``candidate_limit`` 不许有别的占位符，也不许有裸括号。

    ``research_packet_prompt.py`` 里 ``<domain>`` 那行对 ``_SCOPES[worker_kind]``
    调 ``.format(candidate_limit=...)``，只喂这一个键。往 scope 里贴一段带裸 ``{``
    的 JSON 示例，``.format()`` 会当场抛——而且是抛在授权之后、模型窗口已经开着的
    时候，不是启动期。
    """

    template = research_packet_prompt._SCOPES[worker_kind]
    assert _placeholders(template) <= {"candidate_limit"}, (
        f"{worker_kind} 的 scope 模板出现了 candidate_limit 以外的占位符"
    )
    # 真调一次：占位符名对了但括号不配对，只有 format 本身能发现。
    template.format(candidate_limit=packet_candidate_limit(worker_kind))


@pytest.mark.parametrize(
    "bad_scope",
    [
        # 一段 JSON 示例——最可能被顺手贴进 scope 的东西。
        '具体 VisitCandidate；示例：{"candidate_kind": "visit"}',
        # 括号不配对：占位符名单看不出问题，只有 .format() 本身能发现。
        "具体 VisitCandidate；上限 {candidate_limit 个",
        # 名字对不上：.format() 只喂 candidate_limit 一个键。
        "具体 VisitCandidate；上限 {candidate_ceiling} 个",
    ],
    ids=["json_example", "unbalanced_brace", "unknown_key"],
)
def test_a_bad_scope_template_is_caught(monkeypatch, bad_scope):
    """守卫得有牙：这三种写法都必须让上面那条红。

    没有这条，占位符守卫可能只是恒真。三种失败各走不同出口——占位符名单、
    ``Formatter.parse`` 抛的 ValueError、``.format()`` 抛的 KeyError——所以这里接住
    的是一组异常而不是一个。
    """

    monkeypatch.setitem(
        research_packet_prompt._SCOPES, "destination_researcher", bad_scope
    )
    with pytest.raises((AssertionError, KeyError, ValueError, IndexError)):
        test_scope_templates_only_take_candidate_limit("destination_researcher")


def test_a_bad_scope_template_also_breaks_the_real_prompt(monkeypatch):
    """而且它在真实调用路径上炸，不只是在测试里。

    这就是这条守卫存在的理由：``<domain>`` 那行的 ``.format()`` 跑在授权之后、模型
    窗口已经开着的时候，抛在那里比抛在启动期贵得多。
    """

    monkeypatch.setitem(
        research_packet_prompt._SCOPES,
        "destination_researcher",
        '具体 VisitCandidate；示例：{"candidate_kind": "visit"}',
    )
    with pytest.raises((KeyError, ValueError, IndexError)):
        render_system_prompt("destination_researcher")


# --- 已知不一致 ----------------------------------------------------------- #


@pytest.mark.xfail(
    reason="node.py:296 的 6 与 packet_candidate_limit 的 4 不一致，属行为决策",
    strict=True,
)
def test_destination_repair_task_prompt_agrees_with_the_packet_limit():
    """定向补研 task prompt 说"1 至 6 个"，同一次调用的 system prompt 说 4。

    改成 4 是改模型读到的指令，是行为票不是重构票，所以这里只把不一致钉住。有人改
    对的那天这条会 XPASS 报出来。
    """

    from travel_agent.agents.destination_researcher.node import (
        build_destination_task_prompt,
    )

    prompt = build_destination_task_prompt(
        task_desc="补齐东京 Visit/Dining 候选的身份字段",
        user_query="想看当代建筑",
        rag_context_section="",
        require_current_candidate=True,
        offered_dining_place_ids=[],
    )
    matched = re.search(r"动态保留 1 至 (\d+) 个身份完整", prompt)
    assert matched is not None
    assert int(matched.group(1)) == packet_candidate_limit("destination_researcher")
