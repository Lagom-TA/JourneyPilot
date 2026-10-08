# Harness 实验与验证记录（2026-10-08）

架构批 A–E 与正式部署批 F1–F5 的实现、故障路径见根目录 `harness_review_2026-10-08.md`。历史离线/协议材料保存在 [harness-verification-2026-10-08.json](harness-verification-2026-10-08.json)；最新真实运行结果保存在 [harness-formal-verification-2026-10-08.json](harness-formal-verification-2026-10-08.json)。两者均有固定参考 SHA 与证据摘要，不包含配置凭据或原始用户提示词，验证范围分别标明。

## 历史架构批 A–E 实测范围

| 验证 | 实际结果 | 范围 |
|---|---|---|
| 全量后端 | 477 passed / 116 skipped | 跳过项依赖项目 PostgreSQL/pgvector 条件 |
| 前端 | 23 passed；类型检查、生产构建通过 | SSE 去重、未知用量与待落库完整性 |
| Ruff / diff check | 通过 | 后端、测试及新脚本 |
| 独立 PostgreSQL 14 ledger | 通过 | 0008 升降级、旧账单、幂等/冲突、价格快照、fingerprint |
| 独立 PostgreSQL 14 journal + LangGraph | 通过 | 0009、CAS、活 lease、typed replay、真实 pending write/fan-in 恢复 |
| 离线请求矩阵 | 24 个 fixture | 冷/暖、新 run/补研/恢复、简单/复杂、full/deferred 标签；API 用量未知 |
| 故障矩阵 | 24/24 通过 | fake model、真实 Gateway、内存审计/journal、取消和完成结果重放 |
| 付费文本协议 | 4/4 通过 | Sol medium / Flash low 各两次，约束 JSON 校准 |
| 付费工具协议 | 2 次请求通过 | Flash low，synthetic 工具调用→工具结果→最终 JSON |

六次付费调用均有完整 usage，无截断；按配置价格计算费用共 **$0.0016389**。加权 cache read rate 为 **0**。五个独立协议 trial 的 p95 为约 **5.51 秒**，这是很小样本的协议延迟，不是生产行程交付 p95。Sol 两个小请求的 reasoning effort 均为 medium，API 报告 reasoning output 为 0；Flash 请求返回 reasoning。没有关闭推理。

离线矩阵中 8 个非常精简的工具定义，full 首次请求估算为 13,712–13,724 Token，deferred 为 13,820–13,832。此 fixture 上 search_tools schema 与目录的额外开销超过省下的定义；先前大 schema fixture 的结果不同。`mode=deferred` 是显式曝光策略，不代表在所有白名单上节省 Token；不能用初始曝光估算宣称 API 缓存或总交付成本收益，后续仍需计入激活轮次和延迟。

故障矩阵的 warm 表示 journal 完成状态的重放；复杂约束和补研是输入标签，没有运行真实约束质量评估。PostgreSQL 图实验使用 `TravelAgentState`、typed packets 和替代合并节点，验证执行/合并边界，未运行生产 Candidate Gate 或最终交付。成功交付数量、成功交付成本和质量收益均保持 null。

## 历史架构批 A–E 复现记录

以下是已完成历史验证的原命令，不再使用其宿主机 test-venv。后续所有 Python 工作只使用 Docker `/opt/journeypilot`，当前复现方式见 F5。历史独立 PostgreSQL 14 实验使用 Unix socket 临时集群，固定参考没有重新下载，已完成矩阵和付费 probes 无需重跑。

```bash
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python -m pytest tests -q -p no:langsmith
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/verify_usage_postgres.py
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/verify_harness_postgres.py
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/harness_recovery_experiment.py
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/harness_experiments.py matrix --output temp/harness-experiments/matrix.jsonl
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/harness_experiments.py analyze --input temp/harness-experiments/matrix.jsonl
```

前端在 `frontend/` 运行 `npm run check`。后端 lint 使用同 venv 的 `ruff check src tests scripts/harness_experiments.py scripts/harness_recovery_experiment.py scripts/verify_harness_postgres.py scripts/verify_usage_postgres.py`；改动检查用 `git diff --check`。

以下两种模式会调用付费模型，读取本地配置的精确模型名与价格，只做协议校准，不写业务数据库。live 模式遇到合同失败或缺失 usage 返回非零退出码；已保存结果用于诊断。

```bash
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/harness_experiments.py live --output temp/harness-experiments/live.jsonl
PYTHONPATH=src:. temp/harness-review-2026-10-05/test-venv/bin/python scripts/harness_experiments.py live-tools --output temp/harness-experiments/tools.jsonl
```

`analyze` 可读取未来端到端试验的 JSONL：每行至少有 `call_id` 与 `trial_id`，可携带真实 Token/cache 桶、usage_complete、cost_usd、run_wall_ms、finish_reason、repair_round、contract_passed 和最终 delivery_succeeded。同 call_id 的相同记录去重，冲突拒绝；未知费用/交付保持未知；成功交付平均成本包含失败 trial 的费用。一次 run 的所有 attempt 使用同一 trial_id。

## 历史架构批 A–E 结束时的部署状态

当时业务数据库尚未迁移；后续 F2 已通过既有入口完成 0009 迁移，F4/F5 已完成真实交付和恢复。usage outbox 默认位于 `data/usage/outbox.sqlite3`，F1/F5 已补齐并验证持久卷；journal 与 TripRun 同生命周期，删除 run 时通过 FK cascade 清理。没有增加累计 Run Token、费用或调用阻断，默认仍为观察模式。

当时应用使用无工具 Chat Completions 的 Sol medium 组合与 Flash low 工具研究。F2 已接入真实 Sol Responses stream 聚合；Sol 工具 adapter 仍未实现，工具研究保持 fast/low，协议 guard 不变。

当时尚待部署环境的完整端到端验证已在 F4/F5 执行；单变量真实缓存/质量/成功交付成本 A/B 仍未执行。独立 stub 数据库、synthetic 工具或短协议请求不能替代正式运行；embeddings 不属于本 LLM ledger。

## 正式部署续验 F1（阶段记录）

后续所有 Python 验证与应用运行使用 Docker 内唯一环境 `/opt/journeypilot`；上文 test-venv 命令仅记录历史验证复现。新材料位于忽略目录 `temp/formal-review-2026-10-08/`，最终脱敏摘要另行归档。WSL 通过 Docker Desktop daemon 的既有 socket 运行项目 Compose，不启动第二个 daemon。

迁移前实际数据库为 PostgreSQL 18.6，JourneyPilot public schema 空。现有 Compose 的 `data/usage` 持久卷缺口已修复。尚未执行应用迁移和完整 provider/SSE/交付验证，不能用历史 477/116 或协议校准替代本轮正式结果。

## 正式部署续验 F2

业务库已通过既有启动入口从空库迁移至 0009，PostgreSQL 18.6 / pgvector / LangGraph checkpoint 校验通过。Docker Desktop 此 WSL distro 未启用 bind mount 集成，验证使用本项目独立 Docker 管理卷装入配置、复用 Qwen 权重和验证材料；没有调整其他项目的 daemon/容器。生产 Compose 补 usage_data 持久卷，唯一 Python 环境为 /opt/journeypilot。

新增 `scripts/verify_formal_run.py --live --request REQUEST.json --output SSE.jsonl` 通过正式 chat-stream API 捕获公共 SSE、run/events/bundle 快照。它明确调用真实模型、写实际业务 run，无 fake worker/gate/finalizer。当前已保存两个真实失败 run；指定 v4.1 入口不可用和 planner ownership 缺陷分开归因。Sol medium 的真实 Responses stream 聚合已成功，Flash alias 的版本身份未确认。账本有真实 reported Token，但现有 model_pricing=[]，费用为 null。更完整交付/恢复结论将在后续批次记录。

## 正式部署续验 F3

`trip_5840a393a0e04c1c` 已验证真实 plan_gate 中断、API 重启后 approve 恢复、真实 Provider 研究与 typed Research Packet 持久化。续跑因同城交通空 scope 失败，保留原始 SSE、快照与只读 checkpoint/ledger 审计于 `temp/formal-review-2026-10-08/`；8 次调用、118,570 输入/15,894 输出/13,659 reasoning Token，usage 完整、pending=0、金额 null。所见缓存读 51,072 Token 只是这个 Run 的供应商报告，不能当作缓存策略 A/B 结论。

已修复初始市内交通 scope 和限定旧同城断点兼容，相关 agent_behavior 回归 **96 passed**。恢复尝试没有新增模型调用：原 Run 的不可重置十分钟 deadline 已耗尽，无 workspace 被 delivery_quality_gate 拒绝（composition_window_exhausted）。保留原状态后，以新 Run 验证修复代码；交付、研究执行期间进程崩溃恢复与账本故障补记仍待正式验证。

## 正式部署续验 F4

真实 `trip_9bcd381f336b41ef` 在 API SIGKILL、租约过期与显式恢复后完成 Delivery Bundle/SSE：`bundle_52723103f64b4a95e6414e58`，completed，恢复段 263.73 秒。12 条崩溃前已提交工具结果的哈希/audit ID 保留；两次在途模型 usage 保持未知。完整 Provider、packet admission、typed gates 与唯一 finalizer 已实际运行，但主题证据有未核实偏差，不等于事实质量全部通过。

额外验证分清范围：`trip_41c25fc35b564c75` 是真实模型+PostgreSQL 停机的账单组件集成，45/72 Token 在 WAL outbox pending=1，恢复补记及两次同 ID 重放后数据库仅 1 行、pending=0；`trip_9b66f2b6d2e74036` 是真实正式 API 在途取消，32.35 秒协作收口、已返回 usage 完整、无 Bundle。没有模型价格表，所有金额保持 null。

本批修复 negative-only 研究调度、provider 之前拒绝的虚假 usage admission、报告/PDF 需求偏差披露。后端与最终镜像正常 Run 已在 F5 收尾；没有重跑固定参考、历史离线矩阵或把工具曝光估算当作真实缓存/成本 A/B。

## 正式部署续验 F5（完成）

| 验证 | 实际结果 | 范围 |
|---|---|---|
| 最终后端 | 585 + 30 = **615 passed / 0 skipped** | 唯一 Docker venv；含真实 PostgreSQL/pgvector；配置来源 suite 隔离 Compose host env |
| 前端 | **23 passed**、类型/生产构建通过 | F2 后未改动，复用最终构建 |
| 正常正式 Run | `trip_2dba16b29d29498f` completed | 真实模型/Provider/Research Packet/admission/typed gates/finalizer/SSE |
| Bundle | `bundle_a57fda02d314da54a24dffbc` | 与 SSE、GET 和 checkpoint 一致，next=[] |
| 模型 Token | 14 次，212,362 输入 / 28,206 输出 / 13,881 reasoning | reported 完整，missing=0、pending=0、capture_complete=true |
| 真实 cache-read | 106,752 Token | 供应商报告；cache-write 未报告，不是策略 A/B |
| PDF | API 200、3 页、54,600 bytes | 抽取文字验证历史建筑“尚未核实”披露 |
| 业务库/备份 | 0009、PG18.6、client18、真实 dump/checksum 通过 | 新 backups_data 卷；未覆盖业务库执行 restore |
| API force-recreate | readiness、同 Bundle、14 条账单、outbox=0、备份再次通过 | 持久卷重建验证，既有入口自动迁移校验 |

正式审批后交付 342.57 秒，含 2 次参观与 1 条真实步行段，无住宿或跨城交通。历史建筑主题证据仍未核实，既有有界修复策略披露后交付；餐饮覆盖还有非阻断 gap。运行完成不能宣称所有质量满足。Sol medium / Responses stream 与 Flash alias low 已实际运行；指定 v4.1 被代理拒绝，alias 版本身份仍未知。价格表为空，金额为 null，没有新增累计 Run 限额。

现有容器按 `uv.lock --frozen --no-default-groups` 构建，验证镜像显式选 `local-embedding dev`。源码、依赖、迁移指纹、卷权限与证据哈希已进入正式验证 JSON。当前 WSL 验证 Compose override 在 `temp/formal-review-2026-10-08/compose.review.yml`；由 `/tmp/jp-compose` 连接现有 Docker Desktop socket。因为该 distro 的 bind mount 集成缺失，配置、Qwen 缓存和输出使用本项目 named volumes，以 docker cp 装入；不创建第二个 daemon，不动其他项目容器。

只读续查（下面 docker 命令在本机可用 `/tmp/jp-docker` 替代；不要重新创建 Run 来重复验证）：

```bash
docker exec -e PYTHONPATH=src:. journeypilot-api /opt/journeypilot/bin/python journeypilot.py doctor --json
docker exec -e PYTHONPATH=src:. journeypilot-api /opt/journeypilot/bin/python journeypilot.py backup --verify /app/backups/backup-20261008T103304Z-formal-review-2026-10-08 --json
docker exec journeypilot-api curl -fsS http://127.0.0.1:8001/api/health/ready
```

`scripts/verify_formal_run.py --live` 是已有正式采集入口，未来新场景可将脚本装入同一容器后使用 `/opt/journeypilot/bin/python` 运行。原始 SSE、请求/source/checkpoint、PDF 和 backup 本体只保留本地忽略材料/卷；Git 仅归档脱敏摘要和 SHA256。仍未验证指定 v4.1、实际金额、其他供应商、复杂跨城/过夜行程、真实业务 dump 完整 restore 演练和缓存/质量/成本 A/B。可选本地语料未提供，中文词法检索使用 simple，readiness 如实报告。
