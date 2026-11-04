<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-lockup-night.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-lockup-day.png">
  <img src="docs/assets/logo-lockup-day.png" alt="JourneyPilot" width="620">
</picture>

<h1>JourneyPilot</h1>

<p>一份能继续查看、讨论和调整的旅行计划。</p>

[![License: MIT](https://img.shields.io/badge/license-MIT-8f6736?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-8f6736?style=flat-square)](https://www.python.org/)
[![Node 22](https://img.shields.io/badge/node-22-8f6736?style=flat-square)](https://nodejs.org/)

[English](README.md) · **简体中文**

</div>

JourneyPilot 是一个开源、自托管的 AI 旅行规划工作台。告诉它想去哪里、什么时候出发，以及同行人和旅行偏好，它会查找资料，整理每天的行程，并把日程、地图和阅读版放在同一个工作区。

产品界面目前使用简体中文。

## 规划一趟旅行

可以用一句话描述旅行，也可以填写目的地、日期和偏好。完整规划会先梳理需求，必要时核实地点并继续提问；确认研究方案后，再开展地点、住宿、交通和天气的正式研究。
研究未完成时会保留已有成果；重试沿用本次规划的时限设置。

规划完成后，你可以：

- 按天查看景点、餐饮、住宿与交通，在地图上找到行程中的地点。
- 打开阅读版、查看可用的资料来源，或导出 PDF。
- 在同一趟旅行中继续对话，提出调整；有需要时可以分几轮补充细节。天气有变化时，也可以把建议带入对话。
- 保存旅行风格和自己的资料，让后续规划参考。

来源、价格和实时信息取决于所用服务。价格按单项展示，暂不汇总；PDF 会标明尚未安排的事项。部分路线可能是估算，房态、车票和预约情况也可能变化；JourneyPilot 不代为预订或支付。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/)、Python 3.11、Node.js 22（最低 20.19）和 npm，以及带 Compose 的 Docker Desktop 或 Docker Engine。还需要一个可用的模型服务及其凭据。

```bash
git clone https://github.com/Lagom-TA/JourneyPilot.git
cd JourneyPilot
cp backend/config.example.yaml config.yaml
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
```

选择模型配置模板。下面以 DeepSeek 为例；`--list` 可以查看其他模板。按实际服务填写 API Key：

```bash
uv run --project backend python backend/journeypilot.py configure --list
uv run --project backend python backend/journeypilot.py configure --provider deepseek
export JOURNEYPILOT_PRIMARY_MODEL__API_KEY="your-api-key"
export JOURNEYPILOT_FAST_MODEL__API_KEY="your-api-key"
```

在仓库根目录启动：

```bash
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

首次启动会安装依赖，通过 Compose 启动 PostgreSQL 和 Redis，执行数据库迁移，再启动 API 和网页。默认本地向量模型会在首次使用时下载。

| 服务 | 地址 |
| --- | --- |
| 网页 | <http://localhost:8080> |
| API 文档 | <http://localhost:8001/docs> |
| 就绪检查 | <http://localhost:8001/api/health/ready> |

`run.sh` 在前台管理服务；可以在另一个终端查看状态或停止：

```bash
./run.sh status
./run.sh logs backend       # 前端日志：./run.sh logs frontend
./run.sh check
./run.sh stop
```

上面的数据库和 Redis 端口与仓库 Compose 配置一致。再次执行 `./run.sh restart` 时，需要重新提供这两个环境变量，或将端口写入 `config.yaml`。停止时，API 会关闭后台任务和 MCP 会话，刷写用量后再关闭数据库与 Redis 连接。启动问题见[本地开发排障](docs/local-development-troubleshooting.md)。

## 使用 Docker Compose

也可以将网页与 API 一起运行在容器中。先按上面的步骤准备 `config.yaml`，再在仓库根目录创建 `.env`，填写模型及需要的数据服务密钥，例如：

```dotenv
JOURNEYPILOT_PRIMARY_MODEL__API_KEY=your-api-key
JOURNEYPILOT_FAST_MODEL__API_KEY=your-api-key
```

```bash
docker compose -f infra/compose.yml up -d --build
docker compose -f infra/compose.yml logs -f api
```

网页和 API 均通过 <http://localhost:8001> 访问。Compose 会读取根目录的 `.env`；仅在宿主 shell 中导出模型密钥，不会自动传入 API 容器。数据库和 Redis 也分别向宿主机发布 `55433`、`16379` 端口。

JourneyPilot 面向单用户自托管场景，目前没有账户系统或内建鉴权。请在可信网络中运行；部署到不可信网络前，请配置访问控制，并检查 API、数据库和 Redis 的监听地址。详见[安全策略](SECURITY.md)。

## 配置与数据

设置来自内置默认值、`config.yaml` 和环境变量，环境变量优先。常用标量字段可通过 `JOURNEYPILOT_<段>__<字段>` 覆盖，例如 `JOURNEYPILOT_DATABASE__PORT`。完整字段、默认值与环境变量见[配置参考](docs/configuration.md)。

```bash
uv run --project backend python backend/journeypilot.py config validate
uv run --project backend python backend/journeypilot.py config show
uv run --project backend python backend/scripts/check_mcp.py
```

默认工具包含网页搜索、OpenStreetMap/Nominatim、12306、Open-Meteo 和汇率查询；高德、百度、Tavily、Brave、Duffel 等服务可按需配置。数据覆盖范围和调用结果由各服务决定，中国境内路线查询需要高德密钥。模型及外部服务可能产生费用。

默认使用本地 Qwen3 ONNX 模型生成知识库向量，也可配置兼容的远程向量服务。仓库附带一份[小规模出厂语料](backend/data/corpus/factory/README.md)，可按说明导入；可选的本地二进制种子不随仓库提供。

数据库迁移由启动脚本或容器入口在 API 启动前执行。检查数据库状态和创建备份：

```bash
uv run --project backend python backend/journeypilot.py doctor
uv run --project backend python backend/journeypilot.py backup
```

## 开发

```bash
# 在仓库根目录运行
uv sync --project backend --locked --group local-embedding --group dev
uv run --project backend ruff check --config backend/pyproject.toml backend/travel_agent/ backend/tests/ backend/scripts/
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
npm --prefix frontend ci
npm --prefix frontend run check
```

数据库集成测试需要可访问的 PostgreSQL；浏览器测试及真实模型测试的前置条件见[端到端测试说明](frontend/e2e/README.md)。

- [文档索引](docs/README.md) · [系统架构](docs/architecture/overview.md) · [配置参考](docs/configuration.md)
- [参与贡献](CONTRIBUTING.md) · [安全策略](SECURITY.md)

## 许可

[MIT License](LICENSE)。第三方数据、字体和素材见 [NOTICE](NOTICE)。
