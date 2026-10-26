# 架构决策记录（ADR）

本目录记录已经做出的架构选择、背景与影响；部分记录包含当时的替代方案。每份 ADR 说明一个决定及其边界，不承担操作手册或设计规范职责。

架构总览见 [`../architecture/overview.md`](../architecture/overview.md)，运行时约定见 [`../invariants.md`](../invariants.md)。

| 编号 | 决定 |
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
| [ADR-0010](ADR-0010-request-contract-control-plane.md) | 用唯一请求合同与确定性编排控制研究工作流 |
| [ADR-0013](ADR-0013-generation-quality-owned-by-model.md) | 内容质量由模型负责，移除内容质量验证体系 |
