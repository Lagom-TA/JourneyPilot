# 本地启动排障

日常启动入口与地址见 [AGENTS.md](../AGENTS.md)，首次安装见 [README](../README.zh-CN.md#快速开始)。仅在启动或开发遇到问题时查阅本文；新增排障经验也记录在这里。

## 先确定失败位置

```bash
./run.sh status
./run.sh logs backend       # 持续查看后端日志，Ctrl+C 结束查看
./run.sh logs frontend      # 持续查看前端日志
```

服务日志位于 `/tmp/journeypilot_logs/backend.log` 和 `frontend.log`。脚本只有在前后端均就绪后才会写入 `tmp/journeypilot.ports`，启动中尚无该文件不代表没有进程。

后端与前端代理分别检查：

```bash
curl --fail --max-time 10 http://localhost:8001/api/health/ready
curl --fail --max-time 10 http://localhost:8080/api/health/ready
```

成功时 HTTP 状态为 200，响应 `status` 为 `ready`；异常时查看响应中的具体组件。非默认端口以 `tmp/journeypilot.ports` 为准。

## Docker 未启动、卡住或命令长时间无输出

`run.sh` 会尝试启动 Docker Desktop，但 Docker 自身卡住时，`docker info` 也可能一直等待。macOS 可先直接探测默认 Docker Desktop socket，跳过 CLI 插件加载：

```bash
curl --silent --show-error --fail --max-time 5 \
  --unix-socket "$HOME/.docker/run/docker.sock" http://localhost/_ping
```

正常返回 `OK`。连接失败、超时，或正文出现 `Docker Desktop is unable to start`，都表示 Docker 尚不可用；需要检查正文，不能仅凭 curl 的退出码判断。

```bash
open -a Docker
# 已打开却仍不可用时，重启 Docker Desktop（会影响其他 Docker 项目）：
docker desktop restart --timeout 30
```

若正常重启仍报告 `processes still running`，通过 Docker Desktop 菜单退出后重开；必要时在活动监视器中结束确认卡住的 Docker 进程。恢复后再运行项目启动命令。保留现有容器、卷和数据库数据。

若 socket 返回 `OK`，但 `docker info` 仍卡住，检查 Docker CLI 插件输出；本机曾出现 `docker-ai` 插件元数据读取超时。此时 CLI 卡住与引擎是否可用需要分别判断。

## PostgreSQL / Redis 连接失败

仓库的 Compose 映射到宿主机的端口为 PostgreSQL **55433**、Redis **16379**；示例配置的默认端口可能不同。

```bash
docker compose -f infra/compose.yml ps
docker compose -f infra/compose.yml logs --tail=80 postgres redis
```

本地 API 使用 Compose 时，每次启动或重启均沿用端口覆盖：

```bash
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh restart
```

也可在本机 `config.yaml` 保存 `database.port: 55433` 和 `redis.port: 16379`，之后直接使用 `./run.sh start` / `restart`。容器内互联使用的端口不同，不要修改 Compose 的容器端口来解决宿主机连接问题。

## 已有实例或 8080 / 8001 端口被占用

`run.sh` 会拒绝重复启动，端口冲突时也不会自动切换端口。

```bash
./run.sh status
lsof -nP -iTCP:8080 -iTCP:8001 -sTCP:LISTEN
```

已有受管实例可使用 `./run.sh restart`；需要关闭时使用 `./run.sh stop`。脚本通过 `tmp/journeypilot.ports` 确认进程归属，不要手工删除该文件来绕过检查。

若报告 `ownership unconfirmed`，先查看提示的 PID 与监听端口；启动中的进程尚未监听时可稍后重试。其他项目占用端口时，先确认进程用途，或显式通过 `FRONTEND_PORT` 和 `JOURNEYPILOT_SERVER__PORT` 为本项目指定空闲端口；`run.sh` 会同步设置前端 API 代理。

## Python 依赖、配置或数据库迁移失败

`run.sh` 使用根目录 `.venv`，由 uv 同步锁定依赖，并在启动 API 前执行数据库迁移。不要手动切换到 `backend/.venv` 或绕过迁移直接启动 API。

```bash
# 展开查看被启动脚本摘要隐藏的依赖安装错误：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv sync --project backend --frozen --group local-embedding

# 校验配置，不打印密钥：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py config validate

# 诊断数据库版本和兼容性：
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py doctor
```

配置选择 `cross_encoder` 时还需要安装 `--group cross-encoder`。迁移被拒绝时，按 CLI 输出定位原因；不要删表、清卷或强行标记迁移版本。API Key 按 README 使用环境变量，排障记录中不要粘贴密钥或完整私有配置。

## 页面未更新或 API 不通

- 前端由 Vite 提供热更新，开发时访问 `http://localhost:8080`，无需为每次修改运行生产构建。
- `run.sh` 启动后端时显式关闭 Python 自动重载；修改后端代码后需要 `./run.sh restart`，并沿用启动时的环境变量。
- 后端健康而前端代理失败时，检查前端日志；通过 `run.sh` 重启可重新设置正确的 `VITE_PROXY_TARGET`。
- `./run.sh stop` 关闭前后端，PostgreSQL 和 Redis 容器继续保留。不要为停止网页服务执行删除数据库卷的命令。
