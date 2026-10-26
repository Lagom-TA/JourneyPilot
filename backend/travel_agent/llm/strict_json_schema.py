"""严格结构化输出子集的判定与改写。

合法性只由 :func:`strict_schema_violations` 判定；:func:`as_strict_schema`
把 ``oneOf`` 改为 ``anyOf``、移除 ``discriminator`` 并补全 ``required``。
``additionalProperties`` 非 ``False`` 的自由映射等无法在此改写，会抛出
:class:`StrictSchemaError`。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# 子集允许的字符串 format；其他 format 会被拒绝而不是忽略，因此计为违规。
PERMITTED_STRING_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "ipv4",
        "ipv6",
        "uuid",
    }
)

# 子集不支持的关键字。子集没有组合关键字，需要 ``allOf`` 的 schema
# 必须在声明处展开。
_FORBIDDEN_KEYWORDS = ("oneOf", "allOf", "discriminator")


class StrictSchemaError(ValueError):
    """schema 无法用严格结构化输出子集表达。"""


@dataclass(frozen=True)
class StrictSchemaViolation:
    """schema 不符合子集的一条原因。"""

    path: str
    rule: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - diagnostic formatting
        return f"{self.path}: {self.rule} ({self.detail})"


def _is_object_node(node: Dict[str, Any]) -> bool:
    return node.get("type") == "object" or "properties" in node


def strict_schema_violations(schema: Any) -> Tuple[StrictSchemaViolation, ...]:
    """返回 ``schema`` 会被严格供应商拒绝的全部原因。

    只有返回空元组才表示 schema 可用；调用方不能把未抛异常当作合法。
    """

    violations: List[StrictSchemaViolation] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if _is_object_node(node):
                additional = node.get("additionalProperties")
                if additional is not False:
                    violations.append(
                        StrictSchemaViolation(
                            path, "additionalProperties", repr(additional)
                        )
                    )
                required = set(node.get("required", []))
                missing = [
                    name for name in node.get("properties", {}) if name not in required
                ]
                if missing:
                    violations.append(
                        StrictSchemaViolation(path, "required", ", ".join(missing))
                    )
            for key, child in node.items():
                if key in _FORBIDDEN_KEYWORDS:
                    violations.append(
                        StrictSchemaViolation(path, key, _describe(child))
                    )
                elif key == "format" and child not in PERMITTED_STRING_FORMATS:
                    violations.append(
                        StrictSchemaViolation(path, "format", str(child))
                    )
                walk(child, f"{path}/{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")

    walk(schema, "#")
    return tuple(violations)


def _describe(value: Any) -> str:
    if isinstance(value, list):
        return f"{len(value)} branch(es)"
    if isinstance(value, dict):
        return ", ".join(sorted(value.get("mapping", {}))) or "mapping"
    return str(value)


def as_strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """把 ``schema`` 改写为严格子集。

    改写后仍有违规（自由映射、不支持的 ``format``、``allOf`` 等）时抛出
    :class:`StrictSchemaError`；这些问题需要在声明模型处修复。
    """

    rewritten = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            branches = node.pop("oneOf", None)
            if branches is not None:
                node["anyOf"] = branches
            node.pop("discriminator", None)
            if _is_object_node(node):
                node["required"] = list(node.get("properties", {}))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(rewritten)
    remaining = strict_schema_violations(rewritten)
    if remaining:
        raise StrictSchemaError(
            "schema cannot be expressed in the strict structured-output subset: "
            + "; ".join(str(violation) for violation in remaining)
        )
    return rewritten
