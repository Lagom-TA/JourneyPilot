"""
系统状态与配置 API (Serving Layer)
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from travel_agent.bootstrap.registry import get_components
from ...config import get_settings
from travel_agent.api.schemas.system import ModelConfigRequest, SystemStatus

from travel_agent.bootstrap.diagnostics.status import collect_status
from travel_agent.bootstrap.diagnostics.readiness import collect_readiness
from travel_agent.config.public_view import public_config_payload
from travel_agent.config.runtime_models import (
    RuntimeModelConfigDisabled, RuntimeModelConfigPersistenceError,
    RuntimeModelConfigInvalid, update_runtime_model,
)

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status", response_model=SystemStatus)
async def get_status():
    """获取系统状态"""
    return SystemStatus(**await collect_status())


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """生产就绪探针：核心依赖不可用时返回 503。"""
    payload = await collect_readiness()
    return JSONResponse(status_code=200 if payload["status"] == "ready" else 503, content=payload)


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """获取当前系统配置（脱敏后）"""
    return public_config_payload(get_settings())


@router.post("/configure")
async def configure_model(config: ModelConfigRequest):
    """热更新模型配置（无需重启）"""
    try:
        return update_runtime_model(**config.model_dump())
    except RuntimeModelConfigDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeModelConfigPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeModelConfigInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools")
async def get_tools():
    """获取所有可用工具列表"""
    components = get_components()
    return {
        "tools": components.tool_registry.list_tools(),
        "total": components.tool_registry.count,
    }


@router.get("/mcp-servers")
async def get_mcp_servers():
    """获取 MCP 服务器状态"""
    components = get_components()
    states = components.mcp_manager.get_server_states()
    servers = sorted(states.values(), key=lambda item: item["name"])
    return {
        "servers": servers,
        "total": len(servers),
        "active": len([s for s in servers if s["enabled"]]),
        "healthy": len([s for s in servers if s["status"] == "healthy"]),
        "misconfigured": len([s for s in servers if s["status"] == "misconfigured"]),
    }
