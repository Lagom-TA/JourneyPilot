# 架构决策记录（ADR）

本目录记录项目演进过程中的关键架构决策、背景依据以及备选方案的取舍。

每篇 ADR 包含统一的章节结构：`状态`、`影响`、`决定`、`为什么`、`替代方案与为什么没选`、`后果`（及可选的 `对应不变量`），新增记录按顺序递增编号。系统的整体模块划分请参阅[架构总览](../architecture/overview.md)，运行时约束请参阅[运行时约定](../invariants.md)。

| 编号 | 决策主题 |
|---|---|
| [ADR-0001](ADR-0001-local-single-profile.md) | 固定单一本地身份，不建账户系统 |
| [ADR-0002](ADR-0002-versioned-migrations.md) | 版本化迁移，API 进程不改 Schema |
| [ADR-0003](ADR-0003-sse-terminal-model.md) | Run 状态只转移一次，终态帧不重复发布 |
| [ADR-0004](ADR-0004-durable-local-jobs.md) | 用 PostgreSQL 做单机 durable 命令与任务存储 |
| [ADR-0005](ADR-0005-restart-does-not-resume-spending.md) | 重启后不自动继续花费额度 |
| [ADR-0006](ADR-0006-resource-budgets-and-isolation.md) | 每条高成本通道都有显式预算与隔离 |
| [ADR-0007](ADR-0007-core-default-enhancements-optional.md) | 核心能力默认可用，增强能力显式安装 |
| [ADR-0008](ADR-0008-config-single-source.md) | 配置只有一处定义，来源可查 |
| [ADR-0009](ADR-0009-ci-never-spends-on-providers.md) | CI 不调用真实付费 Provider |
| [ADR-0010](ADR-0010-natural-language-requirements.md) | 自然语言需求与研究方案直传各角色 |
| [ADR-0011](ADR-0011-generation-quality-owned-by-model.md) | 内容质量由模型负责，服务端只保证结构与资源边界 |
