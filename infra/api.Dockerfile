# JourneyPilot API 镜像。多阶段：编译工具留在 builder，运行层不带它们。
#
# 依赖分组由 build arg 选择（见 backend/pyproject.toml 的 [dependency-groups]）：
#   docker build -f infra/api.Dockerfile .                                       core + local-embedding（Compose 默认）
#   docker build -f infra/api.Dockerfile --build-arg DEPENDENCY_GROUPS="" .       只有 core
#   docker build -f infra/api.Dockerfile --build-arg DEPENDENCY_GROUPS="local-embedding cross-encoder" .
#
# 运行层以非 root 跑：这个进程接受用户上传并 fork 解析子进程，没有一步需要 root。

# ---------------------------------------------------------------------------
# frontend：构建静态产物。镜像不依赖宿主机先跑 npm run build。
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV VITE_OUT_DIR=/out
RUN npm run build

# ---------------------------------------------------------------------------
# builder：装依赖，带编译工具
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# 固定 uv 版本：一个会自己升级的安装器无法保证「同一个 commit 构出同一个镜像」。
ARG UV_VERSION=0.9.7
ARG DEPENDENCY_GROUPS="local-embedding"

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT="/opt/journeypilot"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==${UV_VERSION}"

# 只 COPY 清单再装依赖：源码改动不该让依赖层失效。
COPY backend/pyproject.toml backend/uv.lock ./backend/
COPY README.md ./
# --frozen：lockfile 就是事实，构建期绝不允许它被重新解析。
RUN set -eu; \
    groups=""; \
    for group in ${DEPENDENCY_GROUPS}; do groups="${groups} --group ${group}"; done; \
    uv sync --project /app/backend --frozen --no-default-groups ${groups}

# ---------------------------------------------------------------------------
# node-mcp：Node stdio MCP server 的包，装在自己的层
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS node-mcp

WORKDIR /mcp
COPY backend/mcp/package.json backend/mcp/package-lock.json ./
# npm ci 而不是 npm install：后者会改写 lockfile，而一个构建期被改写却没被提交的
# lockfile 意味着镜像里的版本没有任何地方记着。
RUN npm ci --omit=dev

# ---------------------------------------------------------------------------
# runtime：不带编译工具，不以 root 跑
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# curl 供 healthcheck；libpq5 是 psycopg 的运行时（不是 libpq-dev）；
# libstdc++6 供从 node:22 复制过来的 node 二进制。
#
# 字体：**fonts-wqy-microhei，不是 fonts-noto-cjk**。Debian 的 Noto CJK 打的是 CFF
# （PostScript）轮廓，reportlab 的 TTFont 解析器嵌不进去（实测
# `postscript outlines are not supported`），于是启动预检会判 PDF 导出不可用。
# WenQuanYi 是 TrueType 轮廓，是字体候选表（integrations/pdf_readiness.py）里的首选项。
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        libstdc++6 \
        fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin --uid 10001 journeypilot

# 维护 CLI 在容器内也需要与默认 PostgreSQL 18 匹配的客户端。
# 没有 pg_dump/pg_restore 时，非空库下一次升级会在备份闸门被拒绝。
# codename 从基础镜像取，避免把 bookworm 镜像配到 trixie-pgdg 源。
ARG POSTGRES_CLIENT_MAJOR=18
RUN codename="$(. /etc/os-release && echo "$VERSION_CODENAME")" \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/keyrings/postgresql.asc \
    && printf '%s\n' "deb [signed-by=/usr/share/keyrings/postgresql.asc] https://apt.postgresql.org/pub/repos/apt ${codename}-pgdg main" \
        > /etc/apt/sources.list.d/postgresql.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-client-${POSTGRES_CLIENT_MAJOR}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/journeypilot /opt/journeypilot
COPY --from=node-mcp /mcp/node_modules /app/backend/mcp/node_modules
# MCP 依赖要求 Node >=20（firecrawl-mcp 要求 >=22）；Debian 自带的 nodejs 太旧。
COPY --from=node-mcp /usr/local/bin/node /usr/local/bin/node
COPY --from=node-mcp /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
ENV PATH="/opt/journeypilot/bin:/app/backend/mcp/node_modules/.bin:${PATH}" \
    VIRTUAL_ENV="/opt/journeypilot" \
    PYTHONPATH="/app/backend" \
    PYTHONUNBUFFERED=1

COPY backend/travel_agent/ ./backend/travel_agent/
COPY backend/mcp/ ./backend/mcp/
COPY backend/main.py backend/journeypilot.py backend/alembic.ini backend/pyproject.toml ./backend/
COPY backend/migrations/ ./backend/migrations/
COPY docs/ ./docs/
# 前端产物由 frontend 阶段构建；API 直接服务它。
COPY --from=frontend /out ./backend/static
# **不复制 config.example.yaml 当 config.yaml**：一份示例伪装成真实配置，
# 会让「我的配置没生效」变成「我改的那份文件根本没被读」。Compose 把宿主机的
# config.yaml 挂进来；没挂也能跑（全部走 Pydantic 默认 + JOURNEYPILOT_* 环境变量）。

RUN mkdir -p outputs uploads logs backups data/usage \
    && chown -R journeypilot:journeypilot /app

COPY infra/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

USER journeypilot
ENTRYPOINT ["/usr/local/bin/api-entrypoint.sh"]
