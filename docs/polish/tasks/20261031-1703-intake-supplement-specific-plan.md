# 正式规划前补足信息，并让研究计划针对本次输入

- 编号：20261031-1703-intake-supplement-specific-plan
- 状态：待代码验收
- 创建：2026-10-31 17:03
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`docs/architecture/overview.md`、`backend/tests/README.md`、`frontend/e2e/README.md`、关联任务 [20261030-1416-clarify-before-plan](20261030-1416-clarify-before-plan.md)、[20261030-1012-model-research-plan](20261030-1012-model-research-plan.md)

## 1 用户反馈

用户原话（2026-10-31，附行程工作台截图）：

> 我们为什么前端在正式开始规划之前，还是没有要求信息补足的阶段，为什么没有呢？
>
> 我们的这个规划的内容还是看起来像是占位的，没有为我们用户的输入进行那种特别的计划的感觉。

截图内容：按条件规划填写「深圳市 → 北京市、上海市，2026-11-10 至 2026-11-14，2 位成人，经典均衡」，进入工作台后直接看到「确认旅行需求」门；「本次会这样研究」只有三步通用任务（目的地调研、交通查询/住宿查询、行程规划），没有任何北京市、上海市、日期、同行人或风格的针对性内容；「已识别的旅行要求」为空。

另：截图中的后端进程启动于 2026-10-29 22:50，早于 `c9365f9`（2026-10-30）和 `c74fc10`（2026-10-31）两次规划改动，本任务执行前已手动重启后端。重启只让已有代码生效，不改变本任务要解决的产品缺口。

## 2 现象与发生条件

- 入口：首页「按条件规划」表单，字段已填齐（出发地、两个目的地、日期、同行人、风格；预算在消息摘要中）。
- 提交后不出现任何补充问题，直接创建工作台 Run，并在 `plan_gate` 等待确认。
- 确认门中的研究计划只有 agent 级通用任务，没有本次旅行的城市、日期、同行人、风格或用户补充要求。
- 自然语言入口不在本次反馈范围内，但共用同一 intake；修改时必须保证它不被意外重复追问。

## 3 根因

### 3.1 没有信息补足阶段

- 条件表单提交后，服务端确实会调用 `understand_trip_intake`（`backend/travel_agent/conversation/chat/preparation.py:433-452`），有未答问题就返回 `guided_intake` SSE，不创建 Run；问题为空才继续。
- 但问题完全由模型决定，提示词明确要求：「用户未提预算、餐饮等可选偏好时不要为收集而追问」「没有会改变研究范围或可执行方案的实质缺口，questions 返回空数组；不要为了提问而提问」（`backend/travel_agent/conversation/intake.py:174`、`:179`）。表单已经补齐出发地、目的地、日期、同行人和风格后，模型很容易判定没有缺口，于是 `questions=[]`。
- 服务端没有与模型无关的基线补充问题。条件表单也没有收集必去/排除项、城际交通偏好或住宿偏好。结果就是：用户看到的是「表单填完 → 直接确认计划」，而不是「表单填完 → 补足会改变研究范围的偏好 → 再给计划」。

### 3.2 计划像占位

- 计划正文由 `_serialize_plan_text` 生成（`backend/travel_agent/planning/requirements/approval.py:267-309`），执行步骤的任务正文来自 `_assignment_objective`（`backend/travel_agent/planning/research/capability_planning.py:196-215`），各领域摘要来自 `_domain_summary`（`backend/travel_agent/planning/research/brief_builder.py:270-291`）。
- `_domain_summary` 的基础文案是固定的：「查找符合主题和要求的景点与体验」「查找覆盖整个行程的住宿选择」「查找合适的往返及跨城交通」。只有独立研究计划模型成功产出 `focus_atoms` 时才会追加研究重点；模型计划缺失或未通过范围校验时，`plan_source` 为 `deterministic_fallback`，`_research_scope_rows` 返回空（`approval.py:145-161`），计划只剩这些通用句。
- `_assignment_objective` 对行程规划器只写「结合候选目录与用户要求组合可执行按天行程」，没有城市顺序、日期、同行人或风格。已确认的身份只出现在 `_serialize_plan_text` 的「本次旅行」一行；旧后端连这一行都没有。因此用户看到的正文没有「为这趟旅行专门研究」的感觉。
- 截图中的 `recognized_requirements` 为空，说明当时连风格、预算等也没有进入需求合同；当前代码在正常路径会投影 intent spec，但需要确认端到端仍成立。

## 4 方案

目标状态：条件表单填完后，在创建正式 Run 之前出现一轮可跳过的「再确认一点」补充问题，问题内容与本趟旅行直接相关；回答或选择默认后，确认门中的研究计划明确写出本次旅行的城市顺序、日期、同行人、风格和补充要求，研究任务不再只有通用句。

必须做：

1. **服务端基线补充问题（条件表单入口）**
   - 在 `understand_trip_intake` 返回后、`preparation.py` 判断是否等待回答之前，为「已确认身份 + 首次评估 + 模型没有提出问题」的条件表单会话追加一组固定问题。
   - 只对 `controlled_identity is not None` 的入口追加；自然语言入口维持现有模型驱动逻辑，避免重复追问。
   - 只在 `previous` 为空或 `previous.questions` 与 `previous.answers` 都为空时追加；已回答或已出过题的会话不重复追加。
   - 问题数量控制在 3 道以内，逐题回答，每题都带 `sensible_default`（「按合理默认安排，不再补充」），用户可以全部跳过。
   - 建议题目（执行者可调整文案与选项，但不能退化成通用问卷）：
     1. 这趟旅行最想优先安排什么？多选。选项至少覆盖经典地标、当地美食、博物馆/人文、自然风景；带默认项。题面写清城市名，例如「这次去北京市、上海市，最想优先安排什么？」。
     2. 城际交通更希望怎么安排？单选。选项至少覆盖高铁/动车优先、飞机优先、按时间与价格择优；带默认项。题面写清路线，例如「深圳市 → 北京市 → 上海市 → 深圳市，城际交通更希望怎么安排？」。
     3. 住宿更看重什么？单选，仅多日行程询问。选项至少覆盖靠近地铁/减少换乘、市中心步行方便、安静休息、价格优先；带默认项。
   - 如果用户已经在表单或原文里明确提供了某一项（例如预算覆盖范围、风格中的明确兴趣），不要重复问同一件事。
   - 问题与回答必须走现有 `GuidedIntakeState`、`guided_intake` SSE、`merge_intake_answers` 和 intent 归一化链路；不新增公开 API/SSE 字段，不改数据库 schema。
   - 用户选择默认项时不产生正向研究要求；不能把「按合理默认」当成用户选择了某个具体偏好。

2. **计划正文针对本次输入**
   - 让 `_domain_summary` 接收受控身份，基础文案带城市顺序、日期范围、同行人和风格。例如景点与体验写成「在北京市、上海市（2026-11-10 至 2026-11-14，2 位成人，经典均衡）查找符合该风格的景点与体验」，不再只写「查找符合主题和要求的景点与体验」。
   - 长途交通摘要写出实际链路：「查找深圳市 → 北京市 → 上海市 → 深圳市 的往返及跨城交通」。使用现有的 `build_required_long_distance_legs` 或等价的身份路线推导，不猜测城市间停留天数。
   - 住宿摘要写明天数、城市和同行人；市内交通摘要写明城市。
   - `_assignment_objective` 的 `itinerary_planner` 文案带上城市顺序、日期、同行人和已识别要求，例如「为北京市、上海市 2026-11-10 至 2026-11-14（2 位成人，经典均衡）组合可执行按天路线」。
   - 保持 `_serialize_plan_text` 的「本次旅行」摘要；确认门在身份存在时必须先展示这行，再展示研究范围/执行计划。
   - 如果独立研究计划模型成功，保留其 `focus_atoms` 与检索词；如果失败或未通过校验，确定性摘要仍必须是具体的，不能退回通用句。

3. **确认链路**
   - 补充问题的答案必须出现在后续需求合同或确认门的「已识别的旅行要求」中；如果归一化模型漏抽取，至少不能丢失用户明确选择的研究方向。
   - 不改变计划门的审批 token、版本校验、修订额度、取消/补充行为。
   - 不改变「未获批准不调用天气/Provider」的既有约束。

执行者自己决定：

- 基线问题的具体文案、选项顺序和第 2/3 题的触发条件（例如单目的地是否仍问城际偏好）。
- 基线问题放在 `intake.py` 还是独立模块；优先保持责任单一、可测试。
- 计划摘要的具体措辞和截断方式，但必须保留可核对的城市名、日期、同行人与风格。

不许碰：

- 计划门的授权、版本 token、预算/期限封存、Provider 调用时序和 `docs/invariants.md` 中的约束。
- 公开 API/SSE 契约、数据库 schema、真实用户数据。
- 自然语言入口已有的模型问题策略（除共用代码的必要兼容）。
- 与本任务无关的交通卡片、地图、首页视觉改动。

## 5 停下来报告的情况

- 如果给条件表单追加基线问题会绕开现有 `intake_revision`/`ready_to_create` 校验，或需要新增持久化字段，停止并记录。
- 如果计划摘要无法在不读取未授权 Provider 数据的前提下写出具体城市/日期，停止并说明哪些字段缺失。
- 如果现有测试把「完整表单必须零问题」作为不可变合同，先记录冲突点，不要静默改掉安全相关断言。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 条件表单填齐后、模型未出题时，服务端返回至少一道与本趟旅行相关的补充问题；问题逐题出现，每题都有默认跳过项。
2. 自然语言入口和已经答过题的会话不会重复出现基线问题；模型已出题时不叠加基线问题。
3. 全部选择默认后可以继续创建 Run；答案不会伪造出具体偏好。
4. 确认门计划正文包含城市顺序、日期、同行人和风格；长途交通写出实际链路；即使 `plan_source=deterministic_fallback` 也不是通用占位句。
5. 补充问题的明确选择进入需求合同或确认门的已识别要求；计划门既有 token/修订/取消行为未退化。

### 6.2 必须运行的检查

- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/api/test_multi_round_intake_flow.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_model_research_plan_flow.py -q`
- 如改动 intake 证据或语义确认，追加 `backend/tests/planning/requirements/test_confirmation_contracts.py` 与 `backend/tests/api/test_semantic_confirmation_contract.py`。
- `cd frontend && npm run type-check && npm run test`
- 运行 `frontend/e2e/planner-intake.spec.ts` 与 `frontend/e2e/multi-round-intake.spec.ts`（使用离线模型/网络拦截）。

### 6.3 实屏证据（执行者提供）

在 `output/polish/20261031-1703-intake-supplement-specific-plan/` 保存：

1. 条件表单提交后出现的第 1 道补充问题（含默认项）。
2. 全部默认或回答后的确认门，能读到「本次旅行」与具体的城市/日期/同行人/风格。
3. 计划正文中的长途交通链路或研究范围，能看出不是通用模板。

使用虚构旅行数据、本地服务与离线模型；不要写入真实用户会话。

### 6.4 真人验收（用户操作）

1. 在「按条件规划」填写一趟多城市旅行（例如深圳市 → 北京市、上海市，5 天，2 位成人，经典均衡）→ 提交后先看到与本趟旅行相关的补充问题，而不是直接进入确认门。
2. 对问题选择默认或具体偏好 → 进入确认门；计划正文能读到城市顺序、日期、同行人、风格和你的选择。
3. 返回重新提交同一趟旅行 → 已回答的问题不重复出现；自然语言入口不受影响。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-31 17:10 · ZCode / deepseek-v4.1-flash-1017

- 改动摘要：新增条件表单入口的基线补充问题：模型未出题且会话没有问答历史时，按本次受控身份生成最多 3 道可跳过问题（优先体验、城际交通、住宿取向），题面写出城市、线路和晚数，每题都带「按合理默认安排」出口；自然语言入口、已有问答和模型已出题的会话不追加。领域研究摘要与行程规划任务改为使用受控身份，写出城市顺序、日期、同行人、风格、住宿晚数和实际长途链路，确定性回退不再退回通用占位句；补充选择继续经现有 evidence 链路进入需求合同。
- 改动文件：`backend/travel_agent/conversation/intake_baseline.py`（新增）、`backend/travel_agent/conversation/chat/preparation.py`、`backend/travel_agent/planning/requirements/route_legs.py`、`backend/travel_agent/planning/requirements/approval.py`、`backend/travel_agent/planning/research/brief_builder.py`、`backend/travel_agent/planning/research/capability_planning.py`、`backend/tests/api/test_trip_intake.py`、`backend/tests/api/test_multi_round_intake_flow.py`、`backend/tests/planning/requirements/test_control_plane.py`
- 偏离方案及理由：基线问题按任务改为「条件表单 + 首次评估 + 模型没有出题」时追加；`previous` 无问题、无回答、无归档时也视为首次，包括一次失败（unavailable）评估后的首次成功评估。风格里已有明确兴趣时不问优先体验；原文或已识别要求已写城际方式/住宿取向时跳过对应问题；城际问题要求能推导出实际长途链路（含往返），住宿问题只在多日行程出现。补充选择经 `merge_intake_answers` 进入归一化输入并保留在 `intake_evidence_sources`；为避免归一化模型漏抽取时用户选择在确认前消失，`_baseline_intake_preferences` 只把 `explicit_selection` 的基线选择保守投影到确认门的「已识别的旅行要求」，默认项不投影，未新增 Intent/Constraint，也不绕过归一化。并发与 checkpoint 测试的前置状态增加一条已归档回答，避免基线问题改变被验证的版本/租约路径；原有安全与授权断言未放宽。未改数据库 schema、公开 API/SSE 字段、计划门 token 算法/版本/修订/取消逻辑或 Provider 时序。
- 实际运行的检查与结果：`pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/api/test_multi_round_intake_flow.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_model_research_plan_flow.py -q` 通过（126 passed）；追加 `test_confirmation_contracts.py`、`test_semantic_confirmation_contract.py` 通过（74 passed）；非数据库后端全量 `backend/tests/ --ignore=backend/tests/db` 通过（1059 passed）；改动后端文件 Ruff 通过。`cd frontend && npm run type-check && npm run test` 通过（19 个测试文件、161 项测试）；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 npx playwright test e2e/planner-intake.spec.ts e2e/multi-round-intake.spec.ts --workers=1 --output=../output/polish/20261031-1703-intake-supplement-specific-plan/playwright` 通过（9 passed）。未调用真实付费模型、外网或真实用户数据。
- 实屏证据：`output/polish/20261031-1703-intake-supplement-specific-plan/baseline-intake-full.png`、`baseline-question-1440x900.png`、`plan-gate-full.png`、`plan-gate-plan-text.png`、`plan-gate-requirements.png`、`workspace-trip-card.png`、`screenshot-check.json`。截图使用本地 Vite 8080 与离线拦截的虚构行程；问题与计划正文由本轮真实后端函数生成后作为离线 fixture，确认门截图的 `source=deterministic_fallback`，正文仍包含「本次旅行」、城市顺序、日期、同行人、风格、实际长途链路和补充选择。
- 遗留问题或需要指挥决定的事：运行中的后端进程启动于 17:02，早于本轮 Python 改动且未重启（避免在该环境依赖可能挂起的 `./run.sh`/Docker CLI），体验验收前需手动重启后端以加载新代码。基线问题的去重按原文/已识别要求中的关键词判断，用户用非常规措辞提前表达偏好时仍可能被再问一次；这不影响安全或授权。默认选项不会产生正向研究要求，也不会出现在确认门的已识别要求中。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
