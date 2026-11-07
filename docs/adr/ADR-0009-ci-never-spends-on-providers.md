# ADR-0009：CI 不调用真实付费 Provider

状态：已采纳
影响：`.github/workflows/*`、测试分层

## 决定

PR 和 main 推送自动运行；`changes` 作业按变更路径决定哪些作业运行，没受影响的作业直接跳过，手动触发时全部运行，工作流文件本身变化时相关作业全部运行：

- 后端（`backend/`、生成的配置文档变化时）：ruff；`config validate` 与 `config docs --check`；非数据库单元测试与离线迁移 SQL；迁移脚本目录只有一个 alembic head。只安装 `dev` 依赖组，不装本地 embedding 组：单元测试不依赖它。PDF 字体缺失时 PDF 测试失败而不是跳过。
- 前端与 MCP（`frontend/`、`backend/mcp/` 变化时，同一个 Node 22 作业）：`npm run check`（类型检查、lint、单元测试、构建）；MCP 的 `npm ci` 与站表数据模块语法检查。
- shell（`.sh` 文件变化时）：`bash -n`、固定版本的 shellcheck，以及 `infra/scripts/supervise_harness.sh` 的服务监督检查。
- Docker（后端、前端、`infra/` 变化时）：`docker compose config`、带层缓存的 API 镜像构建与镜像 smoke（`config validate`、`config docs --check`、Node 22、前端静态产物、`pg_dump`）。
- 密钥扫描（每次运行）：gitleaks，外加一次种入合成密钥、要求扫描器报出的自检。

依赖安装使用锁文件，不另设重复安装矩阵或源码字符串检查，也不设覆盖率下限：覆盖率数字不说明测试是否有用。

数据库迁移和集成测试在 Actions 的 `PR` 工作流中手动触发，使用 PostgreSQL 与 Redis service container，不调用付费 Provider。完整应用、浏览器交互与真实 Provider 的验证不在自动门禁里：需要时在隔离环境手动运行，并使用显式提供的低额度 Key；不能用 CI 通过代替实际功能验证。

## 为什么

一个每次 PR 都调用付费模型的门禁有两个问题：它花钱，而且**它不稳定** —— 上游一次
限流会让一次无关的改动变红，然后所有人开始忽略红灯。合同测试要验证的是我们的代码，
不是上游今天的心情。

## 替代方案与为什么没选

- **每次 PR 跑一小段真实调用**：不确定性进入门禁，红灯失去意义。
- **完全不测 Provider 交互**：那些兼容逻辑（json_schema 降级、reasoning 方言、
  tool 消息顺序）恰恰是事故最多的地方。它们改由 capability 声明 + 单元测试承载
  （见 [ADR-0008](ADR-0008-config-single-source.md)）。

## 后果

- Fake LLM 必须支持 invoke / stream / tool calls / 畸形 JSON / 超时 / 可重试错误 /
  usage 元数据 / 延迟与取消。只返回固定字符串的 fake 验证不了工作流边界。
- 重型矩阵（10k 事件、kill-point 全矩阵、多架构镜像、备份恢复全量 fixture）不进入
  定时自动化；需要时在本地或隔离环境显式运行。
