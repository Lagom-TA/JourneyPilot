"""AST 守卫共用基础设施。

三条守卫（B1 import 面 / A6 字段写点 / B2 state 写面）共用的部分：
文件遍历与解析、父链上下文遍历、相对导入解析、vacuity 断言。
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

ROOT_PACKAGE = "travel_agent"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def iter_python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def walk_with_function_context(root: ast.AST) -> Iterator[tuple[ast.AST, bool]]:
    """按父链产出 (节点, 是否在函数体内)。

    ``ast`` 没有 parent 指针，遍历时自己带上下文：``FunctionDef`` /
    ``AsyncFunctionDef`` 子树内即视为函数内；类体不改变标记。
    """

    def walk(node: ast.AST, in_function: bool) -> Iterator[tuple[ast.AST, bool]]:
        for child in ast.iter_child_nodes(node):
            child_flag = in_function or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
            yield child, child_flag
            yield from walk(child, child_flag)

    yield from walk(root, False)


def iter_body_nodes(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    """函数体内全部节点；嵌套函数与 lambda 只到其本身，不下钻。"""

    stack: list[ast.AST] = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def find_def(
    tree: ast.AST, name: str, line: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
            and node.lineno == line
        ):
            return node
    return None


def package_root(package_dir: Path) -> Path:
    """找到相对导入的锚点包，断言它就叫 ``travel_agent``。

    不沿 ``__init__.py`` 盲目上爬：本仓 ``src/`` 自己带一个 ``__init__.py``，
    爬过头会把所有相对导入解析成 ``src.travel_agent.*``。
    """

    root = package_dir
    while root.name != ROOT_PACKAGE and (root.parent / "__init__.py").exists():
        root = root.parent
    assert root.name == ROOT_PACKAGE, (
        f"{package_dir} 不在 {ROOT_PACKAGE} 包之下，相对导入无从解析"
    )
    return root


def dotted_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([root.name, *parts])


def relative_import_target(
    dotted: str, is_init: bool, level: int, module: str | None
) -> str:
    """把相对导入解析成绝对 dotted 落点，按文件真实深度算。

    ``__init__.py`` 里 ``from .`` 指的是包自己，比普通文件少升一层。
    """

    parts = dotted.split(".")
    up = level - 1 if is_init else level
    base = parts[: len(parts) - up]
    if not base:
        raise ValueError(f"相对导入越过了顶层包：{dotted} level={level}")
    return ".".join([*base, *module.split(".")]) if module else ".".join(base)


def dotted_module_path(dotted: str) -> Path | None:
    """``travel_agent.x.y`` → ``src/travel_agent/x/y.py``（或包的 ``__init__.py``）。"""

    base = repo_root() / "src" / Path(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def assert_scan_floor(actual: int, floor: int, what: str) -> None:
    """扫到的数量必须与仓库规模相称，否则扫描器自己坏了，守卫恒绿。"""

    assert actual >= floor, f"只扫到 {actual} 个{what}，不该这么少——路径或解析器多半坏了"


def assert_sentinels(found: set[str], sentinels: set[str], what: str) -> None:
    missing = sentinels - found
    assert not missing, f"关键{what}缺席：{sorted(missing)}"
