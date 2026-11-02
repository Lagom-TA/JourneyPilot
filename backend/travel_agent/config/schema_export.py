"""从 schema 生成配置参考文档与 JSON Schema。

字段表由生成器维护：CI 跑一次生成器并要求 git diff 为空。手写的字段表会在改
默认值后过期，而过期的文档仍然显得可信。

JSON Schema 描述的是 ``config.yaml`` 的形态（而不是 ``Settings`` 的内部字段名），
所以可以直接用来校验用户的配置文件。字段表、环境变量表、默认值、取值范围自动
生成；快速开始与解释性文档手写。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple, get_args, get_origin


from .env import env_variable_name, leaf_fields
from .models import Settings

GENERATED_HEADER = (
    "<!-- 本文件由 `journeypilot config docs` 生成，不要手改。"
    "字段与默认值改在 backend/travel_agent/config/models.py。 -->"
)


def json_schema() -> Dict[str, Any]:
    """``config.yaml`` 形态的 JSON Schema。

    ``Settings`` 把 MCP 配置放在 ``mcp_servers`` 字段里，但 ``config.yaml`` 只
    接受 ``mcp.servers``（见 ``loader.build_settings``：这条路径是合并语义）。
    这里把生成结果映射成 YAML 真正接受的形状，并清掉 description 里的 Markdown
    记号——JSON Schema 会被编辑器和校验器直接展示，反引号和粗体只会变成噪音。
    """

    schema = Settings.model_json_schema(mode="validation")
    properties = schema.get("properties", {})
    mcp_servers = properties.pop("mcp_servers", None)
    if mcp_servers is not None:
        properties["mcp"] = {
            "additionalProperties": False,
            "properties": {"servers": mcp_servers},
            "title": "Mcp",
            "type": "object",
        }
    _strip_markdown(schema)
    return schema


def _strip_markdown(value: Any) -> None:
    """递归去掉 description 里的 Markdown 记号（``**`` 与反引号）。"""

    if isinstance(value, dict):
        description = value.get("description")
        if isinstance(description, str):
            value["description"] = description.replace("**", "").replace("`", "")
        for item in value.values():
            _strip_markdown(item)
    elif isinstance(value, list):
        for item in value:
            _strip_markdown(item)


def _type_name(annotation: Any) -> str:
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    origin = get_origin(annotation)
    if origin in (list, set, tuple):
        inner = ", ".join(_type_name(arg) for arg in get_args(annotation))
        return f"list[{inner}]" if inner else "list"
    if origin is dict:
        inner = ", ".join(_type_name(arg) for arg in get_args(annotation))
        return f"dict[{inner}]" if inner else "dict"
    if args and len(args) == 1:
        return _type_name(args[0])
    if args:
        return " | ".join(_type_name(arg) for arg in args)
    return getattr(annotation, "__name__", str(annotation))


def _constraint_text(field: Any) -> str:
    """字段声明的取值范围，读 Pydantic 的 metadata 而不是重写一遍。"""

    parts: List[str] = []
    for item in field.metadata:
        for attribute, label in (
            ("ge", ">="),
            ("gt", ">"),
            ("le", "<="),
            ("lt", "<"),
            ("min_length", "长度 >="),
            ("max_length", "长度 <="),
        ):
            value = getattr(item, attribute, None)
            if value is not None:
                parts.append(f"{label} {value}")
    return "，".join(parts)


def _default_text(field: Any) -> str:
    if field.default_factory is not None:
        return "（按段默认）"
    default = field.default
    if default is None:
        return "null"
    if isinstance(default, str):
        return f"`{default}`" if default else "（空）"
    return f"`{default}`"


def field_reference_markdown() -> str:
    """配置字段参考表（路径、类型、默认值、取值范围、环境变量名）。"""

    lines = [
        GENERATED_HEADER,
        "",
        "# 配置字段参考",
        "",
        "环境变量一栏为空表示这个字段只能在 `config.yaml` 里配：list / dict 字段",
        "（价格表、MCP server、CORS 来源）不提供环境变量入口 —— 用一个字符串表达",
        "一张表，需要额外的解析器和错误信息。",
        "",
        "| 字段 | 类型 | 默认值 | 取值范围 | 环境变量 |",
        "|---|---|---|---|---|",
    ]
    env_names = set(_env_capable_paths())
    for path, field in leaf_fields(Settings, include_containers=True).items():
        dotted = _YAML_SPELLING.get(path) or ".".join(path)
        env = env_variable_name(path) if path in env_names else ""
        lines.append(
            f"| `{dotted}` | {_type_name(field.annotation).replace('|', '&#124;')} | {_default_text(field)} "
            f"| {_constraint_text(field) or '—'} | {f'`{env}`' if env else '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


#: Settings 的内部字段名 → YAML 里真正被接受的写法（见 loader.build_settings）。
#: 照字段名写 `mcp_servers:` 会整体替换掉内置的 11 个 server，而不是合并。
_YAML_SPELLING = {("mcp_servers",): "mcp.servers"}


def _env_capable_paths() -> List[Tuple[str, ...]]:
    from .env import known_env_variables

    return list(known_env_variables(Settings).values())


def json_schema_text() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
