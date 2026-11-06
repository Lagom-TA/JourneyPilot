# 文档

从 [English README](../README.md) 或 [中文 README](../README.zh-CN.md) 开始：安装、配置与使用都在那里；本目录是深入阅读入口。

| 文档 | 用途 |
|---|---|
| [配置参考](configuration.md) | 全部字段、默认值、取值范围与环境变量（生成物） |
| [配置 Schema](config.schema.json) | 描述 `config.yaml` 形态的 JSON Schema（生成物，可直接用于编辑器校验） |
| [架构总览](architecture/overview.md) | 系统形态、模块归属与一次请求的生命周期 |
| [架构决策记录](adr/README.md) | 每个决定、理由与被否掉的替代方案 |
| [运行时约定](invariants.md) | 修改代码时必须保持的约束，以及对应的测试 |
| [本地启动排障](local-development-troubleshooting.md) | 端口、Docker、依赖、迁移与页面/API 问题的排查 |
| [前端开发](../frontend/README.md) | 前端目录、请求层、环境变量、构建与检查命令 |
| [后端测试](../backend/tests/README.md) | 测试策略、目录分工与数据库测试入口 |
| [浏览器测试](../frontend/e2e/README.md) | Playwright 套件、开关与证据目录 |
| [铁路 MCP](../backend/mcp/rail/README.md) | 仓内 12306 站表快照与刷新流程 |
| [安全策略](../SECURITY.md) | 漏洞报告渠道、自托管安全边界 |
| [参与贡献](../CONTRIBUTING.md) | 开发环境、检查命令与提交要求 |
| [第三方声明](../NOTICE) | 第三方数据、字体与素材的来源与许可 |

文档和代码注释里的 `journeypilot <子命令>` 是 `uv run --project backend python backend/journeypilot.py <子命令>` 的简写；仓库没有安装控制台脚本。

配置参考与 Schema 由配置模型生成，用下面的命令检查是否一致：

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py config docs --check
```
