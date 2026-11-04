# S0 审查准备

[返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)、[采集规范](../capture.md)

## 准备项

- [x] 在总览页顶部填写基线分支、提交号和开始日期。
- [x] 按 `AGENTS.md` 启动本地服务，确认前端、API 文档和就绪检查都可访问。
  - 已按授权删除异常锁文件，并按授权重建 `journeypilot_postgres_data`；新库已迁移到 `0001_baseline`，schema 与基线一致。PostgreSQL、Redis 分别在 `55434`、`16379` 健康运行。
  - 当前前端 `:8080`、API 文档 `:8001/docs` 与 `/api/health/ready` 均返回 200。就绪检查显示数据库、Redis 与 MCP 可用；本地出厂语料未提供，知识库集合为空。
  - `55433` 被 `tsg-launch-audit-postgres` 占用；Compose 支持 `JOURNEYPILOT_DATABASE__PORT` 覆盖（基线 `4aa1d11` 之上有一处未提交改动：`infra/compose.yml` 的宿主机端口改为读取该变量，默认 55433）。启动需保留端口环境变量，因为 `restart` 不会保存它们。
  - 按授权删除了已验证的临时数据库备份目录。启动命令使用 `fnm exec --using=22 -- env JOURNEYPILOT_DATABASE__PORT=55434 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start`。
  - `frontend/.nvmrc` 选择 Node 22，`package.json` 的 `engines` 则允许 `>=20.19`。Node 26/npm 11 的 `npm ci` 因锁文件缺少 4 个间接可选依赖失败；Node 22/npm 10.9.9 下成功。`package.json` 和 lockfile 未改动。
- [x] 在当前数据库中准备截图用会话，覆盖以下情况（缺口已移交：单目的地 1 日的真实完整交付待 B3、T2 修好研究包校验后补采，F4 采集 D1 的 1 天场景先用离线夹具）：
  - 完整交付：单目的地、多目的地、1 天、14 天
  - 部分交付：含“尚未安排”的项目
  - 运行终态：失败、已取消、中断后可继续、中断后不可继续
  - 其他：历史结果只读、纯旅行问答
  - 已按授权用当前配置模型创建并持久化苏州 1 日、成都/乐山/重庆 14 日规划会话，以及一条纯旅行问答；素材清单见 `output/review/S0/sessions/manifest.md`。
  - 新建的 14 日 run 在临时时限下完成 14 日 Bundle；`itinerary.unresolved` 含第 6 天“尚未安排具体活动”，但日程 UI 显示“自由休息”，没有呈现该未安排提示。完整交付截图已采集。
  - 另建成都城内 1 日会话；方案确认后重试了一次研究，仍停在研究门，提示交通查询未完成，目的地与住宿成果已保留；未生成 Bundle。当前界面截图已采集，未继续重试。
  - 苏州 run 因交通查询未完成而取消；另一条 14 日 run 曾中断并成功恢复，之后停在研究门。纯旅行问答已完成。
  - 真实库里每个会话只有一个 run，没有失败、不可恢复中断和历史只读的真实样例。已用请求拦截补齐：失败、中断后可继续、中断后不可继续、历史结果只读，各按 M、D、W 采集，并附整页图；素材清单见 `output/review/S0/states/manifest.md`，脚本为 `output/review/_tools/capture-terminal-states.mjs`。这些终态来自拦截，不是真实运行产生。
  - “部分交付”：14 日 Bundle 的 `itinerary.unresolved` 有 50 条（第 6 天 1 条，另 49 条为“接驳尚未核实”），数据样例已具备。但前端不渲染 `unresolved`，`session-state.spec.ts` 的 `concise delivery keeps unlocated stops…` 还断言页面不列出缺口，因此界面上没有“尚未安排”的视觉样例，需 F4 先确认这是不是有意设计。
  - 仍缺：单目的地 1 日的真实完整交付。苏州、成都城内两次停在交通查询未完成；按授权新建的杭州 1 日会话（session `139a1ac0-66df-5145-9d62-3c354723ca0b`，run `trip_93ae8b4793d0597f813cbf36c4985f35`）在临时时限下也停在研究门，点一次重试后又失败：这次不是时限问题，而是目的地调研的模型产出两次都没通过 `ResearchPacket` 结构校验（先是缺 `candidate_kind`，再是 `weather_sensitivity` 填了 `medium`），整份调研被丢弃，已转 B3、T2。在这个问题修好前，再花钱重跑意义不大；F4 采集 D1 的 1 天场景暂用 `session-state.spec.ts` 的离线夹具。
  - 已注意：已开始的 run 带着自己的 deadline 快照（`seal_minimum_delivery_draft` 重试时沿用 `previous_deadline`），在旧 run 上重试不会用到新时限；要放宽时限只能新建会话。
  - 本地日志显示旧规划 run 的交通/住宿调用在研究窗口关闭后被取消；`config.yaml` 的默认 `run_deadline.closeout_seconds` 为 450 秒，`get-tickets` 另有 provider 成功但结果为空的记录。完成一条样例时按授权只对该次服务运行临时覆盖四段时限为 `900/1200/1500/1650` 秒，未改配置文件；之后已恢复默认时限。杭州会话同样临时覆盖这四段时限，跑完后已重启回默认，并确认后端进程不再带 `RUN_DEADLINE` 环境变量。
- [x] 准备过程态的复现手段：离线页面、事件重放或请求拦截。已有 `frontend/e2e/fixtures/generation-sse.html`、`generation-progress.html` 和配套 E2E 页面。
- [x] 在 `output/review/_tools/` 写好按视口矩阵批量截图、录屏和抽帧的脚本：`capture.mjs`。
- [x] 确认分析模型的输入能力：使用本次 Codex。图片分批和联系表规格已写入[采集规范](../capture.md)；官方说明没有给出准确张数、分辨率上限，也未明确本界面的视频输入能力。
- [x] 按[参考库](../references.md#recentdesign-)挑选 recent.design 的参考素材，截图定格，存到 `output/review/_refs/recent.design/`。已选 Orior AI 与 Shopify Editions Winter ’26，来源和用途记在 `output/review/_refs/manifest.md`。
- [x] 代码验证全过程，都可以进行真实运行的测试。Python 环境和导入检查通过；Node 22 下 `npm ci` 成功，API、前端与浏览器素材工具可运行。2026-11-04 已按 `AGENTS.md` 跑完提交前检查，作为基线：ruff、`config docs --check`、`config validate` 通过；前端 `npm run check` 通过（31 个测试文件、193 个用例，`vite build` 成功）；后端 pytest（不含 `tests/db`）910 通过、1 失败。失败用例 `test_run_execution_contract.py::test_node_scope_shares_budget_attribution_and_lifecycle_with_low_level_calls` 调用 `router.guard_run_budget`，而基线提交已让 router 改用台账预留预算、不再导入它；按用户要求直接修了测试，改为调用 `budget.guard_run_budget`，该文件 18 个用例全部通过。另发现：测试进程里的用量记录写进了真实的 `data/usage/outbox.sqlite3`（假 run `supply-flow` 的 2 条），被在线后端每 2 秒重试并因外键失败；已在 `backend/tests/conftest.py` 让测试会话改用一次性 spool 目录，并清掉那 2 条残留。未跑 `tests/db` 与 Playwright。
