# 标题：正式研究前先补齐必要信息并确认计划

- 编号：20261030-1416-clarify-before-plan
- 状态：待代码验收
- 创建：2026-10-30 14:16
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`docs/architecture/overview.md`、`backend/tests/README.md`、`frontend/e2e/README.md`、`20261030-1012-model-research-plan.md`。

## 1 用户反馈

原话：「在一开始的时候，会输入自然语言，或者是通过这个表格来输入这些信息。在这之后，你要把这些信息拿进来之后进行分析，之后来去审查，就是在我们进行研究计划的编写。之前还需要掌握哪些信息才能让我们把这个计划写出来？就是在用户输入信息之后，我们要对他输入信息进行一次梳理，要看我们还缺什么。然后在给用户计划之前，先让用户回答我们所问的问题，然后我们再分析，之后给出一个完整的计划，让用户审批。在计划通过之后，我们就正式开始任务」

用户要求继续已有任务，并明确表示「你可以核实啊，这是你的自由啊，我们本身为了提供更加优质的旅行计划，那让用户进行信息的补充和选择是很正常的」。只使用离线 fake 模型、模拟 Provider 和虚构旅行信息；不得调用真实付费模型或修改真实用户数据。保留所有既有未提交改动。

## 2 现象与发生条件

自然语言和表格入口共用服务端 intake。缺口评估可提出问题，但用户提交答案后当前路径可能直接创建 Run，而不重新评估；已有多轮问题上限还可能吞掉新的必要问题。已有研究计划任务因授权范围与模型臆造的 P1 安全问题受阻，不能把本任务的修复说成完整安全验收。

## 3 根因

- `backend/travel_agent/conversation/chat/preparation.py` 中，已有成功评估且带 `guided_intake` 的回答提交不会触发新一轮 `understand_trip_intake`。
- `backend/travel_agent/conversation/intake.py` 对已答问题计数限制新问题；容量用尽时会忽略模型仍返回的未答问题。`GuidedIntakeQuestions.tsx` 的收起状态也需要检查多轮 SSE 返回时是否能重新显示。
- `backend/travel_agent/planning/graph.py` 当前在审批前运行 `weather_context_builder`，而该节点会调用天气 Provider；这不符合「计划通过之后正式开始」的时序。具体依赖与恢复路径由执行时核实。

## 4 方案

目标：两种入口都先评估必要缺口；存在缺口则逐轮等待用户作答并重新评估。没有必要缺口时才展示同一代完整计划；只有用户明确批准该版本后才启动正式研究及天气 Provider。

必须做：

- 后端以服务端保存的原文、已答问题、用户补充和受控身份为准；回答提交后重新分析，每一轮发现新的必要问题都等待用户回答。不能因轮次或数量上限静默视为信息已完整；入口评估失败时不创建 Run，后续合同化发现未决项时可用已有 Run 暂停追问，但不能展示计划或启动研究。
- 无必要问题时不要为了提问而提问。原文、答案、补充和已确认身份在后续合同中保留；不重复询问已回答的同一个问题，不允许客户端替换服务端问题或原文。
- 检查等待、刷新、重试、多轮返回的 UI 与焦点，保证用户能看到并回答新问题；不把等待澄清错误显示成正在执行。
- 将外部天气查询及其他正式研究调用放在审批之后；审批前的确定性准备、必要的需求分析模型调用仍可执行。保留补充修改、取消、版本 token、预算/期限封存、重启恢复与补充路由。
- 新增针对两种入口、多轮追问、上限、失败和审批前后实际 Provider 调用的离线行为测试；确认测试替身只替换模型、Provider 和持久化等外部边界。

执行者自己决定：问题容量与达上限后的可解释停止方式、前端的多轮展示细节和图中天气节点的安全落点。每一轮回答后重评估是用户授权的额外前置模型调用；应在执行记录如实说明延迟与 token 成本不计入审批后运行预算。

不许碰：不得绕过 `docs/invariants.md`、模拟真实用户审批、隐瞒模型研究计划安全阻塞；不得修改数据库 schema、真实用户数据或无关变更，不修改已有任务以外的产品范围。

## 5 停下来报告的情况

发现无法安全绑定用户答案、无法在不中断旧 checkpoint 的情况下调整时序、评估失败可能触发实际查询，或需要数据库 schema/预算规则变更时，停止并记录。用户已允许必要的逐项核实和选择，可做为此必需的兼容 API/SSE 扩展。研究计划授权边界仍须在 `20261030-1012-model-research-plan.md` 单独完成及复审，不能以本任务替代。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 自然语言和已填表单均能识别缺口；两轮相关问题先后出现，各次回答送回模型。入口待答/评估失败不创建 Run；合同化后发现未决项可以在 Run 内继续追问，但未答时不展示计划、不启动 Provider。无缺口时不额外问。
2. 添加或修改答案后重评估；历史问题和补充保留，已答的不重复。达容量或模型失败明确停止，不把未答问题静默当完成；刷新和服务端原文权威不回退。
3. 内存 checkpoint 下未批准、取消、补充修改和过期 token 都没有正式 Provider 调用；有效批准后天气和研究调用发生，预算/期限在批准时封存，且旧 checkpoint 的合理恢复不退化。
4. 通过多轮提问后 UI 回到可操作问题、不会卡在“准备正式规划”；用户明确批准计划前不显示研究进行中。

### 6.2 必须运行的检查

- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py backend/tests/planning/research/test_lodging_exclusion_flow.py backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/test_node_presentation.py -q`
- 新增完整时序的内存 checkpoint/fake Provider 测试；实际命令写执行记录。
- `cd frontend && npm run type-check && npm run test`
- 使用网络拦截的 `frontend/e2e/planner-intake.spec.ts`，添加并运行多轮真实交互测试，禁止外网或真实用户数据。

### 6.3 实屏证据（执行者提供）

使用离线浏览器截取第一次回答后的第二轮问题及最终确认门，保存于 `output/polish/20261030-1416-clarify-before-plan/`。

### 6.4 真人验收（用户操作）

1. 输入虚构旅行，带一项有歧义的预算或行动限制 → 看到具体问题；回答后若还有缺口先看到下一问。
2. 所需信息明确后查看计划，修改或取消不触发查询；明确批准后才开始正式调研。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 14:16 · pi

- 改动摘要：两种入口提交答案后重新评估，可多轮追问；未决合同先追问、不能批准空计划；审批后才调用天气 Provider。补充修改的未决原文可继续归一化，并照顾旧 checkpoint 的无偏移来源恢复。
- 改动文件：`backend/travel_agent/conversation/intake*.py`、`conversation/chat/preparation.py`、`api/chat_errors.py`、`planning/{graph,state,execution}.py`、`planning/requirements/{approval,normalization,constraints/sources}.py`、`planning/weather/node.py`，相关后端测试；`frontend/src/features/travel/components/planning/{GuidedIntakeQuestions,TripBriefPlanGate}.tsx`、`frontend/src/features/travel/model/planApprovalGate.ts`、离线 E2E；中英文 README 与架构时序说明。多目的地发现修复及测试仍属于研究计划任务。
- 偏离方案及理由：问题数量上限由 4 扩至 12，超限停止并提示，不静默丢题；合同化后通过现有计划门载荷的空步骤与无 approve 选项呈现澄清，复用原有 SSE 字段和版本凭据。用户回答各轮问题后会再次调用需求分析模型，单次上限 45 秒，产生审批前额外 token，不计入审批后的 Run 预算。
- 实际运行的检查与结果：后端含归一化、澄清、真实图顺序、旧 checkpoint、Provider、租约及 API 的离线定向组合 272 项通过；相关 Ruff 与 `git diff --check` 通过。前端 type-check、108 项单测通过；`planner-intake` 与多轮提问离线浏览器 8 项通过；计划门/动效/提问集成离线浏览器 7 项通过。此前整套浏览器测试有两条旧断言要求默认展开过程卡，已改为验证紧凑态可手动展开且原内容保留，再次通过。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/second-question.png`、`unresolved-question.png`、`plan-gate.png`。
- 遗留问题或需要指挥决定的事：独立审查进行中；原研究计划 P1 来源授权与饮食限制问题尚未消除，本轮不可作为完整任务交付。首次图时序试验暴露预算台账可能访问本地数据库，已替换为内存台账；使用虚构 Run ID，未写入真实数据。

### 第 2 轮 · 2026-10-30 15:48 · pi

- 改动摘要：补充会话内并发串行化、在执行前核对最新已保存需求、独立保存回答后也强制重评估；未决补充保留原文与旧 checkpoint 的安全恢复；按版本在本标签页保存未提交回答；研究窗口关闭时不调用天气 Provider。历史回答超过单轮容量时归档，继续追问而不是丢弃。
- 改动文件：上一轮文件，以及 `backend/travel_agent/conversation/intake_lock.py`、`backend/travel_agent/api/routes/sessions.py`、`backend/travel_agent/planning/weather/context_builder.py`、`frontend/src/features/travel/model/planGateDraftStorage.ts`、相关测试。`archived_answers` 是现有 intake 载荷中的新增可选字段，未修改数据库 schema；输入草稿保存在浏览器当前标签页，提交后清除。
- 偏离方案及理由：需求澄清历史需要可恢复的结构化归档；原任务未授权新增公开字段，该部分仍需指挥与用户决定，不能直接验收。会话锁依据项目的单 API 进程架构，只保护本进程内并发，不宣称跨进程互斥。
- 实际运行的检查与结果：后端离线定向 289 项通过，含新旧 checkpoint、并发旧评估与新回答、补充重分析及天气时间窗；前端 111 项单测、type-check 和 8 项计划门/多轮澄清/恢复浏览器检查通过；相关 Ruff 与 `git diff --check` 通过。未调用付费模型或真实 Provider。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/`，包含两轮提问、刷新草稿和确认门的合成浏览器材料。
- 受阻：研究计划仍与需求归一化同一次调用生成，且模型自造的结构化值与 fallback 可能绕过真实用户授权；要保证用户所描述的顺序和安全，需要独立的、版本绑定的语义确认合同及后续计划生成步骤。该方案涉及公开交互合同和额外模型调用，超出原任务授权；未提交、不应投入真实规划。独立复核仍在进行。

### 第 3 轮 · 2026-10-30 · pi

- 改动摘要：根据复审修复历史 amendment 只重放未决分句导致已确认预算丢失的问题；后续归一化即使漏抽取，也保留上一代有效健康约束。限制需求分析提示的估算 token，超限时不调用模型并提示重新整理，不截断已答内容。
- 改动文件：`backend/travel_agent/planning/requirements/constraints/{sources,assembly}.py`、`backend/travel_agent/conversation/intake.py`、相关离线测试。
- 偏离方案及理由：已存在的有效约束不会因模型一次漏抽取而被静默撤销；可靠撤销仍依赖待授权的结构化语义确认，当前不宣称能处理所有更正。
- 实际运行的检查与结果：澄清、历史 checkpoint、预算/健康约束重放及提示容量定向测试 48 项通过；相关 Ruff 通过。更大范围集成及独立复核尚未完成。
- 实屏证据：不需要。
- 遗留问题：前述结构化语义确认、计划生成时序与执行授权仍受阻；等待用户对协议和交互范围的决定。

### 第 4 轮 · 2026-10-30 · pi

- 改动摘要：用户明确允许必要的核实与选择。补充 intake 单调版本与持久化 CAS，迟到的旧页面不能覆盖新草稿；正常启动与消费 intake 共用事务，旧运行写入 turn 不再删除新草稿。按原始命令顺序解决预算冲突，避免旧预算在重放时复活。
- 改动文件：`backend/travel_agent/conversation/{intake,intake_contracts,intake_lock}.py`、`conversation/chat/`、`api/routes/sessions.py`、`memory/chat_session.py`、`storage/trip_run_store.py`、约束来源和冲突处理、前端 intake 表单与请求类型及相关测试。
- 偏离方案及理由：新增兼容的 intake 版本字段，旧页面若缺少当前版本须刷新；这属于用户授权的澄清流程必要协议扩展。数据库 schema 未改；生产启动与清理共享事务，本次只用内存和离线 SQL 替身验证，未运行真实数据库测试。
- 实际运行的检查与结果：不包含已知语义授权反例的定向后端组合 299 项通过；语义授权新反例 3 项仍失败，表明该部分不可验收。前端 type-check、111 项单测、11 项离线浏览器测试通过；Ruff 与 `git diff --check` 通过。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/` 下的离线浏览器材料。
- 遗留问题：逐项语义确认、确认后单独生成模型计划及 Provider 参数权威边界仍在实现；新合同的独立实现/复审代理在运行。不得将当前版本用于真实规划。

### 第 5 轮 · 2026-10-30 · pi

- 改动摘要：用户授权必要核实和选择后，增加服务端 intake 版本及存储层条件写，拒绝迟到的旧页面；Run 启动与 intake 消费共用事务，旧 turn 保存不再清除新草稿；历史预算冲突按原始命令顺序而非重放时间裁决。
- 改动文件：`backend/travel_agent/conversation/`、`api/routes/sessions.py`、`memory/chat_session.py`、`storage/trip_run_store.py`、约束冲突解析与相关测试；前端 intake 版本回执与离线双页面测试。
- 偏离方案及理由：新增兼容的 `intake_revision` 字段及冲突响应；涉及数据库事务但无 schema 迁移。旧页面必须刷新后重新核对，避免静默覆盖。事务只在离线内存与 SQL 替身测试中验证，未连接真实数据库。
- 实际运行的检查与结果：语义授权反例之外的定向后端组合 299 项通过，前端 type-check、111 项单测与 11 项离线浏览器检查通过；Ruff 和 `git diff --check` 通过。新增 `test_semantic_authorization_flow.py` 的 3 项真实反例仍失败，明确作为后续阻断，不计入通过数。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/`。
- 遗留问题：结构化逐项语义确认、确认后单独生成研究计划及实际 Provider 执行权限仍在开发与独立复审。未调用真实付费模型或用户数据，未提交。

### 第 6 轮 · 2026-10-30 · pi

- 改动摘要：对每份 intake 增加不可复用 ID 和修订号，修复清空后版本复用；旧草稿在读取时获得稳定 legacy ID，缺少版本凭据的旧写请求被拒绝。只读重展示不再写入。Run 在真正保存含同一原文和身份的 checkpoint 前保留输入，断连或重启可回到需求草稿，不自动调用模型。
- 改动文件：`backend/travel_agent/conversation/intake*`、`conversation/chat/`、`memory/chat_session.py`、`planning/workflow.py`、`storage/trip_run_store.py`、前端 intake 状态与离线测试。
- 偏离方案及理由：启动不再立即清空草稿；只有真实 checkpoint 证明包含同一输入后才条件清理。旧客户端写请求必须刷新获取 ID 与版本。没有数据库 schema 变更；持久事务仅由离线替身检查，尚未运行真实数据库测试。
- 实际运行的检查与结果：输入版本、ABA、旧客户端、只读回放、无 checkpoint 输入保留及 checkpoint 身份绑定等定向 139 项通过；双标签页版本/多轮提问离线浏览器 4 项通过，随后含 ABA 的双标签页检查 2 项通过。语义授权反例仍为 3 项失败，不计入通过数。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/playwright-id/` 与 `playwright-id-aba/`。
- 遗留问题：逐项语义确认、独立模型计划生成与执行守卫仍在实现；需要独立复审，不可投入真实规划。

### 第 7 轮 · 2026-10-30 · pi

- 改动摘要：补全 intake ID 与旧数据读取兼容，旧版本缺少 ID/修订号的写入拒绝；启动前保存输入，只有真实 checkpoint 包含相同会话、原文、身份和来源证据时才清理草稿。把用户原文、选中的答案、自由补充与模型问题上下文分开记录，默认选项不产生正向来源。
- 改动文件：`backend/travel_agent/conversation/{intake_contracts,intake_evidence,intake}.py`、聊天准备与执行、`memory/chat_session.py`、`planning/{state,workflow}.py`、前端 intake ID 与离线测试。
- 偏离方案及理由：历史归档补充了选项 ID/标签以保存用户选择的来源；无可验证拆分的旧归档标记为未验证，不当作正向授权。兼容字段保存于现有 JSON/checkpoint，没有数据库 schema 迁移。
- 实际运行的检查与结果：输入版本、ABA、旧草稿、恢复和来源拆分的离线后端定向 142 项通过；相关 Ruff 通过。双标签页及多轮提问离线浏览器 4 项通过，ABA 双标签页 2 项通过。完整语义授权 3 项反例仍失败，不计入通过数。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/playwright-id/` 与 `playwright-id-aba/`。
- 遗留问题：保存的来源记录本身不是授权；逐项语义确认、模型计划生成时序和执行参数守卫仍须完成并独立复审，尚未调用真实付费服务或提交。

### 第 8 轮 · 2026-10-30 · pi（收尾核对）

- 改动摘要：按用户要求停止扩展并记录现状。前置多轮追问、版本隔离及输入恢复已有实现和离线检查，但完整计划仍依赖未完成的语义授权链路。
- 改动文件：以此前记录和工作区差异为准；未暂存或提交。
- 偏离方案及理由：语义确认界面当前仅通过合成事件验证，不能当作已完成的后端闭环。
- 实际运行的检查与结果：本次后端定向组合 517 项通过、4 项语义/时序反例失败；前端 type-check、150 项单测及 5 项相关离线浏览器检查通过；Ruff 与 `git diff --check` 通过。后端测试使用网络屏蔽，未运行真实数据库并发测试。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/`。
- 遗留问题：与 `20261030-1012-model-research-plan.md` 共用的最终授权和计划生成尚未验收；当前后端改动不得用于真实规划。

### 第 9 轮 · 2026-10-31 01:28 · Kimi Code / Deepseek 辅助

- 改动摘要：两种入口继续支持多轮必要问答；合同化后只在缺口、来源、排除或预算口径需要核实时展示普通补充问题，回答后重新分析，无未决项才生成独立模型计划并进入最终审批。按用户最新反馈，取消逐项参数确认页，旧语义门恢复也降级为普通补充问题。最终批准后才查询天气和正式研究。
- 改动文件：`backend/travel_agent/conversation/`、`api/`、`planning/` 相关图状态、需求、研究和执行模块及离线测试；前端 intake、计划门、恢复投影与 E2E；`docs/architecture/overview.md`。未修改数据库 schema，原始脏工作区和其他前端任务未混入本任务。
- 偏离方案及理由：用户明确要求只问必要问题，因此不采用逐项执行字段确认页；以最终一次性计划审批作为正式执行批准。每轮回答的重新分析最长 120 秒，独立计划选择最长 30 秒、最多重试 2 次，产生审批前额外 token，不计入批准后的 Run 预算；持续无法理解的合同化澄清最多四轮，超过后明确失败。动态 Provider 无法预编译的参数 fail closed，并在计划门说明执行边界。
- 实际运行的检查与结果：全部使用 socket 禁止插件、fake LLM、内存 checkpoint/store 和 mock Provider。原始阻断文件最终 15 项通过；intake、控制面、chat 与计划任务定向组合 311 项通过；research/tools、预算、并发和恢复组合 297 项通过。前端 type-check、150 项单测通过；`planner-intake`、多轮问答和必要回答浏览器 10 项通过，另 6 项计划门恢复检查通过。Ruff 与 `git diff --check` 通过。未调用真实模型、网络、数据库或真实用户数据。
- 实屏证据：`output/polish/20261030-1416-clarify-before-plan/necessary-question.png` 与 `final-plan-gate.png`，分别为普通必要问题和最终计划审批，均为本地虚构数据与网络拦截环境。
- 遗留问题或需要指挥决定的事：独立复审发现的逐项排除误跳过、否定短语、domain 级 operation 缺失和模型 summary/params 自造查询均已修复并有反例覆盖。动态 POI 详情、RAG、部分铁路与市内接驳没有精确预授权时会降级或阻断，不能宣称所有 Provider 路径均已覆盖。

## 8 指挥验收（指挥填写）

### 2026-10-30 · 返工

独立复审发现，仅追问模型标记为未决的条目不足以证明语义授权；计划草稿也在缺口解决前生成。用户明确允许必要的逐项核实、补充和选择，可做必要的兼容协议扩展和独立计划生成。另须修复旧页面迟到覆盖新需求、历史预算复活和断连清除新草稿，并验证真实来源生命周期；不得以现有测试通过宣告完成。

## 9 真人验收（指挥代录）
