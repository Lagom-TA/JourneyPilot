"""YAML + 环境变量 → `Settings`，以及「这个值是从哪来的」。

加载顺序固定：

    找到 config.yaml → 严格校验 → 环境变量覆盖 → 生成 effective config（脱敏）

严格校验在环境变量之前：一个拼错的 YAML 字段要在它有机会被环境变量掩盖之前报出来。

错误信息必须能直接照着改：字段路径、当前值、合法范围。**不许**把 api_key 写进任何
一条错误或日志（`redaction.py`）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from .env import EnvOverrideError, apply_env_overrides, known_env_variables
from .models import MCPServerItem, ModelPricingItem, Settings
from .pricing import resolve_price_in
from .redaction import redact

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """配置读不成一份合法的 `Settings`。"""


def find_config_yaml() -> Optional[Path]:
    """按 ``CONFIG_PATH`` → 向上查找 → 当前目录 定位 config.yaml。

    ``CONFIG_PATH`` 不带 ``JOURNEYPILOT_`` 前缀：它回答的不是「哪个字段是多少」，
    而是「去哪读那份文件」—— 在配置被加载之前就得知道，所以它不能是配置项。
    """

    env_path = os.getenv("CONFIG_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate
        raise ConfigError(f"CONFIG_PATH 指向的文件不存在：{env_path}")

    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    candidate = Path("config.yaml")
    return candidate if candidate.exists() else None


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _describe_validation_error(exc: ValidationError, path: Optional[Path]) -> str:
    """把 Pydantic 的报错变成一条能照着改的话：字段路径、当前值、合法范围。"""

    location = f"（{path}）" if path else ""
    lines = [f"config.yaml 校验未通过{location}："]
    for error in exc.errors():
        dotted = ".".join(str(part) for part in error["loc"]) or "<root>"
        given = error.get("input")
        if any(marker in dotted.lower() for marker in ("api_key", "password", "secret", "token")):
            given = "<redacted>"
        lines.append(f"  {dotted}: {error['msg']}（当前值 {given!r}）")
    lines.append("  字段清单：docs/configuration.md（journeypilot config docs 生成）")
    return "\n".join(lines)


def build_settings(data: Dict[str, Any], *, path: Optional[Path] = None) -> Settings:
    """严格校验一份 YAML 数据。

    ``mcp.servers`` 与 `Settings` 其余部分不同：它是**合并**语义而不是替换 ——
    用户通常只在 YAML 里填 env，command/args/required_env 要保留内置默认，否则
    健康检查会因为 ``required_env=[]`` 漏报配置缺失。
    """

    payload = dict(data)
    if "mcp_servers" in payload:
        # 顶层字段会整体替换内置默认，导致对应 MCP 服务器没有启动命令、其工具无法注册。
        # 只有 `mcp.servers` 会与内置默认合并。
        raise ConfigError(
            "config.yaml 顶层不接受 `mcp_servers`，改写成 `mcp:` → `servers:`："
            "只有那条路会与内置的 MCP 默认合并（照字段名写会把它们整体替换掉）。"
        )
    mcp_section = payload.pop("mcp", None) or {}
    try:
        settings = Settings.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(_describe_validation_error(exc, path)) from exc

    servers = mcp_section.get("servers") if isinstance(mcp_section, dict) else None
    if isinstance(servers, dict):
        for name, override in servers.items():
            if not isinstance(override, dict):
                raise ConfigError(f"mcp.servers.{name}: 应当是一组字段，实际 {override!r}")
            try:
                if name in settings.mcp_servers:
                    merged = settings.mcp_servers[name].model_dump()
                    merged.update({k: v for k, v in override.items() if v is not None})
                    settings.mcp_servers[name] = MCPServerItem.model_validate(merged)
                else:
                    settings.mcp_servers[name] = MCPServerItem.model_validate(override)
            except ValidationError as exc:
                raise ConfigError(_describe_validation_error(exc, path)) from exc
    return settings


def _apply_mcp_native_env(settings: Settings) -> None:
    """MCP provider 的原生 Key 名按原名读，传给子进程。不走 JOURNEYPILOT_ 前缀。"""

    for server in settings.mcp_servers.values():
        merged = dict(server.env or {})
        for key in server.required_env:
            value = os.getenv(key)
            if value:
                merged[key] = value
        server.env = merged or None


@dataclass
class EffectiveConfig:
    """当前生效的配置，以及每个值的来源。

    这一份直接回答「我改了 YAML 为什么没生效」：来源里写着 environment 的字段，
    改 YAML 不会有任何效果。
    """

    settings: Settings
    config_path: Optional[Path]
    #: 字段路径 → "config default" | "config.yaml" | "environment (VAR)"
    sources: Dict[str, str] = field(default_factory=dict)

    def source_of(self, dotted: str) -> str:
        return self.sources.get(dotted, "config default")

    def redacted(self) -> Dict[str, Any]:
        return redact(self.settings.model_dump(mode="json"))

    def report_lines(self) -> List[str]:
        """``journeypilot config show --effective`` 打的那些行。"""

        lines: List[str] = []
        for dotted, value in sorted(_flatten(self.redacted()).items()):
            lines.append(f"{dotted} = {value}    source={self.source_of(dotted)}")
        return lines


def _flatten(payload: Any, prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if isinstance(payload, dict):
        for name, item in payload.items():
            flat.update(_flatten(item, f"{prefix}.{name}" if prefix else str(name)))
    elif isinstance(payload, list):
        flat[prefix] = f"[{len(payload)} 项]"
    else:
        flat[prefix] = payload
    return flat


def _yaml_sources(data: Dict[str, Any]) -> Dict[str, str]:
    return {dotted: "config.yaml" for dotted in _flatten(data)}


def load_effective_config() -> EffectiveConfig:
    """完整走一遍加载顺序，带来源。"""

    path = find_config_yaml()
    payload = load_yaml(path) if path else {}
    settings = build_settings(payload, path=path)
    sources = _yaml_sources(payload)
    try:
        applied = apply_env_overrides(settings)
    except EnvOverrideError as exc:
        # 环境变量的问题与 YAML 的问题对调用方是同一件事：配置读不成一份合法的
        # Settings。收敛成同一个异常，CLI 与启动路径才只需要处理一种。
        raise ConfigError(str(exc)) from exc
    for dotted, variable in applied:
        sources[dotted] = f"environment ({variable})"
    _apply_mcp_native_env(settings)
    return EffectiveConfig(
        settings=settings,
        config_path=path,
        sources=sources,
    )


_effective: Optional[EffectiveConfig] = None


def get_effective_config() -> EffectiveConfig:
    global _effective
    if _effective is None:
        _effective = load_effective_config()
    return _effective


def get_settings() -> Settings:
    """全局配置单例。"""

    return get_effective_config().settings


def reload_settings() -> Settings:
    global _effective
    _effective = None
    return get_settings()


def resolve_price(
    model: Optional[str],
    provider: Optional[str] = None,
    *,
    pricing: Optional[List[ModelPricingItem]] = None,
) -> Optional[ModelPricingItem]:
    """按 (model, provider) 查一条价格；未命中返回 None（→ 只报 token 不编造成本）。"""

    table = pricing if pricing is not None else get_settings().model_pricing
    return resolve_price_in(table, model, provider)


def _write_yaml_section(section: Dict[str, Any]) -> Path:
    """把一组配置段合并写回 config.yaml，返回被写的路径。"""

    path = find_config_yaml()
    if not path:
        raise FileNotFoundError("config.yaml 未找到，先从 backend/config.example.yaml 复制一份")
    data = load_yaml(path)
    for name, values in section.items():
        existing = data.get(name)
        if isinstance(existing, dict):
            existing.update(values)
            data[name] = existing
        else:
            data[name] = values
    with open(path, "w", encoding="utf-8") as handle:
        yaml.dump(data, handle, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return path


def persist_model_config(tier: str, model_data: Dict[str, Any]) -> None:
    """把一个档位的模型配置写回 config.yaml。"""

    key = "primary_model" if tier == "primary" else "fast_model"
    _write_yaml_section({key: model_data})


def write_model_section(section: Dict[str, Any]) -> Path:
    """把一份 provider preset 的模型段写回 config.yaml，返回被写的路径。"""

    return _write_yaml_section(section)


def env_variable_reference() -> Dict[str, str]:
    """所有合法环境变量名 → 它覆盖的字段路径。文档与 CLI 共用这一份。"""

    return {name: ".".join(path) for name, path in known_env_variables(Settings).items()}
