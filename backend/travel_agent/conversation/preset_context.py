"""
Preset 注入器（Domain Layer）。
将旅行风格预设的指令和约束转换为可注入 Agent prompt 的上下文文本。
"""

from __future__ import annotations

from typing import Dict

from travel_agent.planning.requirements.preset_contracts import TravelPreset

PRESET_PACK_CONSTRAINT_CATEGORIES: Dict[str, str] = {
    "pace": "pace_preference",
    "budget": "budget_cap",
}


class PresetInjector:
    """将 Preset 转换为 Agent prompt 上下文"""

    @staticmethod
    def build_context(preset: TravelPreset) -> str:
        """节奏与预算只交给 Constraint Pack 仲裁，不写入自由文本。"""
        parts = [f"[当前启用预设: {preset.name}]"]
        parts.append(f"预设描述: {preset.description}")
        parts.append(f"\n{preset.instructions}")

        c = preset.constraints
        constraint_parts = []
        if c.duration:
            constraint_parts.append(f"建议时长: {c.duration}")
        if c.focus_areas:
            constraint_parts.append(f"重点关注: {', '.join(c.focus_areas)}")
        if c.output_style:
            constraint_parts.append(f"输出格式偏好: {c.output_style}")

        if constraint_parts:
            parts.append("\n结构化约束:")
            for cp in constraint_parts:
                parts.append(f"- {cp}")

        return "\n".join(parts)

    @staticmethod
    def pack_constraints(preset: TravelPreset) -> Dict[str, str]:
        """Preset 里交给 Constraint Pack 执行的那几项：``category -> 原文``。"""
        constraints = preset.constraints
        mapped: Dict[str, str] = {}
        for field_name, category in PRESET_PACK_CONSTRAINT_CATEGORIES.items():
            value = str(getattr(constraints, field_name, "") or "").strip()
            if value:
                mapped[category] = value
        return mapped

    @staticmethod
    def _wrap_active_preset(prompt: str, preset_context: str) -> str:
        """保持闭合 XML 标签完整；字段契约已约束内容。"""
        if not preset_context:
            return ""
        return f"\n<active_preset>\n{prompt}\n{preset_context}\n</active_preset>"

    @staticmethod
    def format_for_agent(preset_context: str) -> str:
        """为最终输出 Agent（FastAnswer / Synthesizer）格式化"""
        return PresetInjector._wrap_active_preset(
            "请严格按照以下风格预设的指令来组织你的回答：",
            preset_context,
        )
