# JourneyPilot Harness：2026-10-08 正式验证收尾

工作目录：`/home/tang/projects/JourneyPilot`。当前状态以本文件与 [审查报告 F1–F5](harness_review_2026-10-08.md) 为准；历史阶段结论保留在 Git 与 [实验记录](docs/review/harness-experiments-2026-10-08.md)。业务库已迁移，真实交付与恢复已验证，不再沿用旧“尚未部署”的结论。

## 分支、授权与固定参考

- 本轮起点 local/remote main 为 `aa5a2da6d16589c27534bbf31fb566098b310ff8`。全部修改、分组 commit/push 只在 main，用户已授权付费测试和适时提交/推送。
- study 本地与远端固定 `5e08d829a04048c6f6dba86b191813e22825c106`，后续不修改。已有改动保留，没有 reset/clean 或重写历史 Bundle/ledger。
- 不开启子 agent。`config.yaml`、`config.md` 和真实运行原文不输出、不提交。当前为 workspace-write/自动审批；连接 Docker Desktop 或远端 Git 时按实际沙箱需要申请 escalation，旧 unrestricted/approval never 说明已失效。
- 复用固定参考和历史验证材料，没有重新下载仓库或重跑已完成矩阵/probes。

| 参考 | 固定 SHA |
|---|---|
| openai/codex | `823ea830c0fd418b09ff02d36cad9a1fff66465b` |
| deepseek-ai/deepseek-harness | `5badb15009ae1756c3afe0ae0cef1faafc290ccc` |

正式批已提交 `26ff0c2`（持久 usage、唯一 Docker 环境、Responses stream、失败 SSE、PG18 client）、`df2703e`（intent owner、同城 transport scope）与 `3a6b779`（排除调度、真实 admission 边界、报告偏差）。收尾提交覆盖备份卷、报告与正式证据。用 `git log --oneline study..main`、`git status --short` 和 `git ls-remote origin refs/heads/main refs/heads/study` 核对最终本地/远端，不通过修改 study 保存实现。

## 保持的产品与控制合同

保留 LangGraph、typed Research Packet/admission/gates 与唯一 delivery finalizer。Sol 使用 `gpt-6.1-sol`、medium、Responses；现有代理要求 stream=true，业务 ainvoke 聚合完整流，未完成/提前 EOF 拒绝交付且保留已返回 usage。工具研究使用 fast/low，Sol 工具 adapter 未实现，原协议 guard 保留。reasoning 不关闭，档位与 transport 为配置参数。

指定 `deepseek-v4.1-flash` 真实请求被代理 422 拒绝。继续指令后，正式链路测试暂用既有 `deepseek-flash` alias/low；版本身份未知，不能写成 v4.1 验证通过。现有价格表为空，全部正式 Run 金额 null。累计 Run budget 为 observe，各 Token/费用/调用上限 null；单请求输出预留和既有十分钟 Run deadline 保持独立。

## 唯一环境与正式部署

所有项目 Python 运行、验证、维护只用 Docker `/opt/journeypilot`，虚拟环境名 `journeypilot`；不再调用宿主机历史 test-venv。镜像按 uv.lock frozen 安装，默认组不隐式加入；验证镜像显式 `local-embedding dev`。前端生产产物已进入运行镜像。

本项目容器：`journeypilot-api`（8001）、`journeypilot-postgres`（host 55433 / PostgreSQL18.6 + pgvector）、`journeypilot-redis`（16379）。既有入口 `api-entrypoint.sh → config validate → journeypilot migrate → main.py` 已从空业务库迁移至 **0009_worker_journal**。vector/pgcrypto、受管 schema fingerprint 与 LangGraph checkpoint 合同均通过。fingerprint 为 `a3475a5d68d47f275d4012a9a86b512cdf45c5cac69eb611d72dd40a08053891`。

当前 WSL distro 默认 Docker socket 不通，使用 `/tmp/jp-docker` 通过 WSL root 客户端连接已有 Docker Desktop socket：`/mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock`。`/tmp/jp-compose` 使用主 Compose 与忽略的 `temp/formal-review-2026-10-08/compose.review.yml`。没有更改全局 daemon 或其他项目容器。

该 distro 尚未启用 Desktop bind mount 集成，直接绑定项目目录会为空；当前验证改用本项目 named volumes，docker cp 装入既有配置/权重。override 配置在 `/app/deployment/config.yaml`（UID10001、0600），复用 Qwen 缓存且 HF offline。不要输出配置，也不要在此环境直接撤掉 override 导致配置挂载失效。

- `journeypilot_usage_data → /app/data/usage`：SQLite WAL、FULL、文件0600、UID10001；确认落库后精确 ack。所有正式收尾检查 pending=0。
- `journeypilot_backups_data → /app/backups`：正式 CLI 备份与重建持久性已通过。
- PostgreSQL、Redis、HF 缓存以及验证配置/输出/上传各用原本项目卷。不要用 `down -v` 或重命名卷清理环境。

## 最新实际结果

最终镜像源码与本批工作区 SHA256 一致。全后端 **585 passed / 0 skipped**；配置来源 suite 为避免 Compose DB env 干扰单独执行 **30 passed**，合计 **615 passed**。前端 **23 passed**、TypeScript 与生产构建通过。Ruff/diff check 通过。旧 477/116、独立 PG14、24×离线/故障矩阵和 6 次付费协议请求仍是历史范围，不替代下面正式结果。

| 正式 Run | 结果与范围 |
|---|---|
| `trip_73e7ee37f5d94d2e` | 精确 v4.1 422，failed；3 错误尝试入账，用量未知，pending=0 |
| `trip_49e3ad1a066e4eb3` | ownership 缺陷失败；1 次真实调用，失败 SSE 已收到结算；缺陷已修复 |
| `trip_5840a393a0e04c1c` | plan gate 中断→API 重启→approve 恢复、真实 typed packet 持久化；旧交通 scope 已修复，之后原 deadline 到期拒绝交付，无新增调用 |
| `trip_9bcd381f336b41ef` | 研究中 API SIGKILL→sweeper interrupted→显式 resume→completed，Bundle `bundle_52723103f64b4a95e6414e58`；12 条已提交工具结果/hash/audit ID 保留，2 在途用量未知；旧代码还有1条前置拒绝的 phantom usage，不改写历史 |
| `trip_41c25fc35b564c75` | 真实模型+DB停机的账单组件集成，45/72 Token，outbox pending1→恢复补记0；同 ID 两次重放仍1行；已结束，不列为行程端到端 |
| `trip_9b66f2b6d2e74036` | 正式在途 cancel，32.35秒协作收口，lease released、无Bundle；4271/5351 Token完整，pending0 |
| `trip_2dba16b29d29498f` | 最终正常正式交付，审批后342.57秒，Bundle `bundle_a57fda02d314da54a24dffbc`；14次、212362输入/28206输出/13881reasoning/106752cache-read，reported完整、missing0、pending0 |

两个 completed Run 实际运行真实 provider → Research Packet admission → typed gates → 单一 finalizer → Delivery Bundle → SSE。最终 Run 初始仅 destination → itinerary，后续 typed 定向交通补研；2参观、1真实步行段、无酒店/跨城。checkpoint next=[]，SSE/GET/finalizer Bundle 身份一致。

历史建筑主题仍 unverifiable，按既有有界修复策略披露后交付，未放宽 gate；还有非阻断的餐饮覆盖 gap。公共摘要、报告和真实 PDF 统一显示“尚未核实：以历史建筑为主题安排游览内容”。PDF API 200、3页、54600bytes，文字抽取校验通过；业务 completed 不代表全部事实需求已核实。

真实业务库备份 `/app/backups/backup-20261008T103304Z-formal-review-2026-10-08`：client18、custom dump2133620bytes、checksum/pg_restore list通过。API force-recreate 后经原入口启动，再验同备份、同 Bundle、14条完整账单、outbox0、网页/readiness与PDF均通过。未在业务库覆盖执行 restore。

## 续接材料与未验证范围

[正式机器证据](docs/review/harness-formal-verification-2026-10-08.json) 归档脱敏结果、依赖、固定SHA、schema与证据哈希；[历史机器证据](docs/review/harness-verification-2026-10-08.json) 保留原离线/协议范围。原始材料在忽略目录 `temp/formal-review-2026-10-08/`，包含 SSE、只读审计、测试日志、PDF；备份本体在持久卷，真实请求/source/checkpoint/秘密不提交。

只读续查使用 `/tmp/jp-docker exec -e PYTHONPATH=src:. journeypilot-api /opt/journeypilot/bin/python journeypilot.py doctor --json`；同入口 `backup --verify DIR --json` 校验已有备份。未来新的正式场景用 `scripts/verify_formal_run.py --live` 装入同一容器采集真实 API，不为续接重跑已完成场景。

仍未验证指定 v4.1 的真实版本、实际费用金额、缓存/质量/成功交付成本 A/B、其他供应商、复杂跨城/过夜行程及真实业务 dump 完整 restore 演练。可选本地知识种子缺失、词法检索为 simple，readiness 如实报告；当前空知识库不证明 embedding模型身份迁移兼容。取消现为协作式，等在途回合完成，不保证立即停止上游计费。磁盘写入失败 fallback 明确不完整，跨主机卷迁移不自动完成；这些边界未以运行成功覆盖。
