"""state 写面守卫：节点与 with_run_control 写进 state 的每个键必须在
``TravelAgentState.model_fields`` 里。

为什么运行时看不见写面漂移（langgraph 1.1.3 实跑验证）：

1. 节点返回未知键 → LangGraph 静默丢弃，不抛异常，最终 state 只有已知键。
2. 给 TravelAgentState 加 ``extra="forbid"`` → 结果完全一样，还是静默丢弃、
   还是不抛。过滤发生在校验之前，所以 forbid 对节点写面是安慰剂。

结论：运行时没有任何一个位置能看见写面漂移，测试是唯一看得见它的地方。

顺带不要动的东西：``TravelAgentState`` 的 ``model_config`` 保持
``{"arbitrary_types_allowed": True}``，不要加 ``extra="forbid"``——它对写面
无效，但会咬到 ``workflows/travel_planning.py`` 里的
``TravelAgentState.model_validate(snapshot.values)``：字段改名后 resume 旧
checkpoint 会从静默忽略变成抛错。

扫描规则（数据流，跟 Return）：

- ``return {...}`` 字典字面量 → 收集键。
- ``return helper(...)`` 且 helper 可解析（模块内或 import 落点）→ 返回值被
  整个 return 出去，递归进去；被跟进调用的字典字面量参数也收集键。
- ``key: helper(...)``（字典值位置）→ 那是某个字段的值，不是 state 更新，
  不跟进。这条规则天然排除 ``artifact_gate._attribution`` 这类反例。
- 变量返回值 / ``**`` 展开 → 本地变量跟踪：收集该变量的字典赋值、下标写点、
  ``.update(...)`` 调用；参数起源、无字典赋值的进已知清单计数比对。
- 调用点的字符串常量参数沿递归绑定，解析 ``out[route_key]`` 这类动态下标键。

节点函数的真源从构图结果反查（``spec.runnable.func.__wrapped__``，
``with_run_control`` 用了 ``functools.wraps``），不 grep 源码：所有注册面都是
模块级字面量或纯构造器的产物，import 一次就是权威真值。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from tests._ast_support import (
    assert_scan_floor,
    assert_sentinels,
    dotted_module_path,
    dotted_name,
    find_def,
    iter_body_nodes,
    package_root,
    parse_file,
    relative_import_target,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class KeyWrite:
    file: str
    line: int
    key: str


@dataclass(frozen=True)
class UnresolvedShape:
    file: str
    line: int
    shape: str


@dataclass(frozen=True)
class WriteSurfaceScan:
    node_names: frozenset[str]
    writes: tuple[KeyWrite, ...]
    unresolved: tuple[UnresolvedShape, ...]


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


class _ModuleInfo:
    def __init__(self, path: Path):
        self.path = path
        self.tree = parse_file(path)
        self.dotted = dotted_name(package_root(path.parent), path)
        self.is_init = path.name == "__init__.py"
        self.defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.imports: dict[str, tuple[Path, str]] = {}
        for node in self.tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            target = (
                relative_import_target(self.dotted, self.is_init, node.level, node.module)
                if node.level
                else node.module or ""
            )
            if not target.startswith("travel_agent."):
                continue
            target_path = dotted_module_path(target)
            if target_path is None:
                continue
            for alias in node.names:
                if alias.name != "*":
                    self.imports[alias.asname or alias.name] = (target_path, alias.name)


class _Scanner:
    def __init__(self):
        self.modules: dict[str, _ModuleInfo] = {}
        self.writes: list[KeyWrite] = []
        self.unresolved: list[UnresolvedShape] = []
        self._visited_funcs: set[tuple] = set()
        self._resolving: set[tuple] = set()

    def module(self, path: Path) -> _ModuleInfo:
        info = self.modules.get(str(path))
        if info is None:
            info = _ModuleInfo(path)
            self.modules[str(path)] = info
        return info

    def _write(self, path: Path, line: int, key: str) -> None:
        self.writes.append(KeyWrite(_rel(path), line, key))

    def _fail(self, path: Path, line: int, shape: str) -> None:
        self.unresolved.append(UnresolvedShape(_rel(path), line, shape))

    def scan_function(
        self, func: ast.FunctionDef | ast.AsyncFunctionDef,
        info: _ModuleInfo,
        bindings: dict[str, str],
    ) -> None:
        key = (str(info.path), func.lineno, tuple(sorted(bindings.items())))
        if key in self._visited_funcs:
            return
        self._visited_funcs.add(key)
        env = (info, func, bindings)
        for node in iter_body_nodes(func):
            if isinstance(node, ast.Return):
                self._classify(node.value, env)

    def _classify(self, value: ast.expr | None, env) -> None:
        info, _func, _bindings = env
        if value is None:
            return
        if isinstance(value, ast.Dict):
            for key_node, val_node in zip(value.keys, value.values):
                if key_node is None:
                    self._classify(val_node, env)
                elif isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    self._write(info.path, key_node.lineno, key_node.value)
                else:
                    self._fail(info.path, key_node.lineno, f"非常量键（{ast.unparse(key_node)}）")
            return
        if isinstance(value, ast.Call):
            self._classify_call(value, env)
            return
        if isinstance(value, ast.Name):
            self._resolve_name(value.id, env)
            return
        if isinstance(value, ast.IfExp):
            self._classify(value.body, env)
            self._classify(value.orelse, env)
            return
        if isinstance(value, ast.Await):
            self._classify(value.value, env)
            return
        if isinstance(value, ast.BoolOp):
            for operand in value.values:
                self._classify(operand, env)
            return
        self._fail(
            info.path, value.lineno, f"无法分类的返回形态（{ast.unparse(value)[:80]}）"
        )

    def _classify_call(self, call: ast.Call, env) -> None:
        info, _func, _bindings = env
        callee = call.func
        if (
            isinstance(callee, ast.Name)
            and callee.id == "dict"
            and len(call.args) == 1
            and not call.keywords
        ):
            self._classify(call.args[0], env)
            return
        resolved = self._resolve_callee(callee, info)
        if resolved is None:
            self._fail(
                info.path,
                call.lineno,
                f"return 处解析不出的调用（{ast.unparse(call)[:80]}）",
            )
            return
        target_path, target_func = resolved
        for arg in [*call.args, *[kw.value for kw in call.keywords]]:
            if isinstance(arg, ast.Dict):
                self._classify(arg, env)
        self.scan_function(
            target_func, self.module(target_path), self._bind_string_constants(target_func, call)
        )

    def _resolve_callee(self, callee: ast.expr, info: _ModuleInfo):
        if isinstance(callee, ast.Name):
            local = info.defs.get(callee.id)
            if local is not None:
                return info.path, local
            imported = info.imports.get(callee.id)
            if imported is not None:
                target_path, target_name = imported
                target_func = self.module(target_path).defs.get(target_name)
                if target_func is not None:
                    return target_path, target_func
        return None

    @staticmethod
    def _bind_string_constants(func, call: ast.Call) -> dict[str, str]:
        params = [a.arg for a in func.args.args] + [a.arg for a in func.args.kwonlyargs]
        out: dict[str, str] = {}
        for param, arg in zip(params, call.args):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out[param] = arg.value
        for kw in call.keywords:
            if (
                kw.arg is not None
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ):
                out[kw.arg] = kw.value.value
        return out

    def _resolve_name(self, name: str, env) -> None:
        info, func, bindings = env
        guard = (str(info.path), func.lineno, name)
        if guard in self._resolving:
            return
        self._resolving.add(guard)
        try:
            param_names = {a.arg for a in func.args.args} | {
                a.arg for a in func.args.kwonlyargs
            }
            assigned = False
            for node in iter_body_nodes(func):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            assigned = True
                            self._classify(node.value, env)
                        elif (
                            isinstance(target, ast.Subscript)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == name
                        ):
                            self._subscript_write(target, bindings, info)
                elif isinstance(node, ast.AnnAssign):
                    if (
                        isinstance(node.target, ast.Name)
                        and node.target.id == name
                        and node.value is not None
                    ):
                        assigned = True
                        self._classify(node.value, env)
                elif isinstance(node, ast.AugAssign):
                    if isinstance(node.target, ast.Name) and node.target.id == name:
                        self._classify(node.value, env)
                    elif (
                        isinstance(node.target, ast.Subscript)
                        and isinstance(node.target.value, ast.Name)
                        and node.target.value.id == name
                    ):
                        self._subscript_write(node.target, bindings, info)
                elif (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "update"
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == name
                ):
                    for kw in node.value.keywords:
                        if kw.arg is not None:
                            self._write(info.path, kw.value.lineno, kw.arg)
                    for arg in node.value.args:
                        self._classify(arg, env)
            if not assigned:
                where = "参数" if name in param_names else "来源"
                self._fail(
                    info.path,
                    func.lineno,
                    f"变量 {name} 无字典赋值（{where}起源，函数 {func.name}）",
                )
        finally:
            self._resolving.discard(guard)

    def _subscript_write(
        self, target: ast.Subscript, bindings: dict[str, str], info: _ModuleInfo
    ) -> None:
        index = target.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            self._write(info.path, target.lineno, index.value)
        elif isinstance(index, ast.Name) and index.id in bindings:
            self._write(info.path, target.lineno, bindings[index.id])
        else:
            self._fail(info.path, target.lineno, f"变量下标键（{ast.unparse(index)}）")


def _node_callable_targets() -> list[tuple[str, Path, str, int]]:
    from travel_agent.workflows.fast_answer import build_fast_workflow
    from travel_agent.workflows.travel_planning import build_travel_workflow

    targets = []
    for graph in (build_travel_workflow(), build_fast_workflow()):
        for node_name, spec in graph.nodes.items():
            fn = getattr(spec.runnable, "func", None) or getattr(
                spec.runnable, "afunc", None
            )
            original = getattr(fn, "__wrapped__", fn)
            code = original.__code__
            targets.append(
                (
                    node_name,
                    Path(code.co_filename),
                    original.__qualname__.split(".")[-1],
                    code.co_firstlineno,
                )
            )
    return targets


_SCAN: WriteSurfaceScan | None = None


def scan_state_write_surface() -> WriteSurfaceScan:
    """构图反查节点真源，按数据流规则收集 state 写点。"""

    global _SCAN
    if _SCAN is not None:
        return _SCAN
    scanner = _Scanner()
    targets = _node_callable_targets()
    for node_name, path, func_name, line in targets:
        info = scanner.module(path)
        func = find_def(info.tree, func_name, line)
        assert func is not None, f"节点 {node_name} 的可调用体找不到：{_rel(path)}:{line}"
        scanner.scan_function(func, info, {})

    rc_path = _REPO_ROOT / "src/travel_agent/workflows/run_control.py"
    rc_info = scanner.module(rc_path)
    scanner.scan_function(rc_info.defs["_blocked_research_worker_update"], rc_info, {})
    wrapped = next(
        node
        for node in ast.walk(rc_info.defs["with_run_control"])
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_wrapped"
    )
    scanner.scan_function(wrapped, rc_info, {})

    _SCAN = WriteSurfaceScan(
        node_names=frozenset(node_name for node_name, *_ in targets),
        writes=tuple(scanner.writes),
        unresolved=tuple(scanner.unresolved),
    )
    return _SCAN


# 解析不出的形状的显式清单（评审条目 B2 阶段 2）。计数比对：多一个就红——
# 某种语法形态如果扫不到，那一类分类就永远不会被行使，将来同样形态写的新东西
# 会直接漏过守卫（先例：openpi child-session.test.ts 的 KNOWN_FACTORY_TOOLS）。
# 条目身份不含行号，行号漂移不触发误报。
_KNOWN_UNRESOLVABLE_SHAPES: dict[tuple[str, str], str] = {
    (
        "src/travel_agent/agents/orchestrator/candidate_gate.py",
        "变量 base_update 无字典赋值（参数起源，函数 _passed_update）",
    ): "合并参数携带的既有更新；键由各调用方的字面量与本地变量覆盖。",
    (
        "src/travel_agent/agents/orchestrator/candidate_gate.py",
        "变量 base_update 无字典赋值（参数起源，函数 _catalog_contract_update）",
    ): "同上：调用方传入的 base_update 在调用点已被扫描。",
    (
        "src/travel_agent/workflows/composition_repair.py",
        "变量 update 无字典赋值（参数起源，函数 apply_composition_repair_budget）",
    ): "预算函数原样合并入参 update；字面量参数在调用点收集，变量参数的键在其宿主函数收集。",
    (
        "src/travel_agent/workflows/run_control.py",
        "return 处解析不出的调用（fn(state, *args, **kwargs)）",
    ): "with_run_control 透传节点体结果；23 个节点体各自已按数据流扫描。",
}


def test_every_state_write_key_is_a_travel_agent_state_field():
    """收集到的每个键必须在 TravelAgentState.model_fields 里。"""

    from travel_agent.entities.state import TravelAgentState

    scan = scan_state_write_surface()
    model_fields = set(TravelAgentState.model_fields)
    violations = sorted(
        {(w.file, w.line, w.key) for w in scan.writes if w.key not in model_fields}
    )
    assert not violations, "\n\n".join(
        "state 写面出现 model_fields 之外的键：\n"
        f"  文件：{file}:{line}\n"
        f"  键：{key}\n"
        "  这个键不在 model_fields 里，写进去会被 LangGraph 静默丢弃。\n"
        "  想清楚它本来想写什么：补字段进 entities/state.py，还是改键名。"
        for file, line, key in violations
    )


def test_unresolvable_shapes_match_the_known_list():
    """B 类形状必须与显式清单完全一致：新增的进来分析，消失的连条目一起删。"""

    scan = scan_state_write_surface()
    scanned = {(u.file, u.shape) for u in scan.unresolved}
    known = set(_KNOWN_UNRESOLVABLE_SHAPES)
    new = sorted(scanned - known)
    stale = sorted(known - scanned)
    assert not new, "\n\n".join(
        "state 写面扫描遇到了已知清单之外的不可解析形状：\n"
        f"  {file}: {shape}\n"
        "  先分析它写了什么；确实解析不出，就去 _KNOWN_UNRESOLVABLE_SHAPES "
        "加一条并写理由。不许静默跳过。"
        for file, shape in new
    )
    assert not stale, "\n\n".join(
        "这些不可解析形状已经不存在了，请连同条目一起删：\n"
        + "\n".join(f"  {file}: {shape}" for file, shape in stale)
    )


def test_the_scan_itself_is_not_vacuous():
    """守住扫描器自己：什么都没收集到时，上面的守卫会永远绿。"""

    scan = scan_state_write_surface()
    assert_scan_floor(len(scan.node_names), 20, "节点可调用体")
    assert_sentinels(
        set(scan.node_names),
        {"plan_gate", "dispatcher", "delivery_finalizer"},
        "节点",
    )
    assert_scan_floor(len({w.key for w in scan.writes}), 51, "state 键")
