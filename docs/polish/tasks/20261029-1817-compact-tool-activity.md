# 工具调用改为紧凑行列表，过程标题显示当前阶段

- 编号：20261029-1817-compact-tool-activity
- 状态：待真人验收
- 创建：2026-10-29 18:17
- 执行前先读：[工作目录 README](../README.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md、AGENTS.md

## 1 用户反馈

> 在这个界面里面，其实也暴露了一些问题,就是我们在显示我们工具调用的列表当中，它每一个条目占的高度太高了，就导致它整个显示效率非常低。然后它其实没有必要以卡片式的形式去出现，它只要一行弄一个条目就可以，用户点击，然后可以查看这个工具调用返回的结果，对吧？我们把它过滤完成之后给用户。然后最上面那一行正在为你调研，你可以改成，目前我们在哪个阶段，你就改成哪个阶段就好了

截图：`output/polish/20261029-1817-compact-tool-activity/feedback-1.png`，2000×880，准备阶段空卡占据大面积空间，研究卡里面每条查询仍是两行。

## 2 现象与发生条件

正式规划工作区右侧 ThinkingChain：两列阶段卡、展开阶段横跨全宽、类别和查询主题分两行。顶部泛称“正在为你调研”，没有准确表达准备/每日路线/生成阶段。

## 3 根因

- `frontend/src/index.css:3603–3637` 给 workspace 阶段组设置两列卡片、圆角边框、132px 最小高度和大内边距；无内容的需求整理阶段也占大块空间。
- `frontend/src/features/chat/components/ThinkingChain.tsx:53–77` 的 ToolActivity 将类别和主题作为两个 block，再通过阶段卡展开才看到列表；需要浏览阶段卡和工具详情两个层级。
- `ThinkingChain.tsx:173` 只按 live/有无 steps/正文判断标题，所有有步骤的准备与研究阶段泛称“正在为你调研”。`agentStages.ts` 已覆盖原始节点名、中文显示名和补充轮次，`travelProgress.ts` 有现有阶段投影，应沿真实进度复用，不能按动画或时间猜测。
- `toolDisplay.ts` 和后端 `summarize_tool_result` 已形成安全的公开结果边界（INV-UI-003），应复用。

## 4 方案

目标状态：右侧展示紧凑、可扫描的行列表；工具每项一行，直接点击查看过滤后的返回摘要、预览及来源。顶部按真实当前阶段变化，终态准确。

必须做：

- 正式 workspace 过程区取消阶段卡片网格、132px 最小高度和无意义留白。可保留紧凑阶段分隔/标题及有增量里程碑，查询行默认直接可见，不需要先展开大阶段卡再找工具。
- 每个工具折叠条目在桌面保持单行：类别、可读查询主题、真实状态和详情提示。以约 40–48px 行高作为桌面密度目标；长主题可省略但点击后能读完整内容。手机保留可点区域、明确状态且无横向溢出，不强压长文本导致详情丢失。
- 每行有安全结果时可直接点击/键盘展开，详情保留公开摘要、结果预览、来源与有意义的失败/空结果/参考资料状态。无详情行不画无效展开按钮，不伪造结果。不要输出原始 JSON、技术载荷或把内部工具搜索查询当作原始技术字符串展示；优先复用已有展示过滤。
- 顶部展示实际当前阶段，如整理旅行需求、查找旅行资料、安排每天路线、生成完整计划。使用现有步骤/流/状态信号，覆盖中文 agent 名、原始节点名和后缀。并行研究不按最后一条工具完成事件任意跳阶段；返回前面重新整理的补充轮次可准确回退。
- 等待审批、取消中、已取消、中断、失败、完成分别准确，不把终态说成正在调研。不修改服务端真值，不因正文片段误报阶段完成。与同批统一工作区任务联动，审批时的标题/状态不冲突。
- 保留普通聊天里的过程查看、查询状态、防 JSON 泄露、来源链接、已完成内容和停止后不显示瞬时占位的现有回归。

执行者自己决定：平铺列表/紧凑阶段分组的具体组件边界、详情样式、阶段文案与投影复用方式。普通聊天模式可保留现有布局；workspace 必须达到行列表目标。

不许碰：后端/API/SSE、Run 事实和批准规则、真实模型/用户数据、交付内容和无关样式；不提交不推送。保留工作区既有改动。

## 5 停下来报告的情况

若已有公开事件缺失判定某阶段的必要信息，说明具体场景，使用真实中性文案，不伪造阶段或修改公开协议。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. workspace 无大阶段卡片和空白准备卡；工具一项一行，桌面正常折叠行约 40–48px，可直接展开结果。
2. 结果与来源经过现有安全过滤，原始 JSON/未知载荷不出现在界面；长查询展开可完整阅读，空结果/失败/参考资料状态准确，键盘可操作。
3. 准备、并行研究、路线、交付与终态的顶部标题准确；支持中文名、节点名及补充轮次。不能只把固定标题替换成另一个固定标题。
4. 320/390px 无溢出；左侧摘要/进度/扫光、停止与 reduced-motion 不回归。

### 6.2 必须运行的检查

frontend 下：

- `npm run type-check`
- `npm run test -- src/features/chat/model/agentStages.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/toolDisplay.test.ts`
- `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`

按行为更新 workspace 旧卡片断言，保留普通聊天用例；离线夹具覆盖单行行高/密度、长查询展开、结果/来源、阶段变化与终态。补充轮次和阶段判定若新增纯投影函数，加入有意义定向单测。复用实际组件和真实 SSE 呈现链，不调用模型。与统一工作区任务共享文件，由同一执行者顺序实现。

### 6.3 实屏证据（执行者提供）

2000×880：并行研究的紧凑列表、展开单项结果、路线与生成阶段标题；390×844：查询详情可用无溢出。保存到本任务 output 目录，附桌面折叠行高度的实际测量。

### 6.4 真人验收（用户操作）

1. 开始规划 → 右侧过程区每条工具调用紧凑显示，顶部随当前阶段更新。
2. 点击任一已完成查询 → 原位看到整理后的结果与来源；再点击收起。
3. 查看停止或失败的规划 → 顶部和条目状态准确，没有继续调研的提示。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 · pi 执行代理

- 改动摘要：workspace 过程区改为紧凑纵向行列表，取消两列阶段卡、132px 最小高度和大块空卡；阶段标题只占紧凑一行，工具查询直接可见，单行约 44px，有公开结果时可直接点击/键盘展开摘要、预览和来源。长查询在折叠时省略、展开后完整可读；无安全详情的行不显示展开控件。顶部标题改为真实阶段投影，覆盖整理需求、查找资料、安排路线、生成计划及等待审批、停止中、取消、中断、失败、完成；补充轮次可回退需求阶段，迟到的并行研究事件不会把已进入的路线阶段拉回。普通聊天仍保留原来的过程卡布局。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/features/chat/model/agentStages.ts`、`frontend/src/features/chat/model/agentStages.test.ts`、`frontend/src/features/chat/model/toolDisplay.ts`、`frontend/src/features/chat/model/toolDisplay.test.ts`、`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/research-progress.tsx`、`frontend/e2e/planner-intake.spec.ts`（旧固定标题断言改真实阶段）、`frontend/e2e/session-state.spec.ts`（workspace 行列表断言）；两份任务文档。
- 偏离方案及理由：复用现有 `researchGroups`/`ToolActivity`/`toolResultText`/`publicProgressText` 安全过滤，只给 `ToolDisplay` 增加未截断的 `fullSubject` 供展开阅读；阶段标题投影放在 `agentStages.ts` 纯函数中，避免按动画或时间猜测。普通聊天 `layout="default"` 保持原行为。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts src/features/chat/model/agentStages.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/toolDisplay.test.ts`：23/23 通过；新增阶段标题/中英文轮次与 `fullSubject` 单测。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`：13/13 通过；新增 workspace 密度用例实测桌面折叠行高 44px（断言 40–48px），展开长查询、来源、路线/生成标题、390px 无横向溢出。
  - `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1`：7/7 通过，旧“正在准备规划/正在为你调研”断言已改为真实阶段标题。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：19/19 通过，workspace 恢复研究时行列表直接可展开。
- 实屏证据：`output/polish/20261029-1817-compact-tool-activity/workspace-2000-compact-list.png`（折叠列表）、`workspace-2000-expanded-query.png`（长查询与来源）、`workspace-2000-route-stage.png`、`workspace-2000-delivery-stage.png`、`workspace-390-expanded-query.png`、`generation-2000-failed-expanded.png`、`generation-390-failed.png`、`generation-1440-active.png`。均为离线夹具/合成 SSE，不含真实 Provider 调用。
- 遗留问题或需要指挥决定的事：未运行真实付费 Provider 验证；离线夹具覆盖了阶段投影与视觉密度，真实并行研究/补充轮次的最终文案仍需在授权后做实 Provider 抽查。

### 第 2 轮 · 2026-10-29 · pi 执行代理

- 改动摘要：针对 R1/R2 返工。workspace 阶段分组头改为同一行容纳名称、状态、摘要和查询数，阶段头最小高度 44px；长摘要在桌面单行省略并通过 `title`/`aria-label` 保留完整可读途径；390px 下查询数留在首行、摘要换到第二行完整可读。清理连续重复的 `.research-panel-workspace .research-panel-body` padding 声明，合并为一条。`search_tools` 等 internal 工具不再从 query 提取 `global_place_search` 等内部标识作为 subject/fullSubject，只显示“整理规划”类别和安全结果摘要。普通聊天布局未改，工具行仍为 44px。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/features/chat/model/toolDisplay.ts`、`frontend/src/features/chat/model/toolDisplay.test.ts`、`frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx`、`frontend/src/index.css`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/research-progress.tsx`。
- 偏离方案及理由：未使用针对截图单句的黑名单，而是在 `subjectForKind` 的 `internal` 分支统一不产出查询主题；阶段摘要完整阅读使用原生 `title`/`aria-label`，避免为阶段头增加新的展开层级。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/agentStages.test.ts`：14/14 通过；新增 internal 工具不暴露内部标识的定向检查。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`：13/13 通过；新增阶段头 40–48px 密度断言、internal 行“整理规划”与安全摘要断言、无 `global_place_search` 断言。
- 实屏证据：已更新 `output/polish/20261029-1817-compact-tool-activity/workspace-2000-compact-list.png`（单行阶段头 + internal 安全行）、`workspace-390-expanded-query.png`（手机两行阶段头与展开详情）、`workspace-2000-expanded-query.png`、`workspace-2000-route-stage.png`、`workspace-2000-delivery-stage.png`。均为离线夹具，不含真实 Provider 调用。
- 遗留问题或需要指挥决定的事：无；真实 Provider 验证仍未运行，维持原说明。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 实屏与代码检查

- 结论：返工。工具行 44px、直接展开、安全结果与顶部阶段变化已实现；阶段分组标题仍是名称/摘要/查询数三行，单组头部约 80px，未达到第 7 节所称“一行”。截图已核对 `workspace-2000-compact-list.png` 和 `workspace-2000-expanded-query.png`。
- R1：workspace 分组头部压为紧凑一行（名称/状态/摘要/查询数按空间分配），摘要长时省略但有信息仍可读，手机按可读性处理；不隐藏真实异常或结果。保持工具 40–48px、无需先展开阶段、普通聊天不受影响。清理重复的 `.research-panel-workspace .research-panel-body` padding 声明。
- R2：`toolDisplay.ts` 把 `search_tools` 归为 internal，仍从 query 提取 `global_place_search 地点` 之类内部工具搜索文本作为 `fullSubject`，原截图即包含此形状。内部能力选择行应显示可读的整理规划标签/安全摘要，不把内部标识作为查询主题；不使用针对截图单句的黑名单。补一项对应形状的展示检查。
- 按最新文件定向复测 research-progress 和展示单测，更新同路径实屏并写本轮记录。

### 第 2 轮 · 2026-10-29 · 返工验收

- 结论：R1/R2 通过，转待真人验收。已查看更新的桌面紧凑列表、单项展开、路线/生成阶段标题与手机展开证据；阶段头和工具折叠行均为 44px，桌面同排名称/状态/摘要/计数，手机摘要自然换行，无大阶段卡和空白准备卡。长查询展开后可读，来源仍可点击。
- 已核对 internal 类别不再生成来自能力搜索参数的主题，使用已有安全结果与可读类别；未按截图单句建立黑名单。重复的 workspace panel-body padding 已合并，普通聊天仍用原布局。停止后瞬时占位过滤保留。
- 指挥独立运行 `JP_COMPONENT_E2E=1 JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts e2e/session-state.spec.ts --grep 'workspace 工具行密度|restores staged research' --workers=1 --output=../output/polish/20261029-1817-compact-tool-activity/commander-checks`：2 passed。实际验证了阶段头/工具行 40–48px、内部工具标识不出现、长查询及来源、路线/生成标题、手机无溢出与历史研究恢复。
- 已查看指挥复测的完整工作台 `commander-checks/session-state-restores-sta-f0b6f-tted-tool-calls-and-results-chromium/desktop-generation-research.png`；执行者返工 type-check、14 项相关单测、13 项研究进度 e2e 均通过，`git diff --check` 通过。
- 本轮均为离线展示与事件验证，未调用真实模型或外部 Provider，未修改真实会话。真人操作按第 6.4 节进行。

## 9 真人验收（指挥代录）
