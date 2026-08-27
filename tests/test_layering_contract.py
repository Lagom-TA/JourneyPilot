"""entities 层的 import 面守卫：只依赖标准库、第三方库、entities 内部和白名单例外。

为什么是白名单而不是黑名单（禁止 agents/workflows/api 之类）？

1. 黑名单是空转：只要扫描器什么都没收集到，「没见到禁止对象」就永远通过 ——
   一个恒绿的门禁比没有门禁更贵。
2. 更根本的是，本仓没有定义过层次序。``src/travel_agent/`` 下有 17 个包
   （agents / api / cli / config / db / entities / guardrails / infrastructure /
   memory / models / panels / preset / rag / services / tools / utils / workflows）
   和 3 个顶层模块（builders / capabilities / local_profile），没有任何文档写明
   它们谁在谁之上，所以「禁止依赖更高层」这类断言没有可引用的序。

所以契约直接写成白名单：entities 只依赖标准库、第三方库和 entities 内部，
5 条例外逐项列出并各写理由。例外物理地分成两张表，因为下一个人必须能分清
哪一条槽位是他能加的：

- ``_PERMANENT_DEFERRED_EXCEPTIONS``：永久例外，且必须是**函数内延迟导入**。
  这是设计意图（见 ``run_deadline_policy.py:27-28`` 的自陈注释），不是历史包袱；
  哪天它变成模块级，守卫红。
- ``_MODULE_LEVEL_CURRENT_STATE``：当前状态，容忍的是模块级导入。新增一条就红，
  改的人得来这里写理由，并借此机会决定它是否配得上永久化。

遍历基础设施在 ``tests/_ast_support.py``（A6 的写点守卫、B2 的 state 写面守卫共用）；
本文件的 ``scan_imports`` 只回答「谁在 import 谁、是模块级还是函数内」。
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tests._ast_support import (
    assert_scan_floor,
    assert_sentinels,
    dotted_name,
    iter_python_files,
    package_root,
    parse_file,
    relative_import_target,
    walk_with_function_context,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENTITIES_DIR = _REPO_ROOT / "src" / "travel_agent" / "entities"
_ROOT_PACKAGE = "travel_agent"
_ENTITIES_PACKAGE = f"{_ROOT_PACKAGE}.entities"

_STDLIB = sys.stdlib_module_names


@dataclass(frozen=True)
class ImportRecord:
    """源码中的一条 ``import`` / ``from ... import`` 语句。"""

    path: Path
    line: int
    target: str  # 解析后的绝对 dotted 落点（相对导入已按文件深度展开）
    in_function: bool  # True = 函数体内（延迟导入），False = 模块级


@dataclass(frozen=True)
class ImportScan:
    files: tuple[Path, ...]
    imports: tuple[ImportRecord, ...]


# --- 白名单：两张表物理分开，理由写在条目里 --------------------------------

_PERMANENT_DEFERRED_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("run_deadline_policy.py", "travel_agent.config"): (
        "run_deadline_policy.py:27-28 自陈的设计意图：entities 不得在 import 期把 "
        "config 包拉进来，窗口数字只在构建新快照时才读。这条必须永远是函数内延迟导入，"
        "升级成模块级就是破坏了被人主动维护过的边界。"
    ),
}

_MODULE_LEVEL_CURRENT_STATE: dict[tuple[str, str], str] = {
    ("user.py", "travel_agent.utils.user_text"): (
        "is_blank 是只依赖标准库的纯函数，PreferenceOptionGroup 在模型层校验选项文本"
        "是否为空；工具模块本身零内部依赖。"
    ),
    ("state.py", "travel_agent.local_profile"): (
        "LOCAL_USER_ID 是本地单用户身份锚点（ADR-0001），state 的行要按用户标记归属。"
    ),
    ("trip_run.py", "travel_agent.local_profile"): (
        "同上：TripRun 是本地单用户的持久运行记录，行归属锚在 LOCAL_USER_ID。"
    ),
    ("trip_run.py", "travel_agent.infrastructure.row_values"): (
        "iso_or_none 是只依赖标准库的序列化纯函数，TripRun 行用它写 ISO 时间。"
    ),
}


# --- 通用扫描器 ------------------------------------------------------------


def _records_for(
    path: Path,
    node: ast.Import | ast.ImportFrom,
    dotted: str,
    is_init: bool,
    in_function: bool,
) -> Iterator[ImportRecord]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield ImportRecord(path, node.lineno, alias.name, in_function)
        return
    if not node.level:
        yield ImportRecord(path, node.lineno, node.module or "", in_function)
        return
    target = relative_import_target(dotted, is_init, node.level, node.module)
    yield ImportRecord(path, node.lineno, target, in_function)


def _walk_imports(
    path: Path, tree: ast.AST, dotted: str, is_init: bool
) -> Iterator[ImportRecord]:
    """收集 import 节点，父链上下文由共用遍历器提供。"""

    for node, in_function in walk_with_function_context(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield from _records_for(path, node, dotted, is_init, in_function)


def scan_imports(package_dir: Path) -> ImportScan:
    """AST 扫描一个包（含子目录）下每个 ``.py`` 的全部 import 语句。"""

    root = package_root(package_dir)
    files = iter_python_files(package_dir)
    records: list[ImportRecord] = []
    for path in files:
        tree = parse_file(path)
        dotted = dotted_name(root, path)
        records.extend(_walk_imports(path, tree, dotted, path.name == "__init__.py"))
    return ImportScan(files=files, imports=tuple(records))


def classify_target(target: str) -> str:
    """``stdlib`` / ``third_party`` / ``travel_agent``，按首段归类。"""

    root = target.split(".", 1)[0]
    if root == _ROOT_PACKAGE:
        return _ROOT_PACKAGE
    if root in _STDLIB:
        return "stdlib"
    return "third_party"


# --- 白名单匹配 -------------------------------------------------------------


def _match_in(
    file_key: str, target: str, table: dict[tuple[str, str], str]
) -> tuple[str, str] | None:
    for entry_file, dotted in table:
        if entry_file == file_key and (
            target == dotted or target.startswith(dotted + ".")
        ):
            return (entry_file, dotted)
    return None


def _file_key(path: Path) -> str:
    return path.relative_to(_ENTITIES_DIR).as_posix()


# --- 守卫本体 ---------------------------------------------------------------


def test_entities_imports_only_stdlib_third_party_itself_and_the_whitelist():
    """entities 只依赖标准库、第三方库和 entities 内部，5 条例外逐项列出并各写理由。

    本仓没有定义过层次序（见模块 docstring），所以这里不引用任何「层」的概念：
    白名单之外的每一个 ``travel_agent.*`` 落点都是违规，违规文案直接告诉人怎么办。
    """

    scan = scan_imports(_ENTITIES_DIR)
    violations: list[str] = []
    for record in scan.imports:
        if classify_target(record.target) != _ROOT_PACKAGE:
            continue
        if record.target in (_ROOT_PACKAGE, _ENTITIES_PACKAGE) or record.target.startswith(
            _ENTITIES_PACKAGE + "."
        ):
            continue
        file_key = _file_key(record.path)
        where = "函数内延迟导入" if record.in_function else "模块级导入"
        permanent = _match_in(file_key, record.target, _PERMANENT_DEFERRED_EXCEPTIONS)
        current = _match_in(file_key, record.target, _MODULE_LEVEL_CURRENT_STATE)
        if permanent is None and current is None:
            violations.append(
                "entities 出现了白名单之外的跨包导入：\n"
                f"  文件：src/travel_agent/entities/{file_key}:{record.line}\n"
                f"  目标：{record.target}（{where}）\n"
                "  如果这是有意的：去 tests/test_layering_contract.py 的白名单加一条并写理由 ——\n"
                "  先想清楚它是永久例外（进 _PERMANENT_DEFERRED_EXCEPTIONS，必须保持函数内延迟导入）\n"
                "  还是当前状态（进 _MODULE_LEVEL_CURRENT_STATE）。"
            )
            continue
        if permanent is not None and not record.in_function:
            violations.append(
                "永久例外被升级成了模块级导入：\n"
                f"  文件：src/travel_agent/entities/{file_key}:{record.line}\n"
                f"  目标：{record.target}\n"
                "  这条是设计意图（entities 不得在 import 期拉起 config 包），不是历史包袱。\n"
                "  把它移回函数体内；若边界真的要改，先改设计再动守卫。"
            )
        if current is not None and record.in_function:
            violations.append(
                "模块级白名单条目现在以函数内延迟导入出现：\n"
                f"  文件：src/travel_agent/entities/{file_key}:{record.line}\n"
                f"  目标：{record.target}\n"
                "  如果延迟化是有意的：把这条从 _MODULE_LEVEL_CURRENT_STATE 挪进\n"
                "  _PERMANENT_DEFERRED_EXCEPTIONS 并更新理由；两张表不能同时含糊。"
            )
    assert not violations, "\n\n".join(violations)


def test_every_whitelist_entry_still_matches_a_real_import():
    """白名单条目必须对应真实存在的导入，否则条目要跟着代码一起删。

    例外表只删不增是常态：代码里的导入消失了、条目还留着，下一个加例外的人
    会以为这张表还管着什么东西。
    """

    scan = scan_imports(_ENTITIES_DIR)
    used: set[tuple[str, str]] = set()
    for record in scan.imports:
        file_key = _file_key(record.path)
        for table in (_PERMANENT_DEFERRED_EXCEPTIONS, _MODULE_LEVEL_CURRENT_STATE):
            matched = _match_in(file_key, record.target, table)
            if matched is not None:
                used.add(matched)
    stale = (set(_PERMANENT_DEFERRED_EXCEPTIONS) | set(_MODULE_LEVEL_CURRENT_STATE)) - used
    assert not stale, (
        "这些白名单条目已经没有对应的真实导入，请连同代码变更一起删掉：\n"
        + "\n".join(f"  {file_key} -> {target}" for file_key, target in sorted(stale))
    )


def test_the_scan_itself_is_not_vacuous():
    """守住扫描器自己：它如果什么都没收集到，上面的守卫会永远绿。

    恒绿的门禁比没有门禁更贵（先例：tests/test_invariants_doc.py 的
    ``test_the_gate_itself_collects_references``）。
    """

    scan = scan_imports(_ENTITIES_DIR)
    assert_scan_floor(len(scan.files), 40, "文件")
    assert_sentinels(
        {path.name for path in scan.files},
        {"contract_base.py", "state.py", "trip_run.py"},
        "文件",
    )
    assert scan.imports, "收集到 0 条 import 语句，AST 遍历器多半坏了"
