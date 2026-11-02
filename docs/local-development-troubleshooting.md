# 本地启动排障

日常启动入口与地址见 [AGENTS.md](../AGENTS.md)，首次安装见 [README](../README.zh-CN.md#快速开始)。只在启动或开发遇到问题时查阅本文。

## 先确定失败位置

```bash
./run.sh status
./run.sh logs backend       # 持续查看后端日志，Ctrl+C 结束查看
./run.sh logs frontend      # 持续查看前端日志
```

服务日志位于仓库内的 `tmp/logs/backend.log` 和 `tmp/logs/frontend.log`。`run.sh` 只有在前后端均就绪后才写入 `tmp/journeypilot.ports`；启动中还没有这个文件不代表没有进程。

后端与前端代理分别检查：

```bash
curl --fail --max-time 10 http://localhost:8001/api/health/ready
curl --fail --max-time 10 http://localhost:8080/api/health/ready
```

成功时 HTTP 状态为 200，响应 `status` 为 `ready`；异常时查看响应里的具体组件。非默认端口以 `tmp/journeypilot.ports` 或 `./run.sh status` 输出为准。

## Docker / Compose

`run.sh` 会尝试启动 Docker（macOS 用 `open -a Docker`，Linux 尝试 `systemctl`/`service`），并用 `infra/compose.yml` 只启动 **PostgreSQL 和 Redis**；API 与前端由脚本在本机拉起。

如果 Docker 本身卡住，`docker info` 也可能一直等待。macOS 可以先直接探测 Docker Desktop socket，跳过 CLI 插件加载：

```bash
curl --silent --show-error --fail --max-time 5 \
  --unix-socket "$HOME/.docker/run/docker.sock" http://localhost/_ping
```

正常返回 `OK`。连接失败、超时，或正文出现 `Docker Desktop is unable to start`，都表示 Docker 尚不可用；要检查正文，不能只看 curl 退出码。仍不可用时重启 Docker Desktop（会影响其他 Docker 项目），必要时在活动监视器中结束卡住的 Docker 进程。恢复后再运行启动命令；保留现有容器、卷和数据库数据。

Compose 映射到宿主机的端口是 PostgreSQL **55433**、Redis **16379**。`backend/config.example.yaml` 面向本机 PostgreSQL（5433/6379），所以用 Compose 时要显式覆盖：

```bash
docker compose -f infra/compose.yml ps
docker compose -f infra/compose.yml logs --tail=80 postgres redis
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

也可以把 `database.port: 55433`、`redis.port: 16379` 写进 `config.yaml`，之后直接用 `./run.sh`。容器内互联端口不同，不要改 Compose 的容器端口来解决宿主机连接问题。

## PostgreSQL / Redis 连接失败

确认连接参数（`config.yaml` 的 `database.*` / `redis.*`，或对应的 `JOURNEYPILOT_*` 环境变量）与 Compose 端口一致。Compose 不可用时也可以使用本机 PostgreSQL/Redis，但需要：

- PostgreSQL 带 `vector` 与 `pgcrypto` 扩展（`zhparser` 可选）；
- 为 `embedding.dimensions` 对应的 pgvector 维度建库；
- 数据库账号有建表/迁移权限（迁移由 `journeypilot migrate` 执行，API 进程只读校验）。

连不上时先看 `./run.sh logs backend` 的错误，再跑：

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py doctor
```

## 已有实例或端口被占用

`run.sh` 会拒绝重复启动，端口冲突时也不会自动切换端口。

```bash
./run.sh status
lsof -nP -iTCP:8080 -iTCP:8001 -sTCP:LISTEN
```

已有受管实例可用 `./run.sh restart`；需要关闭时用 `./run.sh stop`。脚本通过 `tmp/journeypilot.ports` 确认进程归属，不要手工删除这个文件来绕过检查。

若报告 `ownership unconfirmed`，先查看提示的 PID 与监听端口；启动中的进程尚未监听时可以稍后重试。其他项目占用端口时，先确认用途，或显式为前端指定空闲端口：

```bash
FRONTEND_PORT=8090 ./run.sh start
```

后端端口来自 `server.port`（`config.yaml` 或 `JOURNEYPILOT_SERVER__PORT`），修改后同样用 `./run.sh status` 确认。

## Python 依赖、配置或数据库迁移失败

`run.sh` 使用根目录 `.venv`，以 `uv sync --frozen` 同步锁定依赖，并在启动 API 前执行数据库迁移。不要手动切换到 `backend/.venv`，也不要绕过迁移直接启动 API。

```bash
# 展开查看被启动脚本摘要隐藏的依赖安装错误：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv sync --project backend --frozen --group local-embedding

# 校验配置，不打印密钥：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py config validate

# 诊断数据库版本、结构与迁移状态：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py doctor
```

配置选择 `rerank.provider=cross_encoder` 时还需要安装 `--group cross-encoder`。迁移被拒绝时按 CLI 输出定位原因：**未版本化的非空库一律拒绝**，需要重建数据库或从匹配的备份恢复，不要手工 `stamp` 迁移版本。API Key 按 README 使用环境变量；排障记录中不要粘贴密钥或完整私有配置。

## 页面未更新或 API 不通

- 前端由 Vite 提供热更新，开发时访问 `http://localhost:8080`，不需要为每次修改跑生产构建。
- `run.sh` 启动的后端固定关闭自动重载；修改 Python 代码后需要 `./run.sh restart`。`restart` 不会保存环境变量，端口/数据库覆盖要重新带上。
- 后端健康而前端代理失败时，先看前端日志；通过 `run.sh` 重启会重新设置正确的 `VITE_PROXY_TARGET`。
- 已交付行程的地图区域提示加载失败，且浏览器网络面板对 `node_modules/.vite/deps/react-leaflet.js`、`leaflet.js` 返回 504 `Outdated Optimize Dep` 时，是 Vite 的预打包依赖缓存缺失或过期。在 `frontend/` 运行 `npx vite optimize` 重建依赖，或执行 `./run.sh restart`；不要为此删除行程或数据库数据。
- `./run.sh stop` 只关闭前后端，PostgreSQL 和 Redis 容器继续保留。不要为停止网页服务执行删除数据库卷的命令。

## 安全边界

默认 `server.host` 是 `0.0.0.0`，产品没有账户与鉴权。只在可信网络暴露；公网或不可信网络部署时把监听地址收紧到 `127.0.0.1`（或放在带认证的反向代理之后），并阅读 [SECURITY.md](../SECURITY.md)。

提交 issue 前先确认日志里没有 API Key、数据库口令或完整私有配置。
