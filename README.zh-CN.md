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

首页默认用一句话描述旅行，偏好直接写进描述；切换到“按条件规划”可以直接填写路线、日期、同行人数、预算和旅行风格，人数支持点选与自填。两种方式各自保留草稿；旅行票据与行李签呈现同一提案，场景缓慢轮换，悬停或填写时暂停，点选只更新当前方式，不会直接提交。完整规划会先梳理需求，必要时核实地点并继续提问；确认研究方案后，再开展地点、住宿、交通和天气的正式研究。
生成工作台以行程摘要、四阶段导航和当前任务组织内容。调研任务默认显示最新动态，点击整块任务可展开或收起查询、来源与公开工作说明；手动展开的记录在任务结束后保持可读。停止按钮位于阶段导航右侧；追问与研究方案各使用独立的提交区。
研究未完成时会保留已有成果；重试沿用本次规划的时限设置。
连接断开时，本次执行会中断；重新打开后可查看已保存的状态和内容，支持继续的规划需要手动继续。
不同会话可以同时生成；切换会话不会中断其他会话的运行。
启用运行预算时，模型调用前会估算开销；价格或用量不完整时，费用上限无法保证精确生效。

规划完成后，你可以：

- 按天查看景点、餐饮、住宿与交通，在地图上找到行程中的地点。
- 打开阅读版、查看可用的资料来源，或导出 PDF。
- 在同一趟旅行中继续对话，提出调整；有需要时可以分几轮补充细节。天气有变化时，也可以把建议带入对话。
- 保存旅行风格和自己的资料，让后续规划参考。

交付工作台以满幅地图和城市停留段呈现全程，进入某天后展开日程与地图对页。密集地点随缩放聚合；手机用两档底部面板查看日程，同时保留清晰的地图。尚未安排的事项在相关日期显示，完整说明与事实来源按需展开；阅读版提供 PDF 导出。

手动添加或删除记忆时，系统会保留操作及相关内容，供之后的记忆总结参考，并发送给配置的快速模型。用户明确改变想法时，系统可以更新已有记忆。画像会在下一次对话记忆总结运行时整理，在此之前规划仍可能使用旧画像；删除全部记忆会清空操作记录中的内容，只保留不含内容的清空记录。

来源、价格和实时信息取决于所用服务。价格按单项展示，暂不汇总；PDF 会标明尚未安排的事项。部分路线可能是估算，房态、车票和预约情况也可能变化；JourneyPilot 不代为预订或支付。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/)、Python 3.11、Node.js 22 或更高版本和 npm，以及带 Compose 的 Docker Desktop 或 Docker Engine。还需要一个可用的模型服务及其凭据。

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

启动脚本会复用已有的 PostgreSQL 和 Redis 容器，不会因 Compose 配置变化自动重建它们。如需应用容器配置变更，请先检查影响，再自行运行 Compose。

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

网页和 API 均通过 <http://localhost:8001> 访问。Compose 会读取根目录的 `.env`；仅在宿主 shell 中导出模型密钥，不会自动传入 API 容器。数据库和 Redis 也分别向宿主机发布 `55433`、`16379` 端口；设置 `JOURNEYPILOT_DATABASE__PORT` 可让数据库改用其他宿主机端口。

JourneyPilot 面向单用户自托管场景，目前没有账户系统或内建鉴权。请在可信网络中运行；部署到不可信网络前，请配置访问控制，并检查 API、数据库和 Redis 的监听地址。详见[安全策略](SECURITY.md)。

## 配置与数据

设置来自内置默认值、`config.yaml` 和环境变量，环境变量优先。常用标量字段可通过 `JOURNEYPILOT_<段>__<字段>` 覆盖，例如 `JOURNEYPILOT_DATABASE__PORT`。完整字段、默认值与环境变量见[配置参考](docs/configuration.md)。

```bash
uv run --project backend python backend/journeypilot.py config validate
uv run --project backend python backend/journeypilot.py config show
uv run --project backend python backend/scripts/check_mcp.py
```

默认工具包含网页搜索、OpenStreetMap/Nominatim、12306 和汇率查询；规划天气使用内置的 Open-Meteo 适配器。第三方 Open-Meteo MCP 默认禁用：该包启动时会向第三方域名发送运行通知，可将 `mcp.servers.open-meteo.disabled` 设为 `false` 显式启用。高德、百度、Tavily、Brave、Duffel 等服务可按需配置。工具同名时保留已注册的来源，MCP 服务按配置顺序注册。数据覆盖范围和调用结果由各服务决定，中国境内路线查询需要高德密钥。模型及外部服务可能产生费用。

`run.sh` 会安装锁定的 Node MCP 依赖；直接启动后端前，可运行 `npm --prefix backend/mcp ci --omit=dev` 安装这些依赖。

默认使用本地 Qwen3 ONNX 模型生成知识库向量，也可配置兼容的远程向量服务。向量结果不完整时，资料索引会失败并保留原资料。仓库附带一份[小规模出厂语料](backend/data/corpus/factory/README.md)，可按说明导入；可选的本地二进制种子不随仓库提供。

数据库迁移由启动脚本或容器入口在 API 启动前执行。检查数据库状态和创建备份：

```bash
uv run --project backend python backend/journeypilot.py doctor
uv run --project backend python backend/journeypilot.py backup
```

备份的数据库转储与行数清单来自同一快照，恢复前会校验所需文件和校验值。

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
