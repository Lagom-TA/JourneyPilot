# ADR-0009：CI 不调用真实付费 Provider

状态：已采纳
影响：`.github/workflows/*`、测试分层

## 决定

PR 和 main 推送自动运行：后端 lint、配置、单元测试与离线迁移 SQL；前端类型检查、lint、单元测试与构建；MCP 依赖安装；shell 语法检查；Docker 镜像构建与 smoke；密钥扫描。依赖安装使用锁文件，不另设重复安装矩阵或源码字符串检查。

数据库迁移和集成测试在 Actions 的 `PR` 工作流中手动触发，使用 PostgreSQL 与 Redis service container，不调用付费 Provider。完整应用、浏览器交互与真实 Provider 的验证不在自动门禁里：需要时在隔离环境手动运行，并使用显式提供的低额度 Key；不能用 CI 通过代替实际功能验证。

项目不保留定时 nightly 或 release 工作流。

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
