"""研究 Worker 与合成阶段共享的命名运行时上下文。

各领域的格式化由对应模块负责；装配只决定顺序，不裁剪受控约束，也不修改持久状态。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextSection:
    name: str
    text: str


def agent_context_sections(
    state: Any, agent_label: str = ""
) -> tuple[ContextSection, ...]:
    sections = []
    if getattr(state, "session_anchor", None):
        try:
            from .compressor import AnchorSummary

            text = AnchorSummary.from_dict(state.session_anchor).format_for_prompt()
            if text:
                sections.append(
                    ContextSection("session_anchor", f"【历史对话摘要】\n{text}")
                )
        except Exception as exc:
            logger.debug("%s AnchorSummary 注入失败: %s", agent_label or "agent", exc)
    if getattr(state, "preset_context", None):
        try:
            from travel_agent.conversation.preset_context import PresetInjector

            text = PresetInjector.format_for_agent(state.preset_context)
            if text:
                sections.append(ContextSection("preset", text))
        except Exception as exc:
            logger.debug("%s Preset 上下文注入失败: %s", agent_label or "agent", exc)
    if getattr(state, "constraint_pack", None):
        from travel_agent.planning.requirements.constraints.presentation import format_constraint_pack_for_prompt

        text = format_constraint_pack_for_prompt(state.constraint_pack)
        if text:
            sections.append(ContextSection("constraints", text))
    if getattr(state, "weather_context", None) is not None:
        from travel_agent.planning.weather.presentation import format_weather_context_for_planning

        text = format_weather_context_for_planning(state)
        if text:
            sections.append(ContextSection("weather", text))
    return tuple(sections)


def render_agent_context(state: Any, agent_label: str = "") -> str:
    return "\n\n".join(
        section.text for section in agent_context_sections(state, agent_label)
    )
