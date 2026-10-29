# 两种入口评估实质需求缺口，确认与执行使用同一调研计划

- 编号：20261030-0108-requirement-research-plan
- 状态：待真人验收
- 创建：2026-10-30 01:08
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、README.zh-CN.md、frontend/README.md、backend/tests/README.md、frontend/e2e/README.md、docs/architecture/overview.md、docs/invariants.md、[本轮事实/所有权/提交策略](../references/20261030-0108-feedback-workflow.md)

## 1 用户反馈

> 用户核心：补充调研/澄清 Agent 提示词和真实流程失效，用户只给少量信息竟宣称不需要补充，正式调研前应澄清会实质影响方案的信息；不能强制所有完整请求都补问；应尊重用户已给信息/拒绝补充/采用默认，避免无穷补问。必须沿真实调用链确认是 intake/clarifier/plan gate 哪一处，不能仅改提示词掩盖分支；必须向用户展示与本次目的地/日期/偏好和缺口对应的真实调研计划，已有审批配置的行为需有合理、最小一致修复，不能弄一份与执行脱节的静态计划。

关联截图：`output/polish/20261030-0108-feedback-workflow/feedback/feedback-2.png` 为整理需求阶段；截图并不能证明当时后端输入/配置。指挥已 read 看图，本项核心来自上述完整文字反馈与代码/离线探针。没有读取真实会话或调用模型来追索原 Run。

## 2 现象与发生条件

两种新规划入口必须同时覆盖：①条件表单已经构造完整受控旅行身份，但额外要求/预算范围/实际偏好仍可能存在实质歧义；②自然语言进入首页卡内 intake，补齐地点/日期/同行并逐题回答。身份字段齐全不等于方案信息充分，没填可选项也不等于必须问。正式 Run 内的计划门、刷新恢复、一次修改及已有批准行为都在当前工作台内完成。

离线探针 `output/polish/20261030-0108-feedback-workflow/analysis/probe_entry.py` 已证明：完整身份+“规划这趟旅行，总预算12000元”直接 PreparedChat，intake 根本没被调用；并证明 false gate 直接抛 RuntimeError。该探针是现状证据，修复后应由正式回归用例替代旧结果，不能要求继续维持这个缺陷。

## 3 根因

1. **入口绕开缺口评估**：`frontend/src/features/travel/components/planning/TripPlanner.tsx:236–272` 直接发送 identity；`backend/travel_agent/conversation/chat/preparation.py:254–315` 对已有 identity 只合并 saved intake（若存在），仅无 identity 才理解/出题。`conversation/intake.py:26–56、93–109` 的必要问题 prompt 和输出校验因此不覆盖完整表单入口，空 questions 也不代表评估正确。
2. **名字叫 clarifier，但不是补问节点**：`planning/requirements/entry.py:31–58` 只压缩与守卫 controlled_trip_identity；`planning/graph.py:182–189、230–239` 继续归一化/建计划/计划门/分派。没有另一个可靠 Agent 会替 intake 补问，不能只改一份不存在于该分支的澄清 prompt。
3. **缺少已答/拒绝/默认的闭环**：`intake.py:113–132` 可合并答案和补充，但 `:133–155` 强制所有生成题有回答；`GuidedIntakeQuestions.tsx:265–325、564–647` 阻止漏答且仅给选项/自由输入，没有清楚的默认/不补充出口。`approval.py:95–137` 只输出 hard/preferences；现有 `test_control_plane.py:639–735` 对 unresolved/conflicts 仍可批准，未证明实质歧义已经对用户说明。
4. **计划同源但呈现缺失/过泛**：`planning/research/plan.py:74–114` 生成真实 execution_plan/assignments/query plan，`dispatch.py:66–117、149–173` 真正按它执行，worker 消费 assignment query IDs。`approval.py:59–92` 已投影相同 state，`frontend/src/features/travel/model/planApprovalGate.ts:34–62` 已解析 steps/planText，`TripBriefPlanGate.tsx:34–114` 却不渲染计划。`brief_builder.py:173–184` 与 `capability_planning.py:196–207` 的 objective 主要为领域模板+要求，仍需把本次目的地/日期/范围/待验证事项从真实研究结构投影到用户文案。不是另造静态计划的理由。
5. **配置行为不一致**：`config/models.py:233` 默认 true，当前仅非秘密字段检查得 true/source=config.yaml（不证明截图时进程配置）。前端正常不设置 plan_gate；后端 `chat/execution.py:159–160` 可接受请求覆盖，`planning/workflow.py:165–178` 无 checkpointer 会让有效值为 false；`approval.py:150–151` 却直接报错。readiness/startup 对 false 又免 checkpointer 检查。README 把它描述为“是否暂停”，架构文档则要求 controlled planning 必须有门。

## 4 方案

目标状态：用户提供的信息先被真正评估，只问少量确实影响研究/方案的缺口；已给/已答/拒绝/默认有明确去向。进入正式调研前，在当前工作台看到“本次会查什么、为什么、哪些采用默认或待验证”；确认的就是 Run 后续实际执行的计划。

必须做：

- 在服务端建立唯一的实质缺口评估责任边界，覆盖自然入口和带完整身份的条件入口，不能用“identity 存在/表单非空”代替评估。保留原文、已确认地点/顺序、日期、同行、偏好及回答。模型 prompt 可澄清职责，但必须修正实际调用/分支；不在前端硬写“至少问三题”。
- 仅对会改变研究范围/可执行方案的信息作澄清。例如已给总预算但覆盖往返/住宿范围未明确且会影响方案，可问清；用户未给预算或未点饮食标签并不自动成必答题。完整、无歧义请求可零题直接到真实计划；不得伪造“信息已经足够”的判断或以模型不可用冒充完成评估。
- 对已给/已回答题不重复问，明确支持“按合理默认安排/不再补充”；这些选择应作为真实输入进入同一 RequestContract 归一化，不被重新理解为“未知，继续问”。收集轮次有明确收口，刷新/重试/重复提交不重新出同题；用户主动引入新实质冲突另行处理，但不能形成无穷追问。必需地点/精确日期/合法同行身份不能凭默认虚构。
- 继续用首页原卡内收集与现有工作台计划门，不新增独立澄清整页或新的 gate。优先用现有 questions/answers/补充文本表达用户默认选择，若现有合同无法表达安全语义先报告。
- 呈现与实际执行同源的研究计划，覆盖本次目的地/站序、日期窗口、已知偏好/硬约束、领域目标/查询范围，以及真实未定事项/假设/需查证项。依据 RequestContract→Brief→QueryPlan/Assignments 投影，不能只在前端写“查询交通/酒店/景点”三条静态通用文案；也不暴露内部 query ID、工具名或 Provider 原文。没有缺口就不虚构缺口。
- 计划门消费已有 plan.steps / tasks / planText（选择一种不重复显示即可），和要求摘要形成清楚层级；补充改变研究要求后重新归一化/生成计划/审批，dispatcher 使用对应 revision/generation 的同一计划。研究排除项不得仍展示为将执行的工作；重放/刷新得到相同计划，不用旧 Run 覆盖新 Run。
- 多日行程的默认住宿调研不能覆盖明确排除：只依据结构化 Intent（target=lodging、kind=must_exclude、影响 research 的类别值）判断领域级排除。“酒店/住宿/宾馆/旅馆/hotel/lodging/accommodation”等类别表示整个住宿领域，应关闭默认住宿领域，不生成或调度住宿查询；带限定词的子类或具体酒店（如“连锁酒店”“某家酒店”）只在候选阶段排除，不能关闭整个住宿领域；同时存在正向住宿要求（如民宿）时保留住宿调研并继续排除指定类别。判断不读取原句文本，planner 仍为纯函数。
- **最小配置修复方向**：保留默认 true 和当前架构的真实审批/授权封存；显式 false、或有效门不可用/无 checkpointer 的深规划，在昂贵准备/创建 Run 之前得到明确可操作拒绝，不到 plan_gate 才 RuntimeError。对服务端配置和请求覆盖一致处理，快答不被误拦。同步中英文 README/必要配置说明，准确说明禁用时深规划不可用。不得悄悄把 false 当 true，也不自动批准/绕门；若认为应正式支持“false 无审批仍调研”，先停下报告授权/预算封存方案。
- 保留 approve/edit/supplement/cancel、修订上限、取消/恢复/去重与归属检查。不能把澄清轮次和一次计划修订混成同一个计数，或用所有 unresolved/conflicts 一刀切增加强制审批。

执行者自己决定：统一评估放在现有 intake/preparation 的哪一责任边界、如何复用上下文与保存去重、默认选择的交互文案、计划投影粒度。planner/brief/query/capability 仍为纯函数，不为展示计划新增模型调用或第二套真值。

不许碰：真实用户数据、外部/付费 Provider、身份/五站/14天和旅行预算规则、Run 租约/授权预算封存、SSE终态/Bundle合同、新公开事件/持久化schema。INV-INTENT-001/004/005、INV-PLAN-001、INV-BUDGET-001、INV-SSE-001 必须继续成立。仅现有 payload 文案/已有字段的兼容投影和本任务指定拒绝行为属于授权；新增公开字段/新 gate 需先报告。

所有权：backend 第一阶段独占上述后端责任模块/测试及相应 README 增量；交接后 frontend 才拥有 GuidedIntakeQuestions / TripBriefPlanGate、必要 model/types/会话消费增量与相关离线测试/CSS。共享 `index.css` / `session-state.spec.ts` 串行，Generation 左摘要交独立任务。只改本文状态与第7节；不得自行提交/推送，不能整文件 stage 既有 dirty。

## 5 停下来报告的情况

- 澄清闭环需要新持久化字段/新公开事件/新 gate、改变锁定身份或预算授权方式；给出现有合同不足的最小案例，不能前端伪造 ready。
- 若方案会让所有完整请求固定补问，或明确默认/拒绝仍反复问同题，说明评估边界不成立，先修正设计而非加轮次兜底。
- 实际计划与 dispatcher/worker 消费不是本节所述同源，提供具体 revision/query/assignment 流证据后停下，不另造显示计划掩盖。
- config=false 要支持自动授权时必须先报告；本任务选择早拒绝以保留现有审批/预算边界。
- 修改混合文件无法独立提交时按本轮安全策略报告，不提交旧 composer/恢复浮框来补依赖。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 自然与完整身份两入口均经过真实缺口评估；完整身份但有实质歧义会进入澄清，不再因字段齐全跳过。无歧义完整请求零题正常继续；未给可选项不被强问。
2. 已答、明确拒绝/采用默认进入合同和计划，刷新/重复提交不重复问、不重复建 Run；不确定/理解失败不假称已充分。核心身份缺失仍需真实确认，不能从字符串捏造地点。
3. 实际 pending gate 在原位显示本次目的地/日期/偏好对应研究目标及真实假设/缺口；审批 payload 和 dispatcher 的计划/assignment 对应同 revision/generation。补充后两者同步变化，排除项不再执行，planner不新增模型调用。
4. 默认 true 保持真实 interrupt→approve→封存→dispatch；false 和缺 checkpointer 深规划早拒绝可操作，无孤儿Run/晚期RuntimeError，快答仍可用。读取私有配置只输出测试所需非秘密标量。
5. 首页面内澄清、工作台侧栏、失败重试保留输入、终态与归属/恢复不回归；禁止仅 prompt 文本断言/静态截图代替状态与执行验证。

### 6.2 必须运行的检查

仓库根（使用现有 .venv，不下载/同步依赖；所有新增模型/Provider/存储边界使用离线替身）：

```bash
.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/test_workflow_boundaries.py -q
.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/conversation/test_chat_execution.py -q
.venv/bin/ruff check --config backend/pyproject.toml backend/travel_agent/conversation/intake.py backend/travel_agent/conversation/intake_contracts.py backend/travel_agent/conversation/chat/preparation.py backend/travel_agent/planning/requirements/approval.py backend/travel_agent/planning/research/plan.py backend/travel_agent/planning/research/brief_builder.py backend/travel_agent/planning/research/capability_planning.py backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py
```

扩展上述现有行为测试：至少涵盖完整身份稀少且有实质歧义、完整无歧义零题、已答/拒绝/默认/刷新重放、理解失败；以真实准备入口和内存存储验证停止/进入 Run，不仅测 prompt。以同一合同生成真实 planner/gate payload，批准后验证 dispatcher/worker assignment/query 范围；补充改研究/排除项后验证新代计划与旧产物失效。可用 InMemorySaver，替换真正外部模型/工具/存储边界，不层层 mock 内部节点假装同源。覆盖 gate true/false/无 checkpointer 的公开错误与授权边界。上方 ruff 为现有责任文件的定向列表；若新增或触碰拒绝错误映射等其它 Python 文件，将实际路径追加到命令并记录。若改 schema 元数据，同步生成物，另运行 `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/config/test_config_contract.py -q` 及 `PYTHONPATH=backend .venv/bin/python backend/journeypilot.py config docs --check`；不以此授权新字段。

frontend（只用本地 Vite，8088 使用前核对；没有服务时 `npm run dev -- --host 127.0.0.1 --port 8088 --strictPort`）：

```bash
cd frontend
npm run type-check
npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts
JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1 --output=../output/polish/20261030-0108-requirement-research-plan/playwright-intake
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'gate|审批|确认|intake|需求|计划' --workers=1 --output=../output/polish/20261030-0108-requirement-research-plan/playwright-gate
```

用合成 SSE/API 覆盖两入口、有题/零题/默认拒绝、pending gate 计划、补充后新计划、approve/cancel/失败保留/刷新/跨Run，断言实际请求及计划文本，不只最终存在一个标题。所有 API/外网未匹配要拒绝；不能跑 live/write 或真实后端调研。

### 6.3 实屏证据（执行者提供）

`output/polish/20261030-0108-requirement-research-plan/`：2000×880 有实质缺口的原卡内问题、明确默认后同工作台真实计划、补充修改后的新计划；390×844 问题/默认出口及 pending gate 可滚动可操作。附两个不同目的地/日期/偏好的计划差异与离线后端计划→执行一致证据（合成数据、无内部/敏感载荷）。截图来源标注离线，不能说成实际外部调研成功。指挥 read 逐张看。

### 6.4 真人验收（用户操作）

1. 条件规划仅给基本身份和“总预算12000元”等会改变范围的歧义 → 调研前询问必要问题；填全且无歧义的另一请求不应硬补问。
2. 回答，或明确选择默认/不再补充，再刷新 → 不重复问同题；已有信息保留，核心身份仍需确认。
3. 查看工作台研究计划，补充“不要查酒店”等要求 → 计划对应本次目的地/日期/偏好与默认范围，新计划和后续研究一致；确认开始/取消仍是真实动作，不跳新页面。默认只在离线演示中操作，本轮不以真人步骤授权调用真实模型。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 01:31 · backend 阶段

- 改动摘要：把实质缺口评估收敛到 `understand_trip_intake` 唯一入口，条件表单携带完整身份时也会进入评估；已知身份、原文和已答内容一起送入，评估失败不再放行到 Run。问题统一追加普通选项“按合理默认安排，不再补充”，已答问题和身份字段不再重复出现；默认回答进入同一份需求文本。计划门 `plan_text` 从真实合同/身份/执行计划投影本次目的地、站序、日期、偏好、合同内未决项与默认说明，不新增 payload 字段或模型调用。显式关闭计划门、或新建深调研但无 checkpointer 时，在准备/建 Run 前返回明确错误；快答不受影响。
- 改动文件：`backend/travel_agent/conversation/intake.py`、`backend/travel_agent/conversation/intake_contracts.py`、`backend/travel_agent/conversation/chat/preparation.py`、`backend/travel_agent/conversation/chat/errors.py`、`backend/travel_agent/api/chat_errors.py`、`backend/travel_agent/planning/requirements/approval.py`、`backend/tests/api/test_trip_intake.py`、`backend/tests/planning/requirements/test_control_plane.py`、`README.md`、`README.zh-CN.md`、`backend/config.example.yaml`、本任务第 7 节。
- 偏离方案及理由：新增了两个内部拒绝原因 `intake_unavailable`、`plan_gate_disabled` 及对应 HTTP 错误映射；这是让“评估失败/配置不支持”不再走到晚期 RuntimeError 的最小边界改动，未改 SSE 终态、持久化 schema、公开请求字段或审批/预算封存。`plan_text` 只使用现有字段，未新增公开计划字段。
- 实际运行的检查与结果：
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py backend/tests/api/test_chat_use_cases.py -q` → 153 passed。
  - `.venv/bin/ruff check --config backend/pyproject.toml backend/travel_agent/conversation/intake.py backend/travel_agent/conversation/intake_contracts.py backend/travel_agent/conversation/chat/preparation.py backend/travel_agent/conversation/chat/errors.py backend/travel_agent/api/chat_errors.py backend/travel_agent/planning/requirements/approval.py backend/travel_agent/planning/research/plan.py backend/travel_agent/planning/research/brief_builder.py backend/travel_agent/planning/research/capability_planning.py backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py` → All checks passed。
  - 新增离线回归覆盖：完整身份但有预算范围歧义先停在原卡内问题；完整无歧义零题直接建 Run；刷新待答问题不重新评估；已答/默认选项不重复问；身份评估失败明确拒绝且 0 Run；计划门文本与真实 `execution_plan`/assignment objective 同源，含双城站序/日期/偏好/未决项且不泄露 query ID 或工具名；false gate 与缺 checkpointer 在建 Run 前拒绝。
- 实屏证据：本阶段未采集；frontend 阶段实现后按 6.3 统一提供。本轮后端检查未调用外部模型/Provider，未写入真实用户数据。
- 遗留问题或需要指挥决定的事：frontend 需消费以下既有字段与语义：`guided_intake.questions[].options` 末尾新增普通选项 `id=sensible_default`、`label=按合理默认安排，不再补充`；条件入口有实质缺口时返回 `guided_intake` SSE，其中 `controlled_identity` 已填、`questions` 非空、`ready_to_create=false`，应在原卡内回答后带 `guided_intake` 快照和 `controlled_trip_identity` 继续；无缺口时不返回该事件。新增错误 `503 {"code":"intake_unavailable",...}`（保留表单，可重试）与 `409 {"code":"plan_gate_disabled",...}`（配置不支持深调研，不应当瞬态重试）。计划门 payload 字段不变，`plan_text` 现含 `**本次旅行**`、`**执行计划**`、按需的 `**待核实或需要取舍**` 和 `**默认安排**`，只需渲染一次，不要与 steps 重复铺开。frontend 完成前整项不能标为待代码验收。

### 第 3 轮 · 2026-10-30 02:35 · 返工（backend）

- 改动摘要：修复独立审查发现的三处后端问题。之前评估为 `unavailable` 的草稿，即使客户端补齐身份并携带 `guided_intake` 提交，也会重新走真实缺口评估；再次不可用时以 `intake_unavailable` 拒绝，不创建 Run。身份问题识别不再因为问题正文出现“出发地/目的地”等词就删除，改为问题 id 加明确询问身份字段的句式；“总预算是否包含出发地至目的地的往返交通？”等真实缺口保留。显式关闭计划门、或新建深调研但缺 checkpointer 的拒绝移到 intake 模型调用之前，避免无效模型调用和无意义补问。
- 改动文件：`backend/travel_agent/conversation/chat/preparation.py`、`backend/travel_agent/conversation/intake.py`、`backend/tests/api/test_trip_intake.py`、`backend/tests/api/test_chat_use_cases.py`、本任务第 7 节。
- 偏离方案及理由：无。`test_chat_use_cases.py` 的短路径用例补上受支持的 checkpointer 环境，仍断言澄清/确认在租约和 Run 之前短路，没有放宽原有断言。
- 实际运行的检查与结果：
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py -q` → 19 passed；新增“评估失败后带身份重评估”“再次不可用阻止 Run”“含地名但属于预算范围的问题保留”“真实身份问题仍删除”“自然入口 false gate 不调用评估”等回归。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py backend/tests/api/test_chat_use_cases.py -q` → 157 passed。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q` → 759 passed。
  - `.venv/bin/ruff check --config backend/pyproject.toml backend/travel_agent/conversation/intake.py backend/travel_agent/conversation/chat/preparation.py backend/tests/api/test_trip_intake.py backend/tests/api/test_chat_use_cases.py` → All checks passed。
- 实屏证据：本阶段为后端行为与离线回归，无新增实屏；沿用第 2 轮 `output/polish/20261030-0108-requirement-research-plan/` 的离线原卡问题与计划门截图。
- 遗留问题或需要指挥决定的事：无。

### 第 4 轮 · 2026-10-30 02:45 · 返工（backend）

- 改动摘要：修复独立审查发现的 P2 输入遗漏。`understand_trip_intake` 的评估 payload 新增 `additional_requirements`，把用户在确认前补充的预算、同行、交通方式等实质要求与原文、受控身份、已答内容一起送入同一次缺口评估；系统提示同步要求评估这些补充，避免对其中已明确的信息重复提问。未改变最终需求合并逻辑，补充内容仍只通过现有 `merge_intake_answers` 进入 Run。
- 改动文件：`backend/travel_agent/conversation/intake.py`、`backend/tests/api/test_trip_intake.py`、本任务第 7 节。
- 偏离方案及理由：无。只使用现有 `additional_requirements` 字段，未新增公开 payload、持久化字段或模型调用。
- 实际运行的检查与结果：
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py output/polish/20261030-0108-feedback-workflow/recheck/test_review_inputs.py -q` → 23 passed；两处原审查探针均通过，评估输入包含“总预算12000元”，最终需求也包含该补充。
  - 新增回归：实际 `prepare` 入口在初次评估 unavailable 后提交原卡补充并确认，断言真实评估 payload 带补充、最终需求带补充且只创建 1 个内存 Run；无逐题回答时也断言补充仍进入评估输入。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py backend/tests/api/test_chat_use_cases.py -q` → 160 passed。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q` → 761 passed。
  - `.venv/bin/ruff check --config backend/pyproject.toml backend/travel_agent/conversation/intake.py backend/tests/api/test_trip_intake.py` → All checks passed；`git diff --check` → 通过。
- 实屏证据：本轮仅修复后端评估输入，页面行为与既有离线实屏一致，沿用 `output/polish/20261030-0108-requirement-research-plan/` 下第 2 轮的原卡问题与计划门截图，不新增实屏。
- 遗留问题或需要指挥决定的事：独立审查列出的恢复浮层手机几何不稳定、默认/拒绝→normalizer→计划审批→dispatcher 同代执行一体化离线验证、1440px 五站长名称侧栏实屏及独立候选提交树仍未在本轮处理；本轮未调用真实模型、外部 Provider、真实数据库或 live-planning。未修改、暂存或提交任何既有无关改动。

### 第 5 轮 · 2026-10-30 · 返工（backend）

- 改动摘要：修复多日行程默认住宿领域覆盖明确排除的问题。`build_research_brief` 现在只在没有领域级住宿排除时添加默认 LODGING；判断只看结构化 `IntentItem`（target=lodging、kind=must_exclude、影响 research 的 `CategoryIntentValue`）。领域级类别（酒店/住宿/宾馆/旅馆/hotel/lodging/accommodation）关闭默认住宿调研；窄类或具体酒店（如连锁酒店、某家酒店）保留住宿调研，仅进入候选排除；同时有正向住宿要求（如民宿）时保留调研并继续排除指定类别。没有改 schema、公开计划字段、审批/预算封存或 dispatcher 合同，planner 仍为纯函数。
- 改动文件：`backend/travel_agent/planning/research/brief_builder.py`、`backend/tests/planning/requirements/test_control_plane.py`、新增 `backend/tests/planning/research/test_lodging_exclusion_flow.py`、本任务第 4/6.2/7 节。旧恢复浮框、终态 composer、InputArea、followupComposer、地图动画测试修复和旧任务文档未改动，也未暂存或提交。
- 偏离方案及理由：把责任边界放在 brief 的默认领域投影，而不是只隐藏计划或过滤住宿 worker 末端，因为合同已表达排除，根因是无条件默认 LODGING；query plan、capability plan、dispatcher 和 discovery 都由该 brief 纯函数派生。没有新增 scope 字段：用领域级类别与带限定词/具体类别区分宽窄排除，避免把“连锁酒店/某家酒店”误当成关闭整个住宿领域。
- 实际运行的检查与结果：
  - 原独立探针 `PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/final-review/probe_plan_exclusion.py` → 通过；revision=1、补充后新 generation、approve 同 generation、预算/Deadline/Draft 封存；计划只有交通/目的地/行程步骤，`不要查酒店` 在公开计划中可见；dispatched 不含 `accommodation_researcher`，住宿 discovery 的 Provider 工具调用为 0。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/test_workflow_boundaries.py backend/tests/conversation/test_chat_execution.py -q` → 86 passed。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning -q` → 182 passed。
  - `.venv/bin/ruff check --config backend/pyproject.toml backend/travel_agent/planning/research/brief_builder.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/travel_agent/conversation/intake.py backend/travel_agent/conversation/chat/preparation.py backend/travel_agent/planning/requirements/approval.py backend/travel_agent/planning/research/plan.py backend/travel_agent/planning/research/capability_planning.py` → All checks passed；`git diff --check` → 通过。
  - 新增回归覆盖：无排除多日保留默认住宿调研和 structural query；领域级排除影响 research 时不生成住宿 objective/query、不分配 accommodation、公开计划不展示住宿步骤且如实保留排除；仅影响 composition 的排除不关闭研究；窄类/具体酒店保留住宿调研并只带排除类别；正向民宿要求与“不要酒店”并存时保留住宿调研和排除范围。新增离线集成用例从真实准备/默认回答经过真实 normalizer→brief→最低交付 Draft→planner→计划门补充→新 generation→approve 同代封存→dispatcher→住宿 discovery，外部模型、记忆和工具边界使用替身，内部节点不替换。
- 实屏证据：本轮为后台语义与离线集成回归，无新增实屏；前端呈现沿用 `output/polish/20261030-0108-requirement-research-plan/` 既有离线证据。未调用真实模型、外部 Provider 或真实用户数据。
- 遗留问题或需要指挥决定的事：既有未验证项（排除既有 dirty 后的独立候选提交树、完整生产图/真实 Provider 端到端）仍不在本轮声称通过；本轮未 stage/commit。

### 第 6 轮 · 2026-10-30 · 返工（backend）

- 改动摘要：修复非研究的住宿展示/组合要求重新覆盖明确研究排除的问题。`_default_lodging_research_allowed` 现在只把 `target=lodging`、非 `must_exclude` 且 `impact_stages` 含 `research` 的 Intent 视为正向剩余住宿研究；仅 `projection` 或 `composition` 的已订住宿地址展示要求不再撤销领域级酒店排除。没有扩展排除范围：无排除时仍保留多日默认住宿调研，正向民宿要求仍保留研究，窄类别/具体酒店排除仍只作用于候选。
- 根因与责任边界：`backend/travel_agent/planning/research/brief_builder.py` 的默认 LODGING 分支只判断“存在非排除 lodging Intent”，没有消费结构化 `impact_stages`，与同一函数上方只让 research Intent 进入领域的规则不一致。修复仍只消费结构化 `IntentItem`，planner/brief/query/capability 保持纯函数，未改 schema、公开计划字段、审批/预算封存、dispatcher 合同或前端。
- 改动文件：`backend/travel_agent/planning/research/brief_builder.py`、`backend/tests/planning/requirements/test_control_plane.py`、`backend/tests/planning/research/test_lodging_exclusion_flow.py`、本任务状态与本节。旧恢复浮框、终态 composer、InputArea、followupComposer、地图动画测试修复、其它任务文档和 baseline 存档均未修改。
- 偏离方案及理由：无。没有把 `OUTPUT_REQUIREMENT` 一律排除，而是按合同声明的 `impact_stages` 判断；真正声明 `research` 的正向要求仍可保留剩余住宿调研范围。
- 实际运行的检查与结果：
  - 新增控制面回归：projection-only 与 composition+projection 的已订住宿地址要求，与领域级“不要查酒店”并存时均不生成住宿 objective/query/assignment，同时该展示要求仍进入 `delivery_requirements`；无排除时 projection-only 不关闭默认住宿调研。
  - 扩展真实准备→normalizer→brief→Draft→planner→计划门补充→新 generation→approve 同代封存→dispatcher→住宿 discovery 的离线集成回归：参数化覆盖原始“不要查酒店”和“已订住宿地址（projection）+ 不要查酒店”，后者断言 projection Intent 保留、无住宿 query、无 accommodation assignment、discovery 工具执行意图为 0。
  - `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/test_workflow_boundaries.py -q` → **84 passed**；`backend/tests/conversation/test_chat_execution.py` → **6 passed**。
  - 扩大组合：`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning backend/tests/api/test_trip_intake.py backend/tests/api/test_chat_use_cases.py backend/tests/conversation/test_chat_execution.py output/polish/20261030-0108-feedback-workflow/recheck/test_review_inputs.py -q` → **293 passed**。
  - 原酒店排除探针 `PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/final-review/probe_plan_exclusion.py` → 通过；审查方扩展探针 `.../exclusion-review/probe_projection_scope.py` → 通过，`dispatched` 仅含交通研究，`tool_attempts` 为空，同代批准与授权封存成立。原探针及旧日志未改写。
  - 定向 Ruff 覆盖 `brief_builder.py`、三份相关测试及任务 6.2 的 Python 责任文件 → All checks passed；`git diff --check` 通过。离线边界内未调用真实模型、外部 Provider 或真实数据库。
- 实屏证据：本轮为后端计划投影与执行回归，无新增实屏；前端呈现沿用 `output/polish/20261030-0108-requirement-research-plan/` 既有离线证据。
- 隔离与遗留：HEAD 仍为 `d111b8b`，index 为空；baseline `files/` 的 16 个存档 SHA-256 全部与 manifest 匹配。本轮未运行前端单测/type-check/浏览器，前轮记录不冒充本轮结果；未构造隔离既有 dirty 的候选提交树，未 stage/commit/push。完整生产图、真实模型/Provider/数据库端到端及真人验收仍未运行，旧恢复浮层间歇几何差异根因未定位。

## 8 指挥验收（指挥填写）

### 返工后独立复验 · 2026-10-30

- 结论：暂不通过。上轮六项缺陷的对应修复均已核对代码并独立运行回归；另发现本任务仍有一项实质输入遗漏。
- 新返工项：`backend/travel_agent/conversation/intake.py:135–144` 的模型输入只含原文、受控身份及逐题回答，不含 `previous.additional_requirements`。初次理解失败后，用户在原卡“其他补充”填入预算/交通方式再确认时，真实重评估看不到这些要求，随后却以包含这些要求的需求文本创建 Run。应让缺口评估基于本次完整输入，不能遗漏新增实质要求，也不能对已在补充中明确的信息重复询问。独立离线探针：`output/polish/20261030-0108-feedback-workflow/recheck/test_review_inputs.py`，两条预期断言均失败；实际观察到 `PreparedChat`、1 个内存 Run，评估输入没有“总预算12000元”，最终需求却包含它。仅替换模型/内存存储，无外部调用。
- 独立运行：后端本任务相关五文件组合 158 passed；前端相关六文件单测 34 passed、type-check 通过、定向 Ruff 和 `git diff --check` 通过。浏览器：research-progress 21 passed、首页定向 4 passed、planner-intake 7 passed；session-state 定向 16 passed / 1 failed。
- 恢复浮层失败单独复跑两次为 1 failed / 1 passed，均在手机视口切换后的工作区高度断言（差 36px）；尚不能认定本轮回归，也不算稳定通过。证据在 `output/polish/20261030-0108-feedback-workflow/recheck/{session,recovery-repeat}/`。
- 已用 read 查看三张原反馈及首页10张、需求4张、摘要6张、过程21张关键实屏（含返工后长地名/失败生命周期/补充轮次），以及独立测试失败截图。baseline 存档16个哈希一致；恢复浮层、InputArea 和 followupComposer 当前文件相对 baseline 无增量；index 为空。本次未改产品代码、暂存或提交。
- 尚未完成默认/拒绝→真实 normalizer→计划修改/审批→dispatcher 同代执行的一体化离线验证；既有投影测试与合成前端通过不代替此验证。独立候选提交树及1440px五站长名称侧栏实屏也未验证，不计通过。

### 第 4 轮后独立复验 · 2026-10-30

- 结论：仍需返工。上轮 `additional_requirements` 遗漏已修复，原审查两条探针与对应新增回归独立运行通过；未发现上轮六项缺陷再次出现。以下是新确认的范围执行问题，不是把未验证项当作缺陷。
- **新返工项 P2：排除酒店调研没有落实到执行。** `backend/travel_agent/planning/research/brief_builder.py:62–63` 对多日行程无条件建立住宿研究领域；`research/query_planner.py:181–198` 继续生成 lodging structural query；`research/accommodation/discovery.py:92–124` 未根据研究排除语义阻止这些查询。上海出发、杭州→苏州4天，在计划门补充“不要查酒店”后，合同/assignment 已有 `must_exclude` / `excluded_categories=['酒店']`，新计划仍同时写“查找覆盖整个行程的住宿选择；不要查酒店”。批准后实际 dispatcher 分派住宿研究，真实住宿 discovery 尝试执行 `maps_text_search`，参数为 `杭州 lodging properties`、`苏州 lodging properties`。期望用户明确排除的酒店调研不再进入查询和工具执行，公开计划准确表达剩余研究范围；如仍需确认住宿处理方式，应明确解释/确认，不以多日默认覆盖用户排除要求。
- 可复现证据：`PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/final-review/probe_plan_exclusion.py`；日志 `final-review/probe-plan-exclusion.log`。探针从真实 prepare 的问题→默认回答开始，运行真实 normalizer→brief→最低交付Draft→planner→interrupt修改→重新归一化/生成计划→approve→dispatcher→住宿discovery；仅模型、记忆存储和工具执行边界使用离线替身。确认 revision=1、重新生成 generation、批准后 generation 不变、预算/Deadline/Draft 已封存；最终“不应调用排除的查询”断言失败，截获2次工具执行意图，外部 Provider 调用为0。该探针使用裁剪的真实节点图，不声称完整生产图/全部Worker端到端通过。
- 独立运行通过：后端五文件组合加原审查探针 **162 passed**；前端六文件单测 **34 passed**、type-check、定向Ruff、`git diff --check`。浏览器 research-progress **21 passed**、首页几何/键鼠触摸排序/14天定向 **5 passed**、planner-intake **7 passed**、session-state 审批/恢复/历史/只读/composer定向 **19 passed**；先前不稳定的恢复浮层用例再独立重复 **2 passed**（加本轮组合中1次通过，不能由此断言其旧间歇原因已修复）。没有 skipped 计入通过。
- 实屏：已用 read 逐张查看三张原反馈、首页10张、需求4张、摘要6张、过程21张关键证据，并补采/查看 `final-review/summary-1440-five-long.png`（1440×900五站长名，横溢0、不压天数）；也查看了上轮恢复浮层失败截图。阶段完成折叠/主动展开/无关事件保持/终态收起/跨Run与补充轮次隔离、失败过滤与正常安全详情、整体Run失败动作均通过实际浏览器抽查。
- 边界：baseline存档16个SHA-256全部匹配；对照当前增量，恢复浮层、InputArea、followupComposer及旧任务文件与baseline一致，Generation旧composer与相关样式保留；index为空。仅更新本节和忽略目录审查证据，未修改产品代码、暂存或提交。
- 未验证：排除既有dirty后的独立候选提交树；完整生产图（含地理/天气/全部Worker）端到端和真实数据库/Provider调研。恢复浮层旧间歇几何差异的根因尚未定位。本轮遵守离线边界，不把这些项目记为通过。

### 第 5 轮后独立复验 · 2026-10-30

- 结论：仍需返工，仅剩下述 P2 阻断项。原“不要查酒店”单独排除的根因已在 brief 默认领域责任方修复，不是只隐藏公开计划；原探针本轮重新运行通过，批准前后 generation 一致、Draft/预算/Deadline 封存、dispatcher 不含住宿研究，住宿工具执行意图为 0。
- **返工项 P2：非研究的住宿展示要求会重新覆盖明确研究排除。** `backend/travel_agent/planning/research/brief_builder.py:171–176` 将任意 `target=lodging` 且不是 `must_exclude` 的 Intent 都当作保留住宿调研的正向要求，没有区分 `impact_stages` 或是否要求研究。有效合同中同时有 `output_requirement / target=lodging / impact_stages=['projection']`（把用户提供的已订住宿地址列入报告）和 `must_exclude / categories=['酒店'] / impact_stages=['research','composition']` 时，前者并不请求寻找新住宿，却使默认 LODGING 再次启用。真实计划同时承诺“住宿查询”和“不要查酒店”；approve 后 dispatcher 分派 `accommodation_researcher`，真实 discovery 尝试 `maps_text_search` 的 `杭州 lodging properties`、`苏州 lodging properties` 两次查询。应只让真正请求剩余住宿研究范围的正向合同保留研究，非研究的展示/组合要求不能撤销研究排除；同时继续保留“查民宿”等正向剩余范围、窄类别/具体酒店排除与无排除默认行为。不应移到前端隐藏或 worker 原文过滤。
- 独立证据：`PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/exclusion-review/probe_projection_scope.py` → 预期“不应执行住宿检索”断言失败；日志 `exclusion-review/probe-projection-scope.log`。在原探针上仅扩展输入及外部模型替身，输出合法的 projection-only Intent；内部真实 prepare→normalizer→brief→Draft→planner→plan_gate 修改/批准→dispatcher→discovery 不替换。revision=1、新 generation、同代批准与授权封存均成立；截获 2 次工具执行意图，实际外部 Provider 调用为 0。原探针及其旧日志未改写。
- **本轮重新运行**：`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning backend/tests/api/test_trip_intake.py backend/tests/api/test_chat_use_cases.py backend/tests/conversation/test_chat_execution.py output/polish/20261030-0108-feedback-workflow/recheck/test_review_inputs.py -q` → **289 passed**；其中包含新住宿集成回归。另将默认、多阶段排除、连锁/具体酒店窄排除、正向民宿范围的 6 个用例单独 `-vv` 运行 → **6 passed / 42 deselected**。原酒店排除探针通过。任务 6.2 的 Python 责任文件及 API/聊天错误映射、`test_chat_use_cases.py` 定向 Ruff → All checks passed；`git diff --check` 通过。已有绿测未覆盖上述正向覆盖分支的非研究情况。
- 其余任务覆盖抽查：全文读取四项任务及全局分析；核对首页紧凑表单/可访问名称、真实站序与摘要去重、原始生命周期与公开行动过滤、计划单份渲染的代码。read 查看三张原反馈，以及既有首页1440/390、1440五站长名侧栏、完成阶段折叠和计划门截图。本轮仅后端修复，**没有重新运行前端单测/type-check或浏览器**；此前162/34/21/5/7/19项和全套关键实屏的独立结论仍是前轮记录，不算本轮新跑。未发现其它新阻断项。
- 隔离：HEAD 仍为 `d111b8b`，index 为空；baseline 存档16个 SHA-256 全部匹配。恢复浮框、InputArea、followupComposer 和旧文档与 baseline 相同；Generation/CSS/session-state 的 baseline→当前差异中旧 composer、恢复样式及旧地图时序修复保留。产品代码只读，仅更新本轮状态/第8节和忽略目录审查证据，未 stage/commit/push。第9节既有 frontend 执行记录不代表真人验收，本轮没有真人验收结果。
- 未验证：隔离既有 dirty 后的独立候选提交树（交下一阶段验证，不据此否定实现）；完整生产图/全部 Worker、真实模型/Provider/数据库端到端；旧恢复浮层间歇几何差异根因。本轮不扩大真实调用范围。

### 第 6 轮后独立复验 · 2026-10-30

- 结论：代码验收通过，待真人验收。第5轮后的 P2 已在默认研究范围责任方修复；本轮未发现新的阻断缺陷，不表示真人已验收或已经提交。
- 根因核对：`brief_builder.py:171–176` 仅让 target=lodging、非 must_exclude 且 impact_stages 包含 research 的正向 Intent 保留研究，与上方显式研究领域投影一致。projection-only、composition+projection 的已订住宿展示要求不能覆盖研究排除，仍保留在 delivery_requirements/行程要求中；无排除的多日默认研究、连锁/具体酒店窄排除、正向民宿剩余范围不受破坏。CategoryIntentValue 只有类别值，没有新增 scope；宽窄判断只消费合同，不读取原句，不改 schema/公开合同/预算封存，planner 保持纯函数。
- 本轮独立重新运行：`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning backend/tests/api/test_trip_intake.py backend/tests/api/test_chat_use_cases.py backend/tests/conversation/test_chat_execution.py output/polish/20261030-0108-feedback-workflow/recheck/test_review_inputs.py -q` → **293 passed**。另在 test_control_plane.py 定向运行默认/研究与非研究排除/连锁与具体酒店/正向民宿/非研究展示的9项用例 → **9 passed / 42 deselected**；任务6.2的Python责任文件及错误映射、test_chat_use_cases.py定向 Ruff → All checks passed；`git diff --check` 通过。前轮评估失败绕过、预算问题误删、gate晚拒绝、additional_requirements遗漏的对应回归包含在本轮组合中并通过。
- 两个原审查探针均重新运行通过：`PYTHONPATH=backend .venv/bin/python output/polish/20261030-0108-feedback-workflow/final-review/probe_plan_exclusion.py` 和 `.../exclusion-review/probe_projection_scope.py`。真实 prepare→normalizer→brief→Draft→planner→计划门补充→approve→dispatcher→discovery 链路中，revision=1、补充后新 generation、批准同代、Draft/预算/Deadline封存；无住宿 query/assignment，下一研究分派仅 transport_researcher，住宿工具执行意图为0。projection-only Intent保留在真实合同中，公开计划不承诺住宿检索。仅模型、记忆/内存存储和工具执行边界替身，无真实模型/Provider/数据库调用，未改原探针及旧日志。
- 四项覆盖抽查：全文核对四份任务及全局分析，抽查首页紧凑表单/可访问名称/排序、真实站序与摘要去重、原始生命周期与公开行动过滤、计划门单份渲染及相应离线断言；read查看三张原反馈及首页1440、五站长名侧栏1440、目的地完成折叠、计划门实屏。未发现其它阻断项。本轮纯后端返工，未重跑前端单测/type-check/浏览器；前轮162/34/21/5/7/19及关键实屏结果仍明确属于前轮，不冒充本轮重跑。
- 隔离：HEAD仍为d111b8b，index为空；baseline存档16个SHA-256全部匹配，无关恢复浮框、InputArea、followupComposer及旧文档当前内容与baseline一致。另核对Generation/CSS/session-state的baseline→当前差异，旧终态composer、恢复样式、地图动画时序修复保留。产品代码只读，仅更新四份本轮任务的状态/第8节，不stage/commit/push；第9节旧frontend执行记录不代表真人验收。
- 未验证：隔离既有dirty后的候选提交树交下一阶段独立验证，不因此否定本轮实现；完整生产图/全部Worker、真实模型/Provider/数据库端到端及真人验收未运行。旧恢复浮层间歇几何差异根因仍未定位，不扩大本轮真实调用范围。

## 9 真人验收（指挥代录）

### 第 2 轮 · 2026-10-30 02:10 · frontend

- 改动摘要：首页卡内问题继续在原卡显示，后端追加的 `sensible_default` 作为普通选项渲染，并增加“按合理默认安排，不再补充”的说明；选择后与普通回答一起进入同一份 `guided_intake` 快照。计划门新增“本次会这样研究”，优先渲染后端 `plan_text` 一份，不重复铺开 `plan.steps`；无 `plan_text` 的旧恢复数据才回退到步骤任务。计划文本中的本次旅行、执行计划、待核实项和默认说明直接可见，确认/补充/取消仍是原有真实动作。
- 改动文件：`frontend/src/features/travel/components/planning/GuidedIntakeQuestions.tsx`、`TripBriefPlanGate.tsx`、`frontend/src/index.css`、`frontend/src/features/travel/model/planApprovalGate.test.ts`、`frontend/e2e/planner-intake.spec.ts`、本任务第 7 节。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；完整前端单测 `npm run test` → 107 passed。
  - `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts src/features/travel/model/tripIdentityValidation.test.ts` → 8 passed；同轮相关单测合计 34 passed。
  - `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1` → 7 passed，覆盖有题入口、默认出口、刷新保留、五站提交、失败保留和交接。
  - `JP_SESSION_STATE_E2E=1 ... npx playwright test e2e/session-state.spec.ts --workers=1` → 40 passed，审批/补充/取消/恢复未回归。
- 实屏证据：`output/polish/20261030-0108-requirement-research-plan/` 下 `intake-2000-question.png`、`intake-390-question.png`、`gate-2000-plan.png`、`gate-390-plan.png`，均为离线合成数据；问题页可见默认出口，计划页显示与本次目的地/日期/偏好对应的旅行范围、执行计划和待核实项。
- 未运行/已知风险：未调用真实模型或外部 Provider，未验证真实 Run 的完整调研结果；计划文本依赖后端 `plan_text`，前端不再自行拼静态计划。390px 计划门在长文本下需页面滚动，操作按钮仍在原位。
- 后端整合结论：沿用第 1 轮后端 `guided_intake`、`plan_text` 和错误映射，没有新增公开字段、事件、持久化或审批规则；前端只消费现有 payload。`intake_unavailable`/`plan_gate_disabled` 仍走既有错误呈现，本阶段未新增专门页面。
