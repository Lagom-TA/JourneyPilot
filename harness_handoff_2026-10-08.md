# JourneyPilot Harness：2026-10-08 续接收尾状态

工作目录：`/home/tang/projects/JourneyPilot`。本文件已更新为本轮实施后的状态；初始交接的历史内容保存在 Git 中。实际故障路径和各批实现见 `harness_review_2026-10-08.md`，复现方式见 `docs/review/harness-experiments-2026-10-08.md`。

## 分支和授权

- `study` 已从本轮修改前的远端 main 建立并推送，固定 SHA：`5e08d829a04048c6f6dba86b191813e22825c106`。后续不修改 study。
- 所有实现、原先未提交的工作和分组提交都在 main；没有 reset、清理或覆盖历史未提交改动。
- 用户后续已授权适时 commit/push 和付费模型测试，覆盖初始交接中的旧限制。业务数据库没有迁移。
- 不开启子 agent，不输出 config.yaml/凭据。权限为 unrestricted/approval never，不传 sandbox_permissions。

截至实验材料归档前的提交：

| 提交 | 范围 |
|---|---|
| `ca8e8bb` | 保存此前计量/上下文修改，新增 worker/ReAct 恢复 |
| `0232d70` | usage 持久 outbox 与 ledger 确认边界 |
| `7bfa78c` | composition 固定合同/动态 runtime 与压缩保真 |
| `faf2375` | 任务质量路由与模型请求协议 |
| `4ad7891` | 恢复 fencing、真实图回归、并发 outbox 与账单完整性收尾 |

最后一组是实验框架、结果、审查报告和本交接文件。用 `git log --oneline study..main` 与 `git ls-remote origin refs/heads/main refs/heads/study` 核对最终提交/远端状态；不通过改动 study 保存新实现。

## 保持的产品与控制合同

保留 LangGraph、typed research workers/gates 和唯一 delivery finalizer。primary 精确模型名 `openai/gpt-6.1-sol`，reasoning medium；fast `deepseek/deepseek-v4.1-flash`，reasoning low，不关闭。累计 Run budget 默认只观察，限额 null，不增加 Token、费用或调用阻断。单请求 max output 与累计预算分开处理。

Sol 目前承担无工具的 Chat Completions 组合/仲裁与 schema-only repair。官方协议要求 Sol 工具调用走 Responses；本轮增加 guard，没有实现 Responses 工具 adapter。跨模型修复保留工具数据作为历史观察，移除 foreign opaque reasoning/active tool protocol。

## 已完成的架构实施

1. **生命周期与重放**：0009 `run_worker_journals`，typed serializer、version CAS、活 lease fencing。模型准入→完整 assistant/tool/reasoning→Gateway 信封→typed worker 输出分别提交。scope v2 加入 LangGraph task identity；同一 pending task 恢复重放，新 dispatch 不重复旧失败。只读未提交工具允许再查；不确定写操作不重复。取消、deadline、ask_user 关闭 tool 配对，未完成流不承认为完整产物。
2. **账单完整性**：SQLite WAL + FULL 持久 outbox，先准入、后 finish，commit 后精确 ack；后台补记与冲突隔离。并发写和表结构升级加锁；hostname/PID 启动时间识别遗留调用。历史价格不重算，账单未知/pending/写盘失败进入 API/前端，不伪装完整零用量。
3. **上下文与压缩**：三个研究 worker 和组合节点固定 system 合同，动态 task/evidence/schema 放 runtime；任务范围研究投影和完整定向补研闭包。保留硬约束，完整回合裁剪；摘要失败不推进 compaction CAS。按下一请求窗口计量，包含真实输出预留及新 RAG/tool/question。
4. **路由与协议**：按 TaskKind + typed quality feedback 路由；研究保持 fast，组合/全局仲裁 primary；无工具 schema reject 可升级，证据 unknown 进入补研。模型名称和协议独立判断，medium/low 保留。
5. **横向收尾/实验**：旧 graph tool envelope 不能绕过 Gateway TTL/权限/当前审计；side-effecting 结果不进入调用内缓存。可复現矩阵、付费协议校准、JSONL 聚合以及独立 PostgreSQL journal/ledger/真实 LangGraph 验证脚本均已归档。

## 最新验证与证据

- 全量后端：**477 passed / 116 skipped**。skip 依赖项目 PostgreSQL/pgvector 条件，不代表通过集成。
- 前端：**23 项通过**，TypeScript 与生产构建通过。Ruff 与 diff check 通过。
- 独立 PostgreSQL 14：0008/0009 升降级、旧行/历史价格、幂等/冲突、typed replay、version CAS、活 lease、fingerprint 全部通过；真实 AsyncPostgresSaver + WorkerJournalStore 验证两种并行崩溃边界，不重复执行或合并产物。
- 离线请求矩阵 24 项；fake-model/真实-Gateway 恢复矩阵 **24/24**。标签不等于真实缓存/质量实验。
- 已完成付费协议请求 **6 次**，全部通过、usage 完整、无截断；配置价格合计 **$0.0016389**。cache read rate 0。Sol medium 小请求报告 reasoning 0，Flash low 有 reasoning；不据此声称关闭推理。
- 版本控制证据：`docs/review/harness-verification-2026-10-08.json`（依赖版本、fixture/API 结果、证据 SHA256）；实验说明 `docs/review/harness-experiments-2026-10-08.md`。

继续验证时复用 `temp/harness-review-2026-10-05/test-venv`。已完成的付费 probes 不必重跑；该目录的原始日志、manifest 和固定参考仓库仍可复用。

| 参考 | 固定 SHA |
|---|---|
| openai/codex | `823ea830c0fd418b09ff02d36cad9a1fff66465b` |
| deepseek-ai/deepseek-harness | `5badb15009ae1756c3afe0ae0cef1faafc290ccc` |

## 部署前提与仍未证明的结果

可在现有环境完成的审查、实现和验证已收尾。部署前使用既有 `journeypilot migrate` 升级至 0009，并将 `data/usage` 挂载持久卷。journal 与 TripRun 同生命周期，FK cascade 清理；没有定时删除可恢复历史。磁盘故障 fallback 明确不完整，不能保证再崩溃后的恢复；跨主机卷迁移不自动处理。

独立数据库只建所需 stub/ledger/journal/checkpoint，不是完整业务 pgvector 集成。真实 provider→packet admission→typed gates→Delivery Bundle→SSE/恢复的端到端，以及真实 cache/质量/成功交付成本 A/B，仍需部署环境。协议校准/替代图合并不能替代这些验证。embeddings 不属于该 LLM ledger，本地 Qwen 不编造外部费用。工具 deferred 的目录/激活开销可能超过精简 full schema，应按真实运行衡量，不能保证固定比例收益。
