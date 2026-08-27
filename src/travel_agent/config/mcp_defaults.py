"""仓库内置的 MCP server 默认配置：静态声明读 YAML，求值留在这里。

声明在 `configs/mcp/servers.yaml`——server 名、描述、Key 名、npm 包名与本地 bin 名、
仓内脚本相对路径或 ``-m`` 模块名。这个文件头此前就自称「这是一份数据」，但落地是一个
函数，于是十几个 server 的命令行和四样求值混在同一个函数体里。

求值必须留在 Python，写不进 YAML 的正是这几样：

- ``_node_mcp_fields`` 的本地 bin 探测（依赖 ``<repo>/node_modules`` 当下存不存在）
- ``_server_env`` 的 ``os.getenv``（依赖进程环境）
- ``sys.executable`` 与 ``_REPO_ROOT`` 拼路径（依赖装在哪）

**缓存粒度只到 YAML 解析。** ``models._mcp_servers()`` 是 pydantic 的默认工厂，每次
构造 ``Settings`` 调一次，而环境变量的读取就发生在那一次调用里。把最终的 server dict
缓存起来，会让所有「monkeypatch 环境变量再重建 Settings」的用例变红——它们依赖每次
重建都重新读 env。所以 ``_declarations()`` 只缓存文本到声明对象的解析，
``default_mcp_servers()`` 每次都重新构造。

**失败一律硬抛。** 与 `configs/providers/*.yaml` 相反：那边坏一份只影响那一家模型
供应商的 preset，其余照跑，所以 `providers.py` 记一行 error 就 continue。这份坏掉
等于 0 个 server，四个 worker 的 MCP 工具全空；而 `builders.py` 里 MCP 初始化的
``except Exception`` 只打一行 warning，系统会"正常启动"然后每个 worker 都没工具。
文件缺失、YAML 解析失败、schema 校验失败，三种都在 ``Settings`` 构造期抛
``MCPDeclarationError``，不吞、不回落到空 dict、不回落到硬编码默认。

MCP provider 的原生环境变量名（``TAVILY_API_KEY`` 等）**保持原名**：它们要被原样
传给子进程，改成 ``JOURNEYPILOT_*`` 前缀反而会让子进程读不到。仓库自己的配置项走
统一前缀，见 `env.py`。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import Field, ValidationError, model_validator

from .loader import ConfigError
from .models import MCPServerItem, StrictConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 静态声明的唯一定义处。
DECLARATION_PATH = _REPO_ROOT / "configs" / "mcp" / "servers.yaml"


class MCPDeclarationError(ConfigError):
    """MCP 静态声明读不出来。

    继承 ``ConfigError`` 只为了让 CLI 打出可读的一行而不是 traceback——它仍然是硬
    失败：两个 ``except ConfigError`` 现场都是打印加以 1 退出，没有一处会让进程带着
    0 个 server 继续跑。
    """


class NodeLaunch(StrictConfig):
    """npm 包形态的 stdio server。"""

    #: 带版本号的 npm 包名，回落 ``npx -y`` 时原样传给它。
    package: str = Field(min_length=1)
    #: ``node_modules/.bin`` 下的可执行名，本地装好时优先用它。
    bin: str = Field(min_length=1)


class PythonLaunch(StrictConfig):
    """``sys.executable`` 形态的 stdio server：仓内脚本，或 pip 装好的模块。"""

    #: 相对 repo root 的脚本路径，用 ``/`` 分隔。
    script: Optional[str] = None
    #: ``python -m <module>`` 的模块名。
    module: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_form(self) -> "PythonLaunch":
        if bool(self.script) == bool(self.module):
            raise ValueError("python 启动方式必须且只能给 script 或 module 之一")
        if self.script and (self.script.startswith("/") or ".." in self.script.split("/")):
            # 声明文件里的路径一律相对 repo root 且不许往上走：这份文件决定的是拿
            # 什么去起子进程。
            raise ValueError(f"script 必须是不含 .. 的相对路径，实际 {self.script!r}")
        return self


class MCPServerDeclaration(StrictConfig):
    """一个 server 的静态声明。``extra="forbid"``：拼错的字段名必须在启动期被抓住。"""

    description: str = Field(min_length=1)
    #: 该 server 需要的 provider 原生 Key 名。``env`` 从这里派生，不各写一份。
    required_env: List[str] = Field(default_factory=list)
    node: Optional[NodeLaunch] = None
    python: Optional[PythonLaunch] = None

    @model_validator(mode="after")
    def exactly_one_launch(self) -> "MCPServerDeclaration":
        if bool(self.node) == bool(self.python):
            raise ValueError("必须且只能声明 node 或 python 之一")
        return self


class MCPServerDeclarations(StrictConfig):
    servers: Dict[str, MCPServerDeclaration] = Field(min_length=1)


@lru_cache(maxsize=1)
def _declarations() -> MCPServerDeclarations:
    """读并校验 YAML。**只有这一层被缓存**，见模块 docstring。"""

    if not DECLARATION_PATH.is_file():
        raise MCPDeclarationError(
            f"MCP 静态声明文件缺失：{DECLARATION_PATH}。"
            "没有它就是 0 个 MCP server、四个 worker 全无工具，所以这里直接失败而不是"
            "回落到空配置。"
        )
    try:
        payload = yaml.safe_load(DECLARATION_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MCPDeclarationError(
            f"MCP 静态声明解析失败：{DECLARATION_PATH}\n{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MCPDeclarationError(
            f"MCP 静态声明格式错误：{DECLARATION_PATH} 顶层应当是一个映射，"
            f"实际 {type(payload).__name__}"
        )
    try:
        return MCPServerDeclarations.model_validate(payload)
    except ValidationError as exc:
        raise MCPDeclarationError(
            f"MCP 静态声明校验失败：{DECLARATION_PATH}\n{_describe(exc)}"
        ) from exc


def _describe(exc: ValidationError) -> str:
    """把 pydantic 的报错折成「哪一段的哪个字段」——点名才有用。"""

    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(顶层)"
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)


def reload_declarations() -> None:
    """丢掉 YAML 解析缓存。测试与热加载用。"""

    _declarations.cache_clear()


def _node_mcp_fields(launch: NodeLaunch) -> Dict[str, object]:
    """Node stdio server 的启动方式：本地装好的 bin 优先，否则回落到 ``npx -y``。

    镜像构建期 ``npm ci`` 到 ``<repo>/node_modules``，运行层不带 npm（npx 不存在）。
    """
    local_bin = _REPO_ROOT / "node_modules" / ".bin" / launch.bin
    if local_bin.exists():
        return {"command": str(local_bin), "args": []}
    return {"command": "npx", "args": ["-y", launch.package]}


def _python_mcp_fields(launch: PythonLaunch) -> Dict[str, object]:
    if launch.module:
        return {"command": sys.executable, "args": ["-m", launch.module]}
    assert launch.script  # exactly_one_form 保证
    script = _REPO_ROOT.joinpath(*launch.script.split("/"))
    return {"command": sys.executable, "args": [str(script)]}


def _server_env(required_env: List[str]) -> Optional[Dict[str, str]]:
    """``env`` 从 ``required_env`` 派生，每次调用现读。

    声明了 Key 的 server 即使一个都没配也给 ``{}`` 而不是 ``None``：MCPManager 靠
    ``required_env`` 决定跳过谁（``tools/mcp_manager.py::_missing_required_env``），
    这两者在下游不等价，所以这里保持原样。
    """
    if not required_env:
        return None
    return {name: value for name in required_env if (value := os.getenv(name))}


def default_mcp_servers() -> Dict[str, "MCPServerItem"]:
    """提供仓库内置的 MCP 默认配置。

    每次调用都重新求值：本地 bin 探测与环境变量读取都发生在这一次里。声明与设计理由
    见 `configs/mcp/servers.yaml`。
    """
    servers: Dict[str, MCPServerItem] = {}
    for name, declaration in _declarations().servers.items():
        launch = (
            _node_mcp_fields(declaration.node)
            if declaration.node is not None
            else _python_mcp_fields(declaration.python)
        )
        servers[name] = MCPServerItem(
            **launch,
            env=_server_env(declaration.required_env),
            description=declaration.description,
            required_env=list(declaration.required_env),
        )
    return servers
