from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple, get_args, get_origin

from pydantic import BaseModel, ValidationError

ENV_PREFIX = "JOURNEYPILOT_"
ENV_SEPARATOR = "__"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class EnvOverrideError(ValueError):
    """一个环境变量指向了不存在的字段，或者它的值不是那个字段的类型。"""


def leaf_fields(
    model: type[BaseModel],
    prefix: Tuple[str, ...] = (),
    *,
    include_containers: bool = False,
) -> Dict[Tuple[str, ...], Any]:
    # 容器字段可列入文档，但不能通过单个环境变量赋值。

    paths: Dict[Tuple[str, ...], Any] = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        # 容器里的模型不是可逐层赋值的字段，必须先排除容器再递归。
        if _is_container(annotation):
            if include_containers:
                paths[(*prefix, name)] = field
            continue
        nested = _unwrap_model(annotation)
        if nested is not None:
            paths.update(
                leaf_fields(nested, (*prefix, name), include_containers=include_containers)
            )
            continue
        paths[(*prefix, name)] = field
    return paths


def _unwrap_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def _is_container(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in (list, dict, set, tuple):
        return True
    return any(get_origin(arg) in (list, dict, set, tuple) for arg in get_args(annotation))


def _coerce(raw: str, annotation: Any, path: str) -> Any:
    """把字符串按字段注解转成值。转不了是错误，不是回落到默认。"""

    target = annotation
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if args:
        target = args[0]
    if target is bool:
        lowered = raw.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise EnvOverrideError(
            f"{path}: 期望布尔值（{'/'.join(sorted(_TRUE | _FALSE))}），实际 {raw!r}"
        )
    if target is int:
        try:
            return int(raw.strip())
        except ValueError as exc:
            raise EnvOverrideError(f"{path}: 期望整数，实际 {raw!r}") from exc
    if target is float:
        try:
            return float(raw.strip())
        except ValueError as exc:
            raise EnvOverrideError(f"{path}: 期望数字，实际 {raw!r}") from exc
    return raw


def env_variable_name(path: Tuple[str, ...]) -> str:
    return ENV_PREFIX + ENV_SEPARATOR.join(part.upper() for part in path)


def known_env_variables(model: type[BaseModel]) -> Dict[str, Tuple[str, ...]]:
    """所有合法环境变量名 → 它对应的字段路径。文档生成与校验都读它。"""

    return {env_variable_name(path): path for path in leaf_fields(model)}


def apply_env_overrides(settings: BaseModel) -> List[Tuple[str, str]]:
    """按环境变量覆盖 ``settings``，返回 [(字段路径, 变量名)] 供来源报告使用。

    覆盖是**就地**写的（配置对象是可变的 Pydantic 模型），因为调用方持有的就是这一个
    单例；返回一份新对象会让「谁是当前配置」多出一个答案。
    """

    known = known_env_variables(type(settings))
    annotations = {
        env_variable_name(path): field.annotation
        for path, field in leaf_fields(type(settings)).items()
    }
    applied: List[Tuple[str, str]] = []
    unknown: List[str] = []

    for name, raw in sorted(os.environ.items()):
        if not name.startswith(ENV_PREFIX):
            continue
        path = known.get(name)
        if path is None:
            unknown.append(name)
            continue
        dotted = ".".join(path)
        value = _coerce(raw, annotations[name], dotted)
        target: Any = settings
        for part in path[:-1]:
            target = getattr(target, part)
        setattr(target, path[-1], value)
        applied.append((dotted, name))

    if unknown:
        listed = ", ".join(unknown)
        raise EnvOverrideError(
            f"认不出这些环境变量：{listed}。"
            f"合法名称形如 {env_variable_name(('database', 'port'))}；"
            "完整清单见 `journeypilot config env`。"
        )

    if applied:
        _revalidate(settings, applied)
    return applied


def _revalidate(settings: BaseModel, applied: List[Tuple[str, str]]) -> None:
    """覆盖写完之后整体重校验一次。

    ``setattr`` 不触发 Field 约束和 ``model_validator``（模型没开
    ``validate_assignment``），所以 ``LEASE_SECONDS=0`` 这类值会直接落进配置。逐次赋值
    校验也不行：四段 deadline 一起调高时，中间那次赋值必然是乱序的。
    """

    try:
        type(settings).model_validate(settings.model_dump())
    except ValidationError as exc:
        names = ", ".join(name for _, name in applied)
        raise EnvOverrideError(
            f"环境变量覆盖之后配置不合法（本次覆盖：{names}）：{exc}"
        ) from exc
