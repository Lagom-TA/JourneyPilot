# Documentation / 文档

Start with the [English README](../README.md) or [中文 README](../README.zh-CN.md) for installation, configuration, and usage.

| Document / 文档 | Purpose / 用途 |
|---|---|
| [Configuration reference / 配置参考](configuration.md) | Fields, defaults, and environment variables / 字段、默认值与环境变量 |
| [Configuration schema / 配置 Schema](config.schema.json) | Generated JSON Schema / 自动生成的 JSON Schema |
| [Architecture / 架构总览](architecture/overview.md) | Deployment and request lifecycle / 部署结构与请求生命周期 |
| [Architecture decisions / 架构决策](adr/README.md) | Decisions, rationale, and alternatives / 决策、理由与替代方案 |
| [Runtime invariants / 运行时保证](invariants.md) | Contracts that changes must preserve / 修改代码时应保持的约束 |
| [Frontend / 前端开发](../frontend/README.md) | Local development and builds / 本地开发与构建 |
| [Backend tests / 后端测试](../backend/tests/README.md) | Test strategy and database checks / 测试策略与数据库验证 |
| [Browser tests / 浏览器测试](../frontend/e2e/README.md) | End-to-end commands and provider usage / 端到端测试命令与模型调用范围 |
| [Rail MCP / 铁路 MCP](../backend/mcp/rail/README.md) | Railway tool setup and station data / 铁路工具配置与车站数据 |

The configuration reference and schema are generated from the configuration models. Check consistency with `uv run --project backend python backend/journeypilot.py config docs --check`.

配置参考和 Schema 由配置模型生成，可用上述命令检查一致性。
