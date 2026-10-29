# 20261030-0108 本轮事实、执行所有权与提交隔离

## 本轮授权与交接

用户授权完整 Workflow 后续实际实现、代码审查与 git 提交，不推送；**本轮指挥只分析并创建任务/必要分析文档，不改产品代码**。不能把以下任务文档或已运行的基线检查当作修复完成。任务状态均从“待执行”开始。

全程遵守根 `AGENTS.md`、`docs/invariants.md`、`docs/polish/README.md` / `template.md`、项目与测试 README。只用离线模型 stub、内存存储和浏览器内合成 SSE/API；不调用付费模型/外部 Provider，不读出密钥，不写删真实用户数据。截图已通过 read 逐张查看，直接引用，不重复复制：

- `output/polish/20261030-0108-feedback-workflow/feedback/feedback-1.png`：首页条件表单，出发地过宽、拖动把手/提示、关闭按钮掉行、日期/同行/预算布局。
- 同目录 `feedback-2.png`：三城长标题、重复摘要行、右侧“整理旅行需求”标题重复。
- 同目录 `feedback-3.png`：目的地阶段已结束但所有工具平铺、过多横线、内部“未匹配到工具”出现在正文。

## 1 已核实的链路与判断

### 1.1 不是“补充调研 Agent 换个 prompt”就能解决

1. 首页条件表单在 `frontend/src/features/travel/components/planning/TripPlanner.tsx:236–272` 构造完整 `ControlledTripIdentity`，通过 `useSendMessage.ts:64–79` 发到 `/api/chat-stream`；自然语言入口不带 identity。
2. `backend/travel_agent/conversation/chat/preparation.py:254–315` 只有未携带 identity 的新规划才执行 `understand_trip_intake`。携带 identity 且没有 saved intake 的新请求直接向下创建 Run；有 saved intake 的分支只校验/合并已经生成的问题，不重新评估实质缺口。
3. `conversation/intake.py:26–56` 的 prompt 有“最多三道影响选择的问题”，同时禁止仅为缺可选预算/饮食偏好而追问；`:93–109` 接受模型空 questions。仅改此 prompt 覆盖不到条件入口。`:133–155` 强制所有已生成题必须作答，没有专门的“拒绝补充/默认”产品入口；自由回答可以承载明确默认意愿，但当前并无完整策略。
4. 正式图 `planning/graph.py:182–189、230–239` 是 scope → normalizer → brief/地理/天气/summary → planner → plan_gate → dispatcher。`planning/requirements/entry.py:31–58` 的 scope_clarifier 只做压缩与受控身份守卫，无补问模型或澄清中断。不要把名称误认成真实补问 Agent。
5. `planning/requirements/approval.py:95–137、146–255` 只投影 hard/preferences 和审批动作；未展示 unresolved/conflicts 或显式默认选择。`backend/tests/planning/requirements/test_control_plane.py:639–735` 甚至覆盖了“有 unresolved/blocking conflict 仍可批准”，不能宣称现有测试通过已保证澄清充分。也不能反向把所有 unresolved、空预算或默认风格都强制补问。

修复应在服务端统一评估“会实质改变研究/方案的缺口”，覆盖两种入口；明确已答、拒绝、默认的终止语义，保留身份必填与服务端权威。正常完整请求不增加无意义轮次。任务见 `20261030-0108-requirement-research-plan.md`。

### 1.2 真实计划存在；丢在用户可见投影，而不是证明执行图已经脱节

- `planning/research/plan.py:74–114` 由同一 RequestContract/Brief 纯函数生成 query plan、capability plan、execution_plan、agent_assignments。
- `planning/research/capability_planning.py:85–93、129–169` 封装执行顺序、目标与 query IDs；`planning/research/dispatch.py:66–117、149–173` 实际按 state.execution_plan 派发，worker 按 assignment 的 research_query_ids 消费 query plan。
- `planning/requirements/approval.py:59–92` 的计划 payload/plan_text 已从上述 state 派生；不是另一份模型生成的展示方案。
- `frontend/src/features/travel/model/planApprovalGate.ts:34–62` 已接收 steps / planText，但 `TripBriefPlanGate.tsx:34–114` 只展示同行/偏好和已识别要求，不消费计划。无要求时的“可以直接开始规划”也不能证明缺口评估曾运行。
- 现有任务文案本身偏泛化：`planning/research/brief_builder.py:173–184` 和 `capability_planning.py:196–207` 主要是领域模板+偏好，未充分投影本次目的地、日期、范围与待验证事项。需要强化与实际 query/assignment 同源的公开目标，不新建静态几步计划、不让前端自己拼一套执行承诺。

### 1.3 config 与门的实际不一致

- schema `backend/travel_agent/config/models.py:231–234`、示例 `backend/config.example.yaml:107` 默认 true。本轮只用 config loader 输出一个非秘密字段及来源，实际得到 `run_control.plan_gate_enabled=True`，`source=config.yaml`；**没有输出任何模型/连接/凭证字段**。这是当前 shell 的有效配置，不是截图当时进程环境的证明。
- 前端当前正常发送不主动设置 plan_gate；`conversation/chat/execution.py:159–160` 传递可空请求值（仅非空值覆盖默认）；`planning/workflow.py:165–178` 还把 checkpointer 是否存在纳入有效值。
- `approval.py:150–151` 在 false 时直接 RuntimeError；并非“跳过审批”。readiness/startup 在 false 时却不要求 checkpointer（`bootstrap/diagnostics/readiness.py:50–56`、`bootstrap/startup.py:77–83`）。因此配置/请求 false、或无 checkpointer，可能更晚才失败。
- `README.zh-CN.md` 称此字段决定“是否暂停”，而 `docs/architecture/overview.md` 明确 controlled planning 必须启用审批。推荐最小一致修复：保持默认 true 与受控规划真实审批，深规划不支持的 false/缺 checkpointer 在昂贵准备/建 Run 之前以可操作提示拒绝，并同步配置说明；快答不因该设置被误伤。不在本轮自动批准、改授权/预算封存。若要支持 false 自动授权，是另一项业务决定，必须停止报告，不能顺手绕门。

### 1.4 UI 根因

- 首页：`TripPlanner.tsx:466–520`、`DateRangePicker.tsx:170–184`、`DestinationTokenField.tsx:534–612`、`index.css:1256–1298、1492–1544`；拖动只绑在专用 span，删除图标不能连功能一起删，footer 与 token 共用 wrap 流导致按钮掉行。
- 左摘要：`GenerationJourneyPanel.tsx:119–150` 对完整地名拼全角加号、另列重复目的地/行程；`index.css:4016–4044` 只保单个 segment 不换行，不表达清晰站序布局。
- 右过程：`ThinkingChain.tsx:120–169` workspace 强制 showBody，标题不是 disclosure；`:174–189` 的 openToolIds 无 Run 作用域/完成收敛。顶层标题与 planning 子组同名；`index.css:3732–3759、3793–3799` 仍有阶段/逐行边线。
- 内部失败：`tools/react.py:361–400` 对 search_tools 无命中也发 success +“未匹配到工具”；普通失败经 `conversation/chat/tool_events.py:102–178` 保存为 failed thinking step。前端实时消费 `frontend/src/features/chat/model/streamPresentation.ts:56–104` 经 `toolDisplay.ts:13–20` 把 success→completed、blocked/失败→failed；历史 `model/sessionHistory.ts:17–39` 直接映射已保存状态，二者都进入 ThinkingChain。`toolDisplay.ts:354–367、392–400` 刻意保留未匹配文本，`ThinkingChain.tsx:122、129、137–144、166–169` 不排除失败工具，summary/milestone/previews 均需统一可见性责任边界，不能只隐藏某一条 DOM。

## 2 dirty 基线：不是干净 checkout

开始 HEAD：`d111b8b06c0288af160edb204f8658a4fc739431`。基线位于：

`output/polish/20261030-0108-feedback-workflow/baseline/{manifest.json,tracked.patch,files/,status.txt}`

本轮分析时已核对 HEAD、全部 16 个文件 SHA-256 与 manifest 一致，index 无 staged 文件。既有 tracked 10 文件，diff 为 **1238 insertions / 159 deletions**；6 个 untracked 也属于既有基线，不是本轮新文件。

| 基线文件/组 | 关系及必须保留的内容 | 本轮提交判断 |
| --- | --- | --- |
| `frontend/src/features/chat/components/ThinkingChain.tsx`、`model/toolDisplay.ts` / `.test.ts` | 相关：中文别名、三段安全详情、真实计数、工具展开状态；来自 2325 work-activity-feed | 新过程任务必须在它们上增量修复；不能整文件 add 视为本轮 |
| `frontend/e2e/fixtures/research-progress.tsx`、`frontend/e2e/research-progress.spec.ts` | 相关：中文激活、计数、安全输入、长查询等离线检查 | 保留正常成功路径，按本轮完成折叠/失败隐藏的新要求更新冲突断言；旧增量不自动提交 |
| `frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx` | 共享文件：基线新增 followup composer、只读说明，与左摘要/Run key 处相邻但并非本轮目标 | 保留 import/调用与只读边界；不可因本轮改标题把旧 composer 带入提交 |
| `frontend/src/index.css` | 混合：research 样式相关；恢复浮框、generation-followup/滚动结构不是本轮需求 | 选择器级隔离；不提交恢复浮框/续聊旧块 |
| `frontend/e2e/session-state.spec.ts` | 混合：研究恢复相关；恢复浮框、续聊/只读/审批、地图退场等待属于旧任务 | 保留全部，提交只能是本轮独立夹具/断言增量，不整文件暂存 |
| `frontend/src/app/layout/TripWorkspaceShell.tsx` | 无关：恢复提示移出文档流、点击穿透 | 原样保留，不修改/暂存/提交 |
| `frontend/src/features/chat/components/InputArea.tsx`、`frontend/src/features/travel/model/followupComposer.ts` / `.test.ts`（后两者未跟踪） | 无关：自动聚焦参数和续聊状态判定 | 原样保留，不修改/暂存/提交；注意 Generation 的基线 import 依赖未跟踪文件 |
| `docs/polish/references/20261029-ai-work-activity.md`、`docs/polish/tasks/20261029-2325-{floating-recovery-notice,work-activity-feed,workspace-followup-composer}.md`（均未跟踪） | 旧研究/任务及验收记录；不能冒充本轮创建或已获真人通过 | 原样保留，不暂存/提交、不改状态 |

已读相关旧任务：1207 日期边界/首页操作、1252 home-form-rhythm/destination-tokens/inline-intake/generation-layout、1817 compact-tool-activity/unified-planning-workspace，以及 2325 三项。它们待真人验收不等于已合并或干净。新反馈仅取代冲突的可见教学、已完成阶段展开、失败工具呈现、审批不展示计划的旧要求；保留五站、14 天、草稿/顺序、卡内澄清、原位工作台、服务端审批、正常详情、恢复浮框与续聊。

## 3 严格顺序与文件所有权

同一 checkout **任何时刻只有一个写入者**；测试生成证据/构建也算写入，不能与下一位代理并发。只读探索若使用代理，也必须由指挥核实结论；本轮未并发写产品代码。

1. **backend 执行者，任务 requirement-research-plan 后端部分**：拥有 `backend/travel_agent/conversation/intake*.py`、`conversation/chat/preparation.py` / 错误映射、`planning/requirements/approval.py`、相关计划纯投影模块及对应定向测试；仅在必要时触碰 config/checkpointer 的拒绝边界与文档。拥有本任务第 7 节本阶段记录，不修改第 1–6 节。先交接实际行为/事件样例/离线检查，不能把尚未完成的前端标为整项完成。
2. **frontend 执行者，接着顺序完成**：requirement-research-plan 前端 → home-form-compact → planning-summary → process-disclosure。唯一拥有各任务相关前端组件、model/types 的必要增量、`src/index.css` 与 e2e 夹具/测试；特别 `GenerationJourneyPanel.tsx`、`index.css`、`session-state.spec.ts` 在不同任务间顺序移交，不跨代理并发。`TripBriefPlanGate.tsx`、`GuidedIntakeQuestions.tsx` 归需求任务；`TripPlanner.tsx` / `DestinationTokenField.tsx` / `DateRangePicker.tsx` 归首页任务；Generation 摘要块归 summary；ThinkingChain/toolDisplay/researchProgress 归 process。共享 helper 的新增消费者先交接再改，不重复建规则。
3. **代码审查者只读**：按 baseline→当前增量与 HEAD→拟提交树两层检查，重点覆盖两个入口、默认/拒绝终止、计划和 dispatcher 同源、完成折叠、旧失败历史与 Run 隔离。返工回到相应执行者，继续串行。
4. **指挥**：汇总测试/逐张 read 新实屏、写第 8 节；用户验收只能如实记录，无真人结果不能写“已验收”。用户已授权后续提交，不推送；由指挥/指定提交者独占 index，执行者不得自行 git add/commit。

不能满足任务第 1–6 节而需新 gate 类型、持久化 schema 或改变既有授权规则时，先受阻报告，不为了“实际实现”越界。

## 4 安全提交策略（先决定，不能最后 git add .）

- 文档/干净后端、首页独立文件优先按任务白名单提交。记录提交前 HEAD、baseline→当前差异；本轮新文档仅 `20261030-0108-*.md`。不提交 output、真实配置、旧未跟踪文件。
- 对混合文件，用本轮前后内容构造**临时 index 的候选提交树**（从当前 HEAD 起），仅装入本轮增量；工作树不 reset/stash/checkout 回写，基线副本只读。逐个看 `git diff --cached`（若临时 index 则显式指定），检查内容与 imports。主 index 不能被其他执行者占用。`git add -p` 只能帮助选择可分离 hunk，不能证明依赖独立。
- **已知风险**：ThinkingChain 新三段详情依赖 dirty toolDisplay 的 inputs/count；Generation dirty import 依赖未跟踪 followupComposer；session-state 扩展共用旧夹具。单把当前整文件提交一定混入旧工作，单应用 delta 也可能在 HEAD 上没有相应上下文/能力。
- 每项提交必须能在拟提交树本身运行相关离线测试，不只在含 dirty 前置功能的工作树中跑绿。可将候选树导出到忽略的验证目录串行检查，不能另开产品写入代理或改变共享工作树；验证目录不含真实配置/凭证，不连服务。仅前端页面测试可使用该候选树的独立 Vite 与全拦截夹具。
- 若 delta 无法独立应用/运行：**不得自动扩大白名单、提交整块旧功能或伪称已经隔离。** 可先提交确实独立的后端/文档/首页部分；把相关前端改动保留在当前 dirty 工作树，报告“实现完成但提交受阻”。推荐后续单独列出必要相关旧任务/文件/hunk，由用户确认前置范围后另作前置提交，再提交本轮差异；无关的 floating-recovery/followup/地图时序仍不得混入。不能用一次总提交解决依赖。

本轮尚未尝试构造候选产品树，故不能承诺四项都可独立提交；以上依赖风险已提前指出。授权 git 提交不等于授权接纳所有既有 dirty 改动。

## 5 本轮实际检查与证据限度

- 非秘密配置单字段输出：`True` / `config.yaml`，无网络调用。
- `PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/analysis/probe_entry.py`：完整 identity + 稀少要求直接得到 PreparedChat，内存 Run 数 1，intake 未调用；禁用 gate 得到上述 RuntimeError。外部调用 0，持久化写入 0。探针只证明当前缺口，不是后续修复回归。
- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/test_workflow_boundaries.py -k 'intake or entry_checks_identity' -q`：10 passed / 8 deselected。
- `cd frontend && npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts`：26 passed。
- baseline 16 文件哈希全部一致，HEAD 一致，index 起始为空；本轮没有修改/暂存产品代码，也未提交、推送。
- 8088 有现有 Vite 监听；后续使用前检查。当前不启动/重启真实后端、不连接真实 Run 来复现，不运行 JP_LIVE_E2E / JP_WRITE_E2E。本轮未采集修复后的实屏，必须由执行者按各任务 6.3 补齐。
