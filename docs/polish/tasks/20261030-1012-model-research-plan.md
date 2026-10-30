# 标题：确认的研究计划须真实反映模型和本次需求

- 编号：20261030-1012-model-research-plan
- 状态：待代码验收
- 创建：2026-10-30 10:12
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`（尤其 INV-PLAN-001、INV-INTENT-001/004/005、INV-RUN-003、INV-BUDGET-001）、`docs/architecture/overview.md`、`backend/tests/README.md` 和 `frontend/e2e/README.md`。

## 1 用户反馈

- 原话：「4 核查研究计划为何像固定内容，必须真实基于模型及本次需求生成，不得用固定计划冒充模型结果」；「截图其余没有标红内容不能随意删除。」
- 后续确认：「你可以核实啊，这是你的自由啊，我们本身为了提供更加优质的旅行计划，那让用户进行信息的补充和选择是很正常的。」用户明确允许为可靠规划增加必要的逐项核实、补充和选择。
- 反馈图：`output/polish/20261030-1012-model-research-plan/feedback-1.png`。右侧“本次会这样研究”显示目的地调研、交通住宿、行程规划等通用描述；计划正文没有被标红为删除项。
- 只使用离线/模拟测试，不调用真实付费模型、不修改真实用户数据。本批文档完成后紧接着交付执行，不暂存、不提交。

## 2 现象与发生条件

计划门在开始调研前展示 `plan_text`；缺失时前端回退 `plan.steps.tasks`。截图未提供 SSE 原始载荷，不能由截图断言实际走了哪个分支。截图显示固定风格的计划，但用户并未声称看到过明确的“由模型生成”标签。需要检查实时、补充修改后的新计划和已保存计划的恢复。

## 3 根因

- `backend/travel_agent/planning/requirements/normalization/node.py:70-91` 与 `normalization/model.py:37-92` 会让模型结构化理解本次需求，异常或校验失败时部分或全部确定性 fallback；这**不等于模型生成了研究计划**。
- `backend/travel_agent/planning/research/plan.py:68-100` 以合同为输入调用纯函数构建查询和执行分组；`brief_builder.py:214-227`、`capability_planning.py:196-205` 用固定领域/分工句式加需求摘要。`requirements/approval.py:107-193` 将实际 `execution_plan` 和 assignment 序列化为门内 Markdown，目的地、日期、要求等会变，但计划本身不是模型写的固定格式投影，也没有前端硬编码的一份三步清单。
- `research/dispatch.py:61-128` 以同一 `execution_plan` 调度。`docs/invariants.md` 的 INV-PLAN-001 要求同一 Request Contract 的 brief、查询和执行图是纯函数投影，planner 不能调用模型；INV-INTENT-005 要求 Intent/Constraint 一次归一化。为计划加无约束润色或在 planner 偷加模型调用都无法同时满足用户与现有架构。前端 `TripBriefPlanGate.tsx:91-103` 在任务缺失时还可能回退展示内部 agent 名。

## 4 方案

目标状态：新产生的研究计划有可验证的、针对本次受控身份及完整需求的模型生成研究内容，用户确认的研究范围与后续真实查询/执行一致；不能把固定模板或仅做了需求归一化的规则计划说成模型生成。

必须做：

- 在不违反不变量的前提下，先完成本批 Intent/Constraint 的一次结构化归一化与必要问题；对来源、正向/排除/历史或约束含义无法安全确定的研究事实，结合原始上下文逐项请用户确认或纠正。只有信息完整、确认与当前版本绑定后才单独调用模型生成研究计划，并让有效计划进入最终 Request Contract，成为确认内容和 dispatcher/worker 实际研究范围的依据。同一最终合同须产生相同图；不得让 Brief/Planner/Worker 再解释原始要求或让 planner 调模型。
- 考虑目的地顺序、日期、同行与风格、硬约束和明确排除、未决事项及补充修改；模型建议不得越权扩张用户要求、引入未知节点/工具或伪造事实。补充后生成新的同代合同与计划，批准时执行用户所见版本；确认/修改/取消、既有授权、预算和 deadline 封存仍正确。
- 对模型超时、非法/部分结果和 fallback 明确处理：新计划不能把纯模板或无有效模型计划内容包装成模型结果，不得静默继续为用户执行一份未确认的替代计划；提供真实可理解的失败、重试或取消路径。保留实质输入/未决项，不把无法理解的要求丢掉。控制输入和输出规模，沿用既有限时和成本治理；确认前增加的 token 成本与延迟须在执行记录中如实说明，不得假设确认后才封存的预算已覆盖。
- SSE、恢复和现有历史快照不得伪造来源；旧的待确认计划若来源不可追溯，应如实处理且保留确认、取消、修改能力，恢复或刷新不偷偷触发新的模型调用。确保新旧计划均不把内部 agent 名或原始载荷当作用户计划正文；保持未标红的计划与已识别要求可见。
- 测试在外部模型、工具和持久化边界用替身，验证从真实合同/计划链到确认和 dispatcher 的同代关系；仅核对不同输入下文案不同、或只验证模型被调用，不足以证明计划来自模型并且被执行。现有测试若逐字断言通用模板，应改为验证执行同源、硬约束与覆盖语义，不得直接删掉这些保护。

执行者自己决定：结构化语义确认与模型计划的具体格式、校验及投影。用户已授权必要的核实和选择；允许为此及先澄清再生成计划所需的兼容 API/SSE 与 checkpoint 扩展、独立的有上限前置模型调用。不得修改数据库 schema；明确记录新增延迟、token 消耗和上限。

不许碰：修改或绕过 `docs/invariants.md`，将模型调用放进 planner，重复归一化同一批 Intent/Constraint，绕开硬约束/排除、确认门、预算/时限、租约或恢复规则；不得修改数据库 schema、真实用户数据或调用真实外部服务。不得改既有任务文档。基线 `/tmp/journeypilot-review-oCppsF/existing-tracked.patch`、`existing-status.txt` 和其 `frontend/` 五个文件快照必须保留；先核对差异，在已有修改上窄改，禁止 reset、stash、覆盖、暂存或提交这些已有改动。与确认面板任务共享前端时串行协调。

## 5 停下来报告的情况

若经核实即使用户逐项确认也无法建立可验证的来源与执行授权、无法拒绝冲突/隐藏工具参数或不能安全恢复旧 checkpoint，停止并报告；不得用禁词清单或虚假 fallback 冒充安全。若需要修改数据库 schema、预算规则、不变量或调用真实服务，也停止。其余遵守 README 通用停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 用同一份请求、两份在用户允许范围内不同且合法的 fake 模型研究建议，验证各自进入合同、确认计划与实际查询/assignment；相同最终合同重复投影结果相同。不能通过回显用户原句或只改变润色句子冒充覆盖。
2. 不同目的地/同行/风格/硬要求及排除与补充修改能影响对应计划和执行；补充前后 revision/generation 区分，批准展示的同一版本并在 dispatcher 消费；显式排除酒店不得触发住宿查询，正向剩余住宿要求与原有合同语义仍成立。
3. fake 模型超时、错误、非法/部分结构及 fallback 不冒充成功，不丢实质要求；新计划不可静默执行未确认内容，重试/取消可用。历史来源不明的恢复不虚构模型来源、不自动调用模型，已有确认/修改/取消保留。
4. 受控身份和完整计划/要求在 UI、SSE 和恢复中一致，无内部 agent 名或原始载荷泄漏；planner 不调用模型，同一合同确定性成立，预算和 deadline 的既有封存及恢复边界不回退。

### 6.2 必须运行的检查

以下命令从仓库根目录运行。只用 fake LLM、内存/checkpoint/store 和外部工具替身；禁止 live-planning、真实数据库和 Provider；若某测试不满足隔离则停止并说明，不能用真实调用代替。

- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/conversation/test_chat_execution.py -q`
- 将 6.1 的新离线行为测试放入上述责任范围或单独文件，运行并记录精确命令；应覆盖真实归一化→合同→计划门修改/审批→dispatcher 的内部链路，只替换外部边界。不得把 skipped 当作通过。
- `cd frontend && npm run test -- src/features/travel/model/planApprovalGate.test.ts && npm run type-check`
- 如修改模型/恢复 UI，先启动 `cd frontend && PORT=5173 npm run dev -- --host 127.0.0.1 --strictPort`，再运行 `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1 --grep 'plan gate stays|cancel keeps|narrow plan gate' --output=../output/polish/20261030-1012-model-research-plan/playwright`，fixture 拦截网络并检查逃逸。

### 6.3 实屏证据（执行者提供）

不需要。若实现涉及 UI 状态或新失败路径，补充合成数据截图：不同 fake 计划、失败可重试和历史恢复，保存到 `output/polish/20261030-1012-model-research-plan/`。

### 6.4 真人验收（用户操作）

1. 用离线 fake 模型分别提供两份与同一虚构旅行相关但不同的研究建议 → 门内计划体现差异；确认后离线执行记录对应当前计划。
2. 修改要求后重新整理 → 新计划体现修改；模拟模型失败和刷新旧门 → 不伪称模型成功，恢复与可用操作符合上面的边界。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 · Workflow / pi

- 改动摘要：实现同次需求归一化生成研究计划草稿、计划版本凭据、前端冲突处理和多目的地 Provider 查询；实现仍未通过安全验收，不应部署或用于真实规划。
- 改动文件：`backend/travel_agent/planning/requirements/`、`backend/travel_agent/planning/research/`、`backend/travel_agent/conversation/chat/`、`backend/travel_agent/api/` 下相关模块及测试；前端审批链和 `frontend/e2e/session-state.spec.ts`。完整清单以工作区差异为准；原有未提交内容不属于本任务。
- 偏离方案及理由：审批版本校验需要增加公开 token 字段，当前仅为未验收实现。保守来源校验实验触发已有需求归一化合同回归，已撤回实验，不以放宽测试冒充完成。
- 实际运行的检查与结果：后端定向测试 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/research/test_model_research_plan_flow.py backend/tests/conversation/test_chat_execution.py backend/tests/api/test_chat_use_cases.py -q`：177 项通过；相关 Ruff 通过。前端类型检查、107 项单测、审批与版本冲突相关浏览器检查通过。独立复审另行复现了授权范围绕过，测试通过不代表安全验收通过。
- 实屏证据：`output/polish/20261030-1012-model-research-plan/` 中为离线模拟测试材料。
- 受阻：当前模型归一化的 Intent 值、历史来源和餐饮限制仍可能使未经授权内容进入 Gate 或真实查询；简单的原文匹配/禁词方案会破坏既有合法意图，无法同时证明安全与保留原功能。需要先确定可验证的来源与执行合同、无法判定时的澄清/降级策略，再实现并重新复审。多目的地和异常 token 修复虽通过定向检查，仍需整体复审。未调用真实付费模型或真实数据，未提交。

### 第 2 轮 · 2026-10-30 · pi

- 改动摘要：用户明确允许必要核实和选择；已修订方案，准备以可信逐项确认和独立计划生成取代模型文本自授权。新建三项真实图链路反例，分别复现模型自造、否定误读和 fallback 绕过。
- 改动文件：`backend/tests/planning/research/test_semantic_authorization_flow.py`；独立 worktree 中的候选合同和计划选择器尚未合并。
- 偏离方案及理由：按用户补充的流程，计划生成不能与未完成的需求梳理同一次模型输出；语义授权需要兼容协议扩展。
- 实际运行的检查与结果：上述三项离线反例当前均失败，作为明确阻断；其余不包含这三项的定向后端组合 299 项通过。未调用真实模型或服务。
- 实屏证据：不需要。
- 遗留问题：仍须实现用户逐项确认、独立计划生成、实际 Provider 参数守卫与旧 checkpoint 升级，并经独立复审。未提交，不可用于真实规划。

### 第 3 轮 · 2026-10-30 · pi

- 改动摘要：从隔离 worktree 复制候选选择器，模型只能选择服务端提供的候选 ID，不能返回额外检索文本；独立审查补充了内部标识混入反例并修复。该原语尚未接入图、确认合同或 Provider。
- 改动文件：`backend/travel_agent/planning/research/selection.py`、`backend/tests/planning/research/test_selection.py`。
- 偏离方案及理由：模型选择器仅约束结构；来源合法性、用户确认和执行权限必须由后续责任边界提供，不能单凭此原语认定安全。
- 实际运行的检查与结果：选择器离线测试 27 项通过，Ruff 通过；完整真实链路的语义授权 3 项反例仍失败。
- 实屏证据：不需要。
- 遗留问题：确认合同正在隔离 worktree 返工复审，之后仍需整合前后端逐项确认、独立计划生成、执行守卫和旧状态恢复。未提交。

### 第 4 轮 · 2026-10-30 · pi

- 改动摘要：增加精确来源候选解析、已确认候选 ID 到计划草稿的确定性编译，以及按完整参数、权限哈希和条件回退校验的操作清单原语。它们尚未接入工作流或工具执行，因此不构成完整授权。
- 改动文件：`backend/travel_agent/planning/requirements/evidence_resolution.py`、`research/{selection,plan_from_selection,operation_authority}.py`、`requirements/research_plan_contracts.py` 及对应离线测试。
- 偏离方案及理由：来源字面匹配只用于提出待核对候选，不代表肯定/否定/安全；模型生成的选项中出现、但没有独立用户输入支持的具体地点不会被当作用户原文。旧校验器拒绝未经确认合同核实的候选引用。
- 实际运行的检查与结果：选择器、计划编译、操作清单及来源解析定向离线检查通过；新增的计划时序和语义授权真实链路反例共 4 项仍失败，属于阻断，不计入通过数。
- 实屏证据：不需要。
- 遗留问题：服务端逐项确认、持久调用预算、计划生成节点和所有工具/缓存执行守卫尚未联通，隔离代理对确认合同、交互与预算原语仍在返工复审。未提交，不可用于真实规划。

### 第 5 轮 · 2026-10-30 · pi

- 改动摘要：隔离代理实现预审批调用预留原语及逐项确认 UI 原型，均尚未合并；发现并要求返工预算快照、重试凭据和结果隐私边界。
- 实际运行的检查与结果：隔离代理违反了“只用离线替身”的要求，运行了两项真实 PostgreSQL 测试。核查其 fixture：连接本地 PostgreSQL，分别创建并删除随机 `jp_test_*` 临时数据库，测试写入仅针对这些临时库；未发现其测试代码修改用户数据库，但不能把这次行为说成未连接真实服务。已要求代理禁止 socket 并替换为纯离线测试。其余已合并的候选选择、计划编译与操作清单定向测试 47 项通过。
- 遗留问题：预审批原语尚未验收，不得直接合并；逐项确认、计划生成、执行守卫及 4 项真实链路反例仍未完成。未暂存、未提交主工作区。

### 第 6 轮 · 2026-10-30 · pi

- 改动摘要：已复制并离线验证结构化确认合同原语；计划编译对带候选 ID 的标签逐字保留，修复批准候选空白被改写的问题。历史模型选项若缺少独立用户来源，不作为正向候选。
- 改动文件：`requirements/confirmation_contracts.py`、`requirements/evidence_resolution.py`、`research/{selection,plan_from_selection}.py`、`requirements/research_plan_contracts.py` 及相关测试。
- 偏离方案及理由：确认合同和操作清单尚为独立原语；只有把服务端保存、逐项选择、最终计划与实际执行完整绑定后才可视为授权。表单地点和风格目前标记未验证，不能仅凭客户端 source 字段授权。
- 实际运行的检查与结果：来源、确认合同、计划选择/编译、操作清单的离线定向 104 项通过，另外核对了批准标签逐字保留回归；4 项完整语义与计划时序反例仍失败。Ruff 通过。
- 实屏证据：不需要。
- 遗留问题：计划仍在归一化模型调用中提前生成，逐项确认、预审批预算和 Provider 守卫尚未接入。隔离代理曾违规连接本地 PostgreSQL，临时库边界已记录，后续禁止真实连接。未提交。

### 第 7 轮 · 2026-10-30 · pi

- 改动摘要：为逐项确认建立严格请求合同、前端单选核对界面与版本绑定的服务端接受帧；只有已落盘且身份匹配的确认 checkpoint 才发送接受帧。限制历史来源不能直接给出正向选择，审计与预审批内部事件不公开原始结果。候选标签编译逐字保留。
- 改动文件：`backend/travel_agent/conversation/chat/{contracts,execution,progress_events}.py`、`planning/{state,workflow,invalidation}.py`、`api/{sse_projection,audit_projection,presenters/runs}.py`、前端语义核对组件及请求/事件类型，相关离线测试。
- 偏离方案及理由：确认 UI 已可处理合成事件，但后端尚未生成真实 challenge 或授权执行；确认接受帧必须验证持久 checkpoint，不能仅凭 chat_start 或 gate 切换清除用户选择。
- 实际运行的检查与结果：严格断言界面和 gate 恢复单测 50 项通过；语义 UI 离线浏览器 2 项通过；checkpoint 接受帧、API 合同、旧计划相关定向 106 项通过，相关 Ruff 与类型检查通过。语义授权与先澄清后计划的 4 项真实图链路反例仍失败，不能计入通过数。
- 实屏证据：`output/polish/20261030-1012-model-research-plan/semantic-gate-390.png` 与 `playwright-semantic-integration/`（均为合成数据）。
- 遗留问题：待把可信来源、逐项决策、独立计划生成及实际 Provider 参数守卫接成闭环，旧状态需安全升级；预审批 journal 原语仍在离线复审。主工作区未提交。

### 第 8 轮 · 2026-10-30 · pi（收尾核对）

- 改动摘要：按用户要求停止继续扩展并核对现状；确认界面与协议骨架、来源记录、计划选择和操作清单原语已存在，但尚未接成真实授权链路。
- 改动文件：以工作区差异和前几轮记录为准；没有暂存或提交。
- 偏离方案及理由：无法安全地把模型候选直接当作用户确认事实；未将独立原语标记为完成，也未绕过失败用例。
- 实际运行的检查与结果：网络被禁止的后端定向组合 **517 项通过、4 项失败**；失败是需求未澄清时仍生成计划、模型自造对象、否定误读和 fallback 绕过。前端 type-check 与 150 项单测通过；本次相关离线浏览器检查 5 项通过；Ruff 与 `git diff --check` 通过。
- 实屏证据：`output/polish/20261030-1012-model-research-plan/` 中的合成截图与测试记录。
- 受阻：后端真实逐项确认、已确认合同编译、计划生成与实际 Provider/缓存参数守卫未完成；当前代码不应部署或用于真实旅行规划。

### 第 9 轮 · 2026-10-31 01:28 · Kimi Code / Deepseek 辅助

- 改动摘要：归一化不再同时生成研究计划；必要缺口、来源不明、排除歧义或预算口径问题通过普通问答等待回答并重新分析，无未决项后由独立模型从已澄清合同的候选 ID 生成研究计划。最终审批绑定精确 operation manifest 和独立 OperationApproval；在 worker 模型、Provider、fallback、cache/journal 重放前校验合同、批准 token、assignment、参数和租约。按用户最新反馈，主流程及旧状态恢复均不展示逐项参数确认页。
- 改动文件：`backend/travel_agent/planning/requirements/`、`planning/research/`、`planning/{state,graph,recovery,weather}`、`tools/execution.py`、相关 intake/chat/API 模块与离线测试；前端必要问答、计划门、恢复投影与离线 E2E；`docs/architecture/overview.md`。完整清单以工作区差异为准，原始脏工作区和其他前端任务未混入本任务。
- 偏离方案及理由：用户明确要求只做必要提问和回答，因此取消逐项语义确认 UI，改为必要问答加最终一次性计划审批。确认前需求归一化单次最长 120 秒、独立计划选择单次最长 30 秒、最多重试 2 次，均产生额外 token，不计入批准后的 Run 预算。无法预编译的动态 POI 详情、RAG、部分铁路站点/日期和市内接驳调用 fail closed；计划门提前显示执行边界，必需 worker 没有 operation 时禁止批准。
- 实际运行的检查与结果：全部使用 socket 禁止插件、fake LLM、内存 checkpoint/store 和 mock Provider。原始阻断文件最终 15 项通过；任务定向与 API/chat 组合 311 项通过；research/tools、预算、并发和恢复组合 297 项通过。前端 type-check、150 项单测通过；intake/多轮/必要回答浏览器 10 项通过，计划门恢复等另 6 项通过。Ruff 与 `git diff --check` 通过。未调用真实模型、网络、数据库或真实用户数据。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/necessary-question.png`、`final-plan-gate.png`；均为本地虚构数据与网络拦截环境。
- 遗留问题或需要指挥决定的事：独立复审发现的逐项排除误跳过、否定短语、domain 级 operation 缺失和模型 summary/params 自造查询均已修复并有反例覆盖。动态 Provider 调用只在已有精确预授权时执行，其余会明确降级或阻断，不能宣称所有 Provider 路径均已覆盖。

## 8 指挥验收（指挥填写）

### 2026-10-30 · 受阻

独立复审确认模型可能将历史背景、错误的模型 Intent 或饮食禁忌投射到实际检索；当前实现不得验收。用户随后明确提出编写计划前追问，并于本轮明确允许为高质量规划做必要核实和选择。方案已修订：先逐项核实来源与含义，再单独生成计划；允许为此进行兼容协议扩展及有上限的额外模型调用，继续执行并独立复审。

## 9 真人验收（指挥代录）
