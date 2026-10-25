"""
FastAPI 应用工厂 (Serving Layer)
采用 lifespan 模式管理组件生命周期。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from travel_agent.bootstrap.startup import application_lifespan
from ..config import get_settings
from ..paths import BACKEND_DIR
from ..utils.log_redaction import install_query_secret_redaction
from .middleware import request_logging_middleware
from .routes.trip_runs import runs, events, delivery, workspace, control
from .routes import chat, knowledge, memory, places, preset, product, sessions, system, user

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动时初始化，关闭时清理"""
    async with application_lifespan():
        yield


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例"""
    settings = get_settings()

    # 查询串凭据脱敏的第二个挂载点。第一个在 `services/amap_route_search.py` 的
    # import 时（那个不能挪：绕过入口直接 import 那个模块的脚本/单测/工具直调会裸奔）。
    # 这里再挂一遍是为了反方向的缺口：下一个按查询串带 key 的 provider 忘了自己那句。
    # `install_query_secret_redaction` 按 logger 名幂等，重复调用不叠加 filter。
    install_query_secret_redaction()

    app = FastAPI(
        title="JourneyPilot TripOps API",
        description="基于 LangGraph、RAG、Memory、Tools 和 TripRun 状态的可信旅行规划 API",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Gzip 压缩
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 请求日志
    app.middleware("http")(request_logging_middleware)

    # 注册路由
    app.include_router(chat.router)
    app.include_router(sessions.router)
    app.include_router(system.router)
    app.include_router(knowledge.router)
    app.include_router(user.router)
    app.include_router(places.router)
    app.include_router(memory.router)
    app.include_router(preset.router)
    app.include_router(product.router)
    app.include_router(runs.router)
    app.include_router(events.router)
    app.include_router(delivery.router)
    app.include_router(workspace.router)
    app.include_router(control.router)

    # Vite writes its generated frontend beside the backend package.
    static_path = BACKEND_DIR / "static"
    index_html = static_path / "index.html"
    if static_path.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
        # Vite 把带指纹的资源放在 assets/ 下，而 index.html 用绝对路径 /assets/... 引它们。
        assets_path = static_path / "assets"
        if assets_path.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    # 根路径：**有前端产物就给前端**（Compose 那一路只暴露 API 端口，用户打开的就是
    # 这里），没有产物才给 API 说明页。开发那一路走 Vite，不经过这个分支。
    @app.get("/")
    async def root():
        from fastapi.responses import FileResponse, HTMLResponse

        if index_html.is_file():
            return FileResponse(str(index_html))
        return HTMLResponse("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>JourneyPilot TripOps API</title>
    <style>
        body { font-family: system-ui; max-width: 600px; margin: 80px auto; padding: 20px; }
        h1 { color: #2563eb; }
        code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }
        a { color: #2563eb; }
    </style>
</head>
<body>
    <h1>JourneyPilot TripOps API</h1>
    <p>可信 TripOps 后端正在运行：TripRun、Living Itinerary、Evidence、Risk、Memory 与 Tools 均通过显式 API 边界暴露。</p>
    <p><strong>没有找到前端构建产物</strong>，所以这里显示的是 API 说明页。
    要在这个端口上打开网页端，先构建前端：<code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>。
    开发时也可以直接用 <code>./run.sh</code>，它会另起 Vite。</p>
    <ul>
        <li><a href="/docs">API 文档 (Swagger)</a></li>
        <li><a href="/api/status">系统状态</a></li>
        <li><a href="/api/health/ready">就绪探针</a></li>
        <li>聊天接口：<code>POST /api/chat-stream</code></li>
        <li>Trip Run：<code>GET /api/trip-runs</code></li>
        <li>知识库：<code>POST /api/knowledge/index</code></li>
    </ul>
</body>
</html>
        """)

    return app
