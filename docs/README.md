# 文档索引

项目的快速安装、配置与日常使用请先参阅 [中文 README](../README.zh-CN.md) 或 [English README](../README.md)。本目录汇总了架构设计、配置参考与开发测试文档：

| 文档 | 内容说明 |
|---|---|
| [配置参考](configuration.md) | 全部配置字段、默认值、取值范围与对应环境变量（由 CLI 自动生成） |
| [配置 Schema](config.schema.json) | `config.yaml` 的 JSON Schema 定义（可用于编辑器自动补全与校验） |
| [架构总览](architecture/overview.md) | 系统分层、核心模块职责与一次规划请求的完整生命周期 |
| [架构决策记录](adr/README.md) | 关键架构选择、背景考量与取舍记录（ADR） |
| [运行时约定](invariants.md) | 代码演进时需保持的系统约束及对应测试 |
| [本地启动排障](local-development-troubleshooting.md) | 端口冲突、Docker 容器、依赖安装、数据库迁移与页面访问排障指南 |
| [前端开发指南](../frontend/README.md) | 前端目录结构、状态与数据流、环境变量及构建命令 |
| [后端测试指南](../backend/tests/README.md) | 后端测试目录分工与单元测试、数据库测试运行方式 |
| [端到端测试指南](../frontend/e2e/README.md) | Playwright 浏览器测试套件、环境开关与常用运行命令 |
| [铁路站点快照说明](../backend/mcp/rail/README.md) | 仓内 12306 站表离线快照格式与更新流程 |
| [安全策略](../SECURITY.md) | 安全问题反馈渠道与自托管部署建议 |
| [参与贡献](../CONTRIBUTING.md) | 本地开发环境准备、检查命令与 Pull Request 指南 |
| [第三方声明](../NOTICE) | 第三方数据服务、字体与视觉素材的来源及许可说明 |

文档中的 `journeypilot <子命令>` 是以下运行方式的简写：

```bash
uv run --project backend python backend/journeypilot.py <子命令>
```

修改配置模型后，可通过以下命令校验配置参考文档与 JSON Schema 是否同步：

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend python backend/journeypilot.py config docs --check
```
