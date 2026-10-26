"""
MCP 工具管理器 (Infrastructure Layer)
直接使用 mcp SDK 进行服务器探测、工具注册和调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from typing import Any, AsyncIterator, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from ..utils.coordinates import amap_location_to_wgs84
from travel_agent.runtime.rate_gate import rate_gate_for
from .temporal import temporal_schema_contract_errors

logger = logging.getLogger(__name__)

INIT_TIMEOUT_SECONDS = int(os.getenv("MCP_INIT_TIMEOUT_SECONDS", "45"))
CALL_TIMEOUT_SECONDS = int(os.getenv("MCP_CALL_TIMEOUT_SECONDS", "60"))
# 每个 server 的会话租约空闲 TTL。0 表示不因空闲而回收。
SESSION_IDLE_TTL_SECONDS = float(os.getenv("MCP_SESSION_IDLE_TTL_SECONDS", "60"))
_DUCKDUCKGO_RESULT_TITLE = re.compile(r"^\s*\d+\.\s+(.+?)\s*$")

# 当 server 声明了 ``outputSchema`` 但自己的回答违反该声明时，写入工具结果的标记。
# 只在这样的轮次出现，因此标记缺失是正常情况，不能作为默认假设。
PROVIDER_OUTPUT_SCHEMA_VIOLATION_KEY = "provider_output_schema_violation"


class _OutputSchemaTolerantSession(ClientSession):
    """把 server 自相矛盾的 ``outputSchema`` 当作没有声明。

    MCP SDK 会用工具声明的 output schema 校验 ``structuredContent``，不匹配时从
    ``call_tool`` 内部抛出裸 ``RuntimeError``，并丢弃整个 ``CallToolResult``
    （包括文本内容）。调用方无法把它与管道断开区分，因此会关闭租约并把整个 server
    标记为不健康：一个应用层判定被报告成传输故障。

    server 每次调用都违反的声明不携带有效信息。处理方式与多数未声明
    ``outputSchema`` 的工具一致：接受回答，并明确记录声明不可用
    （见 ``PROVIDER_OUTPUT_SCHEMA_VIOLATION_KEY``）。例如
    ``@brave/brave-search-mcp-server`` 2.1.0 声明
    ``outputSchema: <zod>.shape``，丢掉了 ``looseObject`` catchall 并封闭 schema，
    因此 Brave 自己的 ``mixed`` 字段每次都会被拒绝。

    不是 SDK 校验判定的异常会原样向外传播。
    """

    def __init__(self, *args: Any, server_name: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._server_name = server_name
        self._output_schema_violation: Optional[str] = None

    async def _validate_tool_result(self, name: str, result: Any) -> None:
        try:
            await super()._validate_tool_result(name, result)
        except RuntimeError as exc:
            message = (str(exc) or exc.__class__.__name__)[:1000]
            self._output_schema_violation = message
            logger.warning(
                "MCP 输出 schema 声明不可用，按无声明处理 | server=%s tool=%s error=%s",
                self._server_name,
                name,
                message,
            )

    def take_output_schema_violation(self) -> Optional[str]:
        """返回并清除待处理的违规信息（租约跨多次调用存活）。"""
        violation = self._output_schema_violation
        self._output_schema_violation = None
        return violation


@dataclass
class _ServerSessionLease:
    """一个 server 的长驻 MCP 会话（由 per-server 锁串行化）。"""

    server_name: str
    session: Any
    stack: AsyncExitStack
    last_used_monotonic: float
    create_count: int = 1


def _normalized_duffel_result(server_name: str, tool_name: str, payload: Any) -> Any:
    """把本仓 JSON TextContent 解包成规范的路线结果。"""
    if server_name != "duffel-flights" or tool_name != "search_flights":
        return None
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if not isinstance(text, str):
        return None
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("provider") != "duffel"
        or not isinstance(result.get("routes"), list)
    ):
        return None
    return result


def _normalized_duckduckgo_result(
    server_name: str,
    tool_name: str,
    payload: Any,
) -> Any:
    """把本仓搜索 MCP 的文本投影成完整且有界的结果记录。"""
    if server_name != "duckduckgo-search" or tool_name != "free_web_search":
        return None
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if not isinstance(text, str):
        return None
    lines = text.splitlines()
    query = ""
    if lines and lines[0].startswith("搜索结果:"):
        query = lines[0].removeprefix("搜索结果:").strip()
    results: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for line in lines[1:]:
        title_match = _DUCKDUCKGO_RESULT_TITLE.match(line)
        if title_match is not None:
            if current is not None:
                results.append(current)
            current = {
                "title": title_match.group(1).strip(),
                "url": "",
                "snippet": "",
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("链接:"):
            current["url"] = stripped.removeprefix("链接:").strip()
        elif stripped.startswith("摘要:"):
            current["snippet"] = stripped.removeprefix("摘要:").strip()
    if current is not None:
        results.append(current)
    return {
        "success": True,
        "provider": "duckduckgo",
        "query": query,
        "results": results,
    }


def _normalized_rail_result(server_name: str, tool_name: str, payload: Any) -> Any:
    """把本仓 12306 server 的 JSON TextContent 解包成车票载荷。

    不解包时，载荷是嵌套在 content[0].text 里的 JSON 字符串，
    ``tools/governance.py::_sanitize_value`` 会把它压成一行 900 字符的文本，
    几百趟车次的回答到达确定性铁路绑定时只剩一趟。在这里解包可以让每条扁平记录
    （``results`` 键使用 20 条上限而不是 5 条）完整传给
    ``agents/transport_researcher/node.py::_rail_train_records``。

    只有 ``get-tickets`` 是结构化输出：``get-interline-tickets`` 是面向模型的
    文本，``get-station-code-of-citys`` 是短 JSON 字符串且由自己的解析器读取，
    两者都保持原始透传。
    """
    if server_name != "12306-train" or tool_name != "get-tickets":
        return None
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if not isinstance(text, str):
        return None
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("provider") != "12306"
        or not isinstance(result.get("results"), list)
    ):
        return None
    return result


def _amap_text_content(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        return None
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
    return None


_AMAP_REFUSAL_MARKERS = (" failed:", "cuqps", "over_direction_range", "invalid_user_key")


def _amap_stated_failure(tool_name: str, text: str) -> Optional[Dict[str, Any]]:
    """amap 在文本中说明的拒绝，或无法解码的其他文本返回 ``None``。

    amap 把每个 handler 的拒绝写成 ``"<what> failed: <info|infocode>"``。其他文本
    走通用透传；从无法识别的形状推断失败同样是一种猜测。
    """

    lowered = text.casefold()
    if not any(marker in lowered for marker in _AMAP_REFUSAL_MARKERS):
        return None
    return _amap_failure(tool_name, text)


def _amap_failure(tool_name: str, detail: str) -> Optional[Dict[str, Any]]:
    """amap 明确拒绝请求时的失败形状。

    ``status="0"`` 是 amap 的「请求被拒绝」，``infocode`` 说明拒绝原因（最常见是
    配额）。返回与协议错误相同的 ``success: False`` 形状，使这一轮保留失败签名而
    不是零结果成功：下游据此知道 provider 拒绝过，重试时不应复用同一个已耗尽的 key。
    """

    text = detail.strip()
    if not text:
        return None
    return {
        "success": False,
        "provider": "amap",
        "tool_name": tool_name,
        "error": text[:1000],
    }


def _amap_declared_failure(tool_name: str, parsed: Any) -> Optional[Dict[str, Any]]:
    """从已解码的响应体读取 amap 自己声明的拒绝。"""

    if not isinstance(parsed, dict):
        return None
    status = str(parsed.get("status") or "").strip()
    if status and status != "1":
        infocode = str(parsed.get("infocode") or "").strip()
        info = str(parsed.get("info") or "").strip()
        return _amap_failure(
            tool_name,
            f"amap {tool_name} refused: {info or 'unknown'} ({infocode or 'no infocode'})",
        )
    return None


def _normalized_amap_place_result(server_name: str, tool_name: str, payload: Any) -> Any:
    """把 amap POI TextContent 展平成浅层结构化记录列表。

    amap 把 POI 放在 content[0].text 的大 JSON 字符串里。原样保留时 governance
    清洗器会把这个深层嵌套字符串压到约 120 字符，丢失 POI。与 Duffel 归一化一致，
    这里把 POI 提升到顶层 ``results`` 列表，使 id/name/address/typecode（详情查询
    还包括点坐标）经过清洗后仍能到达确定性住宿绑定与地图投影。
    """
    if server_name != "amap-maps" or tool_name not in {
        "maps_text_search",
        "maps_around_search",
        "maps_search_detail",
    }:
        return None
    text = _amap_text_content(payload)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # amap 会把拒绝写成文本（"Text Search failed: <infocode>"），不是 JSON。
        # 已固定的 server 版本会用 ``isError`` 标记这类回答，``_mcp_result_error``
        # 通常已将其转成失败；但那是某一个 provider 版本的保证，通用透传会把这段
        # 文本当作成功回答。按形状处理，而不是按版本来处理。
        return _amap_stated_failure(tool_name, text)

    # maps_search_detail 把单个 POI id 解析为完整详情，包括 text/around search
    # 不返回的 ``location``（"lng,lat"）。提升这条记录，使已绑定的酒店能带地图坐标。
    if tool_name == "maps_search_detail":
        if not isinstance(parsed, dict):
            return None
        declared = _amap_declared_failure(tool_name, parsed)
        if declared is not None:
            return declared
        record = _amap_record(parsed)
        return {
            "success": True,
            "provider": "amap",
            "tool_name": tool_name,
            "location": parsed.get("location"),
            "results": [record] if record is not None else [],
        }

    declared = _amap_declared_failure(tool_name, parsed)
    if declared is not None:
        return declared
    pois = parsed.get("pois") if isinstance(parsed, dict) else None
    if not isinstance(pois, list):
        return None
    records: List[Dict[str, Any]] = []
    for poi in pois:
        record = _amap_record(poi)
        if record is not None:
            records.append(record)
    # 使用 ``results`` 键（而不是 ``pois``）：``classify_tool_result`` 只把
    # content/result/results/routes/data/text 视为实质内容，``pois`` 键会让带 POI 的
    # 回答被分类为 EMPTY_SUCCESS，导致确定性住宿绑定与地图投影丢失全部 POI。
    # 这三个工具没有 web 搜索 fallback 边，空判定就是误归类。
    return {
        "success": True,
        "provider": "amap",
        "tool_name": tool_name,
        "results": records,
    }


def _amap_record(poi: Any) -> Optional[Dict[str, Any]]:
    """把一条 amap POI 投影为浅层 id/name/address/typecode 记录。"""
    if not isinstance(poi, dict):
        return None
    record: Dict[str, Any] = {
        "id": str(poi.get("id") or "").strip(),
        "name": str(poi.get("name") or "").strip(),
        "address": str(poi.get("address") or "").strip(),
        "typecode": str(poi.get("typecode") or "").strip(),
    }
    # amap 用 GCJ-02 的 "lng,lat" 字符串表示点坐标；这里转换成数值 WGS-84
    # 经纬度，使其与 bundle 中其他地点使用同一套 OSM 瓦片。
    latitude, longitude = amap_location_to_wgs84(poi.get("location"))
    if latitude is not None and longitude is not None:
        record["latitude"], record["longitude"] = latitude, longitude
    if record["id"] and record["name"]:
        return record
    return None


def _mcp_error_message(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "初始化或调用超时"
    return str(exc) or exc.__class__.__name__


def _mcp_result_error(payload: Any) -> Optional[str]:
    """返回 MCP CallToolResult 报告的协议级错误。"""
    if not isinstance(payload, dict):
        return None
    if not (payload.get("isError") is True or payload.get("is_error") is True):
        return None

    messages: List[str] = []
    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    messages.append(text)
    elif isinstance(content, str) and content.strip():
        messages.append(content.strip())
    return "；".join(messages)[:1000] or "MCP 工具返回失败结果"


@dataclass
class MCPServerState:
    name: str
    description: str = ""
    type: str = "stdio"
    enabled: bool = True
    configured: bool = True
    healthy: bool = False
    status: str = "pending"
    tool_count: int = 0
    tools_list: List[str] = field(default_factory=list)
    tool_name_collisions: List[str] = field(default_factory=list)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "enabled": self.enabled,
            "disabled": not self.enabled,
            "configured": self.configured,
            "healthy": self.healthy,
            "status": self.status,
            "tool_count": self.tool_count,
            "tools_list": list(self.tools_list),
            "tool_name_collisions": list(self.tool_name_collisions),
            "last_error": self.last_error,
        }


class MCPManager:
    """MCP 服务器管理器。"""

    def __init__(self) -> None:
        self._initialized = False
        self._server_configs: Dict[str, Any] = {}
        self._server_states: Dict[str, MCPServerState] = {}
        # 每个 server 的会话租约（单会话 + 锁，不是多连接池）。
        self._session_leases: Dict[str, _ServerSessionLease] = {}
        self._server_call_locks: Dict[str, asyncio.Lock] = {}
        self._lease_meta_lock = asyncio.Lock()
        # 租约关闭后仍保留，使 create_count 在 server 进程生命周期内单调递增。
        self._session_lease_create_totals: Dict[str, int] = {}

    async def initialize(self, mcp_servers: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        初始化 MCP 服务器连接，并将工具注册到 ToolRegistry。

        采用“启动时短连探测、执行时 per-server session lease 复用”的模型：
        - 启动阶段真实调用 initialize/list_tools，得到健康状态与工具清单（短连接）
        - 工具执行阶段按 server 复用 ClientSession（同 server 串行；跨 server 可并行）
        """
        if self._initialized:
            return self.get_server_states()

        from .registry import get_tool_registry

        registry = get_tool_registry()
        await self.close_all_sessions()
        self._server_configs = dict(mcp_servers)
        self._server_states = {}
        async def _initialize_server(server_name: str, server_config: Any) -> int:
            state = self._build_initial_state(server_name, server_config)
            self._server_states[server_name] = state

            if not state.enabled:
                state.status = "disabled"
                return 0

            # 使用 sse_url 时（如百度地图远程接入），AK 通常已嵌入 URL，无需 env
            missing_env = [] if getattr(server_config, "sse_url", None) else self._missing_required_env(server_config)
            if missing_env:
                state.configured = False
                state.status = "misconfigured"
                state.last_error = f"缺少必需环境变量: {', '.join(missing_env)}"
                logger.warning(
                    "MCP 服务器 [%s] 缺少必需环境变量: %s",
                    server_name,
                    ", ".join(missing_env),
                )
                return 0

            if not self._is_transport_configured(server_config):
                state.configured = False
                state.status = "misconfigured"
                state.last_error = "未配置 command 或 sse_url"
                logger.warning(f"MCP 服务器 [{server_name}] 配置不完整")
                return 0

            try:
                tools = await self._list_server_tools(server_name, server_config)
                normalized_tools = [
                    self._normalize_tool_definition(tool) for tool in tools
                ]
                contract_errors = temporal_schema_contract_errors(
                    server_name=server_name,
                    tool_definitions=normalized_tools,
                )
                if contract_errors:
                    raise RuntimeError(
                        "date-sensitive MCP schema contract mismatch: "
                        + "; ".join(contract_errors)
                    )
                tool_names: List[str] = []

                for tool_meta in normalized_tools:
                    tool_name = tool_meta["name"]
                    if not tool_name:
                        continue

                    if registry.register(
                        name=tool_name,
                        description=tool_meta["description"],
                        parameters_schema=tool_meta["parameters_schema"],
                        executor=self._make_executor(server_name, tool_name),
                        source="mcp",
                        server_name=server_name,
                    ):
                        state.tool_name_collisions.append(tool_name)
                    tool_names.append(tool_name)

                state.healthy = True
                state.status = "healthy"
                state.tool_count = len(tool_names)
                state.tools_list = tool_names
                state.last_error = None
                logger.info(
                    f"MCP 服务器 [{server_name}] 已连接，注册 {len(tool_names)} 个工具"
                )
                return len(tool_names)
            except Exception as exc:
                error = _mcp_error_message(exc)
                state.healthy = False
                state.status = "error"
                state.last_error = error
                logger.error(f"MCP 服务器 [{server_name}] 初始化失败: {error}")
                return 0

        tool_counts = await asyncio.gather(*[
            _initialize_server(server_name, server_config)
            for server_name, server_config in mcp_servers.items()
        ])
        registered_tools = sum(tool_counts)

        self._initialized = True
        collisions = registry.collisions()
        if collisions:
            logger.error(
                "工具注册同名覆盖 %s 处: %s",
                len(collisions),
                ", ".join(sorted({c["tool_name"] for c in collisions})),
            )
        logger.info(
            "MCP 初始化完成 | 成功服务器: %s/%s | 工具数: %s",
            len([s for s in self._server_states.values() if s.healthy]),
            len(self._server_states),
            registered_tools,
        )
        return self.get_server_states()

    def get_server_states(self) -> Dict[str, Dict[str, Any]]:
        """返回所有 MCP 服务器的当前状态。"""
        return {name: state.to_dict() for name, state in self._server_states.items()}

    def _build_initial_state(self, server_name: str, server_config: Any) -> MCPServerState:
        server_type = "sse" if getattr(server_config, "sse_url", None) else "stdio"
        return MCPServerState(
            name=server_name,
            description=getattr(server_config, "description", "") or "",
            type=server_type,
            enabled=not getattr(server_config, "disabled", False),
        )

    def _is_transport_configured(self, server_config: Any) -> bool:
        if getattr(server_config, "sse_url", None):
            return True
        return bool(getattr(server_config, "command", None))

    def _missing_required_env(self, server_config: Any) -> List[str]:
        env = getattr(server_config, "env", None) or {}
        missing = []
        for name in getattr(server_config, "required_env", []):
            if not env.get(name):
                missing.append(name)
        return missing

    @asynccontextmanager
    async def _open_session(
        self, server_name: str, server_config: Any
    ) -> AsyncIterator[_OutputSchemaTolerantSession]:
        if getattr(server_config, "sse_url", None):
            async with sse_client(server_config.sse_url) as (read, write):
                async with _OutputSchemaTolerantSession(
                    read, write, server_name=server_name
                ) as session:
                    yield session
            return

        server_params = StdioServerParameters(
            command=server_config.command,
            args=server_config.args or [],
            env={**os.environ, **(server_config.env or {})},
        )
        async with stdio_client(server_params) as (read, write):
            async with _OutputSchemaTolerantSession(
                read, write, server_name=server_name
            ) as session:
                yield session

    async def _server_call_lock(self, server_name: str) -> asyncio.Lock:
        async with self._lease_meta_lock:
            lock = self._server_call_locks.get(server_name)
            if lock is None:
                lock = asyncio.Lock()
                self._server_call_locks[server_name] = lock
            return lock

    def _lease_is_idle_expired(self, lease: _ServerSessionLease) -> bool:
        if SESSION_IDLE_TTL_SECONDS <= 0:
            return False
        return (time.monotonic() - lease.last_used_monotonic) > SESSION_IDLE_TTL_SECONDS

    async def _close_session_lease(self, server_name: str) -> None:
        lease = self._session_leases.pop(server_name, None)
        if lease is None:
            return
        try:
            await lease.stack.aclose()
        except Exception as exc:
            logger.debug(
                "MCP session lease close error | server=%s error=%s",
                server_name,
                exc,
            )

    async def close_all_sessions(self) -> None:
        """关闭所有已租用的 MCP 会话（重新初始化 / 进程退出）。"""
        names = list(self._session_leases.keys())
        for name in names:
            await self._close_session_lease(name)

    def session_lease_create_count(self, server_name: str) -> int:
        """测试/观测辅助：这个 server 创建过多少次租约。"""
        return int(self._session_lease_create_totals.get(server_name, 0))

    async def _acquire_session_lease(
        self,
        server_name: str,
        server_config: Any,
    ) -> _ServerSessionLease:
        """返回一个存活的 per-server 会话；调用方必须持有该 server 的调用锁。"""
        existing = self._session_leases.get(server_name)
        if existing is not None and not self._lease_is_idle_expired(existing):
            existing.last_used_monotonic = time.monotonic()
            return existing

        if existing is not None:
            await self._close_session_lease(server_name)

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            session = await stack.enter_async_context(
                self._open_session(server_name, server_config)
            )
            await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT_SECONDS)
        except Exception:
            try:
                await stack.aclose()
            except Exception:
                pass
            raise

        create_count = self._session_lease_create_totals.get(server_name, 0) + 1
        self._session_lease_create_totals[server_name] = create_count
        lease = _ServerSessionLease(
            server_name=server_name,
            session=session,
            stack=stack,
            last_used_monotonic=time.monotonic(),
            create_count=create_count,
        )
        self._session_leases[server_name] = lease
        logger.debug(
            "MCP session lease opened | server=%s create_count=%s",
            server_name,
            lease.create_count,
        )
        return lease

    async def _list_server_tools(self, server_name: str, server_config: Any) -> List[Any]:
        # 启动探测使用短生命周期会话，不复用调用租约。
        async def _probe() -> List[Any]:
            async with self._open_session(server_name, server_config) as session:
                await session.initialize()
                response = await session.list_tools()
                tools = getattr(response, "tools", None)
                if tools is None and isinstance(response, dict):
                    tools = response.get("tools", [])
                if tools is None:
                    tools = []
                logger.debug(f"MCP 服务器 [{server_name}] 返回 {len(tools)} 个工具")
                return list(tools)

        return await asyncio.wait_for(_probe(), timeout=INIT_TIMEOUT_SECONDS)

    def _normalize_tool_definition(self, tool: Any) -> Dict[str, Any]:
        if isinstance(tool, dict):
            data = tool
        elif hasattr(tool, "model_dump"):
            data = tool.model_dump()
        else:
            data = {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "inputSchema": getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None),
            }

        schema = data.get("inputSchema") or data.get("input_schema") or {}
        if not isinstance(schema, dict):
            schema = {}
        if "type" not in schema:
            schema = {"type": "object", **schema}

        return {
            "name": data.get("name", ""),
            "description": data.get("description", "") or "",
            "parameters_schema": schema or {"type": "object", "properties": {}},
        }

    def _make_executor(self, server_name: str, tool_name: str):
        async def executor(**kwargs):
            return await self._execute_tool(server_name, tool_name, kwargs)

        return executor

    async def probe_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行一次实时诊断调用，不改变 MCP 健康状态。

        生产工具执行会刷新管理器的健康遥测；运维预检需要同样的实时协议检查，
        但不应因为观察而改写进程内状态。
        """

        return await self._execute_tool(
            server_name,
            tool_name,
            arguments,
            update_server_state=False,
        )

    async def _execute_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        update_server_state: bool = True,
    ) -> Dict[str, Any]:
        server_config = self._server_configs.get(server_name)
        if server_config is None:
            return {
                "success": False,
                "error": f"MCP 服务器未配置: {server_name}",
                "server_name": server_name,
                "tool_name": tool_name,
            }

        call_lock = await self._server_call_lock(server_name)

        async with call_lock:
            # 在已有的串行化之内追加请求间隔。未配置间隔的 server 等待 0 秒；
            # amap 在超过每秒配额时返回 ``CUQPS_HAS_EXCEEDED_THE_LIMIT``，一次
            # 拒绝会损失该轮全部住宿候选。
            min_interval = float(getattr(server_config, "min_interval_seconds", 0.0) or 0.0)
            if min_interval > 0:
                await rate_gate_for(f"mcp:{server_name}").acquire(min_interval)
            try:
                async def _call() -> Any:
                    lease = await self._acquire_session_lease(server_name, server_config)
                    # 租约跨多次调用存活；丢弃上一次调用留下的违规信息。
                    lease.session.take_output_schema_violation()
                    result = await lease.session.call_tool(tool_name, arguments)
                    lease.last_used_monotonic = time.monotonic()
                    violation = lease.session.take_output_schema_violation()
                    dumped = result.model_dump() if hasattr(result, "model_dump") else result
                    return dumped, violation

                payload, schema_violation = await asyncio.wait_for(
                    _call(), timeout=CALL_TIMEOUT_SECONDS
                )

                protocol_error = _mcp_result_error(payload)
                if protocol_error:
                    # 业务/协议错误载荷：保留租约（连接仍可用）。
                    return {
                        "success": False,
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "error": protocol_error,
                        "result": payload,
                    }

                state = self._server_states.get(server_name)
                if state and update_server_state:
                    state.healthy = True
                    state.status = "healthy"
                    state.last_error = None

                normalized = _normalized_duffel_result(server_name, tool_name, payload)
                if normalized is None:
                    normalized = _normalized_duckduckgo_result(
                        server_name,
                        tool_name,
                        payload,
                    )
                if normalized is None:
                    normalized = _normalized_amap_place_result(
                        server_name,
                        tool_name,
                        payload,
                    )
                if normalized is None:
                    normalized = _normalized_rail_result(
                        server_name,
                        tool_name,
                        payload,
                    )
                answer = normalized if normalized is not None else {
                    "success": True,
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "result": payload,
                }
                if schema_violation is not None:
                    answer[PROVIDER_OUTPUT_SCHEMA_VIOLATION_KEY] = schema_violation
                return answer
            except Exception as exc:
                # 传输/超时/运行时失败：关闭租约，下次调用重建。
                await self._close_session_lease(server_name)
                error = _mcp_error_message(exc)
                state = self._server_states.get(server_name)
                if state and update_server_state:
                    state.healthy = False
                    state.status = "error"
                    state.last_error = error

                logger.error(
                    "MCP 工具执行失败 | server=%s tool=%s error=%s",
                    server_name,
                    tool_name,
                    error,
                )
                return {
                    "success": False,
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "error": error,
                }


# 全局 MCPManager 单例
_mcp_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager
