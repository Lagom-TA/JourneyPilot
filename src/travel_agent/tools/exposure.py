"""Request-local tool exposure over a policy-filtered catalog.

No execution, Gateway decisions or state persistence live here. Stable initial
ordering and append-only activation keep earlier definitions unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from ..config import ToolExposureConfig, get_settings
from ..workflows.node_names import WORKER_NODES
from .builtin_tools import SEARCH_TOOLS_NAME, build_search_tools_item
from .exposure_ledger import estimate_schema_tokens, estimate_text_tokens
from .registry import compact_catalog_items, search_tool_items

_CATALOG_HINT = (
    "【可用工具（按需激活）】\n"
    "你当前只加载了 search_tools 一个元工具，其余工具的完整定义尚未载入。需要用工具时先调用 "
    'search_tools(query="关键词") 检索并激活——支持中文（地图/航班/酒店/汇率/景点）或工具名前缀'
    "（amap_/duffel_）检索，同前缀的一组工具一次即可命中。激活后该工具当轮与后续轮次持续可用，"
    "无需重复检索；若无需任何工具可直接作答。\n候选工具（名称 — 说明）：\n"
)


def tool_name(item: dict[str, Any]) -> str:
    return str((item.get("schema") or {}).get("function", {}).get("name") or "")


@dataclass(frozen=True)
class ToolExposurePlan:
    deferred: bool
    agent: str
    tool_schemas: tuple[dict[str, Any], ...]
    catalog_prompt: str
    injected_tokens: int
    full_tokens: int
    exposed_tool_count: int
    full_tool_count: int


def apply_tool_exposure(
    available_tools: list[dict[str, Any]],
    agent_name: str,
    *,
    config: ToolExposureConfig | None = None,
) -> ToolExposurePlan:
    cfg = config if config is not None else get_settings().tool_exposure
    base_agent = re.sub(r"_r\d+$", "", agent_name)
    ordered = sorted(
        (item for item in available_tools if tool_name(item)), key=tool_name
    )
    schemas = tuple(deepcopy(item["schema"]) for item in ordered)
    full_tokens = estimate_schema_tokens(ordered)
    should_defer = (
        cfg.mode == "deferred"
        and (not cfg.worker_only or base_agent in WORKER_NODES)
        and len(schemas) >= cfg.min_tools_threshold
    )
    if not should_defer:
        return ToolExposurePlan(
            False,
            base_agent,
            schemas,
            "",
            full_tokens,
            full_tokens,
            len(schemas),
            len(schemas),
        )
    search = build_search_tools_item()
    catalog = compact_catalog_items(ordered)
    prompt = _CATALOG_HINT + "\n".join(
        f"- {row['name']}" + (f" — {row['brief']}" if row.get("brief") else "")
        for row in catalog
    )
    return ToolExposurePlan(
        True,
        base_agent,
        (deepcopy(search["schema"]),),
        prompt,
        estimate_schema_tokens([search]) + estimate_text_tokens(prompt),
        full_tokens,
        1,
        len(schemas),
    )


class ToolExposureSession:
    """Own the active schemas for exactly one ReAct invocation."""

    def __init__(
        self, available_tools: list[dict[str, Any]], plan: ToolExposurePlan
    ) -> None:
        self.plan = plan
        self._available = deepcopy(available_tools)
        self._schemas = list(deepcopy(plan.tool_schemas))
        self._activated: set[str] = set()

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return deepcopy(self._schemas)

    def was_activated(self, name: str) -> bool:
        return name in self._activated

    @property
    def activated_names(self) -> list[str]:
        return [schema["function"]["name"] for schema in self._schemas
                if schema["function"]["name"] in self._activated]

    def restore(self, names: list[str]) -> None:
        """Replay definition order, still bounded by the current allowlist."""
        allowed = {tool_name(item): item for item in self._available}
        for name in names:
            if name not in allowed:
                raise ValueError("recovered tool exposure exceeds current allowlist")
            if self.plan.deferred and name not in self._activated:
                self._activated.add(name)
                self._schemas.append(deepcopy(allowed[name]["schema"]))

    def activate(self, query: str) -> dict[str, Any]:
        if not self.plan.deferred:
            return {
                "success": True,
                "activated": [],
                "catalog": [],
                "note": "完整工具定义已加载，可直接调用。",
            }
        matches = sorted(
            search_tool_items(query, self._available, exclude=self._activated),
            key=tool_name,
        )
        newly = []
        for item in matches:
            name = tool_name(item)
            if name and name != SEARCH_TOOLS_NAME and name not in self._activated:
                self._activated.add(name)
                self._schemas.append(deepcopy(item["schema"]))
                newly.append(name)
        return {
            "success": True,
            "activated": newly,
            "catalog": compact_catalog_items(matches),
            "note": (
                f"已激活 {len(newly)} 个工具，现在可直接调用。"
                if newly
                else "未匹配到新工具，请更换关键词，或直接基于已有信息作答。"
            ),
        }


def attach_tool_catalog(
    messages: list[dict[str, Any]], plan: ToolExposurePlan
) -> list[dict[str, Any]]:
    """Place the static catalog before history/runtime, without changing callers."""
    assembled = [dict(message) for message in messages]
    if plan.catalog_prompt:
        if assembled and assembled[0].get("role") == "system":
            content = str(assembled[0].get("content") or "")
            if content != plan.catalog_prompt and not content.endswith(
                "\n\n" + plan.catalog_prompt
            ):
                assembled[0]["content"] = content + "\n\n" + plan.catalog_prompt
        else:
            assembled.insert(0, {"role": "system", "content": plan.catalog_prompt})
    return assembled
