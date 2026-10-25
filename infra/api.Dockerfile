# JourneyPilot API 镜像。多阶段：编译工具留在 builder，运行层不带它们。
#
# 依赖分组由 build arg 选择（见 backend/pyproject.toml 的 [dependency-groups]）：
#   docker build -f infra/api.Dockerfile .                                       core + local-embedding（Compose 默认）
#   docker build -f infra/api.Dockerfile --build-arg DEPENDENCY_GROUPS="" .       只有 core
#   docker build -f infra/api.Dockerfile --build-arg DEPENDENCY_GROUPS="local-embedding cross-encoder" .
#
# 运行层以非 root 跑：这个进程接受用户上传并 fork 解析子进程，没有一步需要 root。

# ---------------------------------------------------------------------------
# builder：装依赖，带编译工具
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# 固定 uv 版本：一个会自己升级的安装器让「同一个 commit 构出同一个镜像」不再成立。
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
FROM node:22-slim AS node-mcp

WORKDIR /mcp
COPY backend/mcp/package.json backend/mcp/package-lock.json ./
# npm ci 而不是 npm install：后者会改写 lockfile，而一个构建期被改写却没被提交的
# lockfile 意味着镜像里的版本没有任何地方记着。
RUN npm ci --omit=dev

# ---------------------------------------------------------------------------
# runtime：不带编译工具，不以 root 跑
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# curl 供 healthcheck；libpq5 是 psycopg 的运行时（不是 libpq-dev）；
# nodejs 供 Node stdio MCP server。不带 npm：那几个 server 的包已在 node-mcp 阶段
# `npm ci` 装进镜像，`mcp_defaults` 直接调 node_modules/.bin 里的 bin，不需要 npx。
#
# 字体：**fonts-wqy-microhei，不是 fonts-noto-cjk**。Debian 的 Noto CJK 打的是 CFF
# （PostScript）轮廓，reportlab 的 TTFont 解析器嵌不进去（实测
# `postscript outlines are not supported`），于是启动预检会判 PDF 导出不可用。
# WenQuanYi 是 TrueType 轮廓，是 `services/pdf_export.py` 候选表里的首选项。
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        fonts-wqy-microhei \
        nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin --uid 10001 journeypilot

# 维护 CLI 在容器内也需要与默认 PostgreSQL 18 匹配的客户端。
# 没有 pg_dump/pg_restore 时，非空库下一次升级会在备份闸门被拒绝。
ARG POSTGRES_CLIENT_MAJOR=18
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/keyrings/postgresql.asc \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/postgresql.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main' \
        > /etc/apt/sources.list.d/postgresql.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-client-${POSTGRES_CLIENT_MAJOR}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/journeypilot /opt/journeypilot
COPY --from=node-mcp /mcp/node_modules /app/backend/mcp/node_modules
ENV PATH="/opt/journeypilot/bin:/app/backend/mcp/node_modules/.bin:${PATH}" \
    VIRTUAL_ENV="/opt/journeypilot" \
    PYTHONPATH="/app/backend" \
    PYTHONUNBUFFERED=1

COPY backend/travel_agent/ ./backend/travel_agent/
COPY backend/mcp/ ./backend/mcp/
COPY backend/main.py backend/journeypilot.py backend/alembic.ini backend/pyproject.toml ./backend/
COPY backend/migrations/ ./backend/migrations/
COPY README.md ./
COPY docs/ ./docs/
# Build the frontend before the image; the API serves its generated output.
COPY backend/static/ ./backend/static/
# **不复制 config.example.yaml 当 config.yaml**：一份示例伪装成真实配置，
# 会让「我的配置没生效」变成「我改的那份文件根本没被读」。Compose 把宿主机的
# config.yaml 挂进来；没挂也能跑（全部走 Pydantic 默认 + JOURNEYPILOT_* 环境变量）。

RUN mkdir -p outputs uploads logs backups data/usage \
    && chown -R journeypilot:journeypilot /app

COPY infra/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

USER journeypilot
ENTRYPOINT ["/usr/local/bin/api-entrypoint.sh"]
