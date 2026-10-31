# 工作过程改为连续动态，所有工具使用中文别名与可核查详情

- 编号：20261029-2325-work-activity-feed
- 状态：待真人验收
- 创建：2026-10-29 23:25
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、frontend/README.md、frontend/e2e/README.md、docs/invariants.md 的 INV-UI-003、docs/architecture/overview.md、[本轮调研](../references/20261029-ai-work-activity.md)

## 1 用户反馈

> 目前的思维链的显示非常的不好看，目前主流的产品，ChatGPT 等等的这些，它都是如何来做这个过程展示的？你调研一下。然后把这个界面重新设计一下，不要以这种卡片的形式来展现。
>
> 我们需要给所有激活的工具起一个统一的、易懂的中文别名，而不是把这些内部名称暴露出来。点击工具查看的时候，显示工具的显示名称、输入和过滤后的结果。有摘要就显示摘要，如果是多条结果，显示“返回 X 条结果”。

截图：`output/polish/20261029-2325-work-activity-feed/feedback-1.png`。右侧仍是一个大面积有边框、圆角和阴影的面板，阶段与工具行形成多层框架；“激活工具：global_place_search、knowledge_search”以及 brave／firecrawl／tavily 等内部名直接出现在结果行。页面处于 Run 已完成、正式结果恢复中。

相关历史：`20261029-1817-compact-tool-activity` 已通过代码验收但仍待真人验收。本任务是本轮新反馈，需在其现有紧凑行基础上重做信息层级，不回退已完成的阶段判定和安全过滤。

## 2 现象与发生条件

正式规划工作区右侧 `ThinkingChain layout="workspace"`：外层面板像一张大卡，阶段组重复图标、状态、摘要和查询数，工具结果挤在宽行里，完成态仍占据大块卡片。所有实时和历史工具步骤都可能受影响，尤其是 `search_tools` 能力选择行；普通聊天也复用同一展示模型，别名不能只修一个截图状态。桌面截图约 2000×880 CSS px，手机布局需同时保证可读。

## 3 根因

- `frontend/src/index.css:3641–3807` 给 `.research-panel-workspace` 外层边框、圆角、阴影，再给标题、阶段和查询增加多层分隔；`ThinkingChain.tsx:88–145` 仍按 Agent 卡组织内容。虽然旧任务已压缩行高，信息架构仍是“面板卡 → 阶段卡头 → 工具行”，不是连续工作动态。
- `ThinkingChain.tsx:60–82` 只在存在“额外摘要或预览”时允许展开，并把摘要或主题当行标题；没有稳定的“工具显示名／输入／结果”详情结构。只有结果、没有预览的工具可能无法点击，输入也没有独立可读区域。
- `frontend/src/features/chat/model/toolDisplay.ts` 已有 `describeToolStep`、中文类别、参数解析和 `toolResultText`，应作为唯一展示投影继续复用；但 `toolResultText` 目前只拦截 JSON 类载荷，纯文本中的内部标识会原样通过。
- 截图中的内部名有明确上游：`backend/travel_agent/tools/react.py:379–396` 给 `search_tools` 生成“激活工具：内部名列表”，`backend/travel_agent/conversation/chat/tool_events.py:102–121` 的 `public_text` 会保留这类自然语言，前端又在 `ThinkingChain.tsx:60` 把它作为 headline。只改行首类别不能消除这些名字。
- `result_preview` 是白名单且最多 6 条（`backend/travel_agent/tools/display.py`），不是完整结果数组；总数只能取公开摘要中的明确计数，不能用预览长度伪造。

## 4 方案

目标状态：右侧成为一个克制、连续、可扫描的工作动态区。用户默认看到真实阶段和每次公开行动；点击任一工具行，原位看到中文显示名、可读输入和过滤后的结果／来源。实时与历史、工作区与普通聊天都使用同一中文别名和安全投影，不展示原始思维链或内部载荷。

必须做：

- **去掉卡片化信息架构。** workspace 不再显示大面积外框卡片、卡片套卡片、每组重复的大图标与无意义状态堆叠。用连续动态列表和轻量阶段分隔组织；内容列有合理阅读宽度，不把少量文字拉满超宽右栏。保留真实阶段标题、运行／停止／失败／完成状态和现有左侧摘要进度。
- **每行只承担一次行动。** 折叠行包含状态、统一中文显示名、简短主题或结果概况和展开提示；桌面保持紧凑单行，长文本省略但详情完整。阶段分组可以保留，但不能要求先展开阶段再找工具，也不能重复显示同一句摘要。
- **每个工具都有可点击／键盘展开的详情。** 详情固定呈现“工具／输入／结果”三个清晰区域；没有可公开输入或结果时使用中性中文空状态，不能因此变成不可点击，也不能编造。运行中只显示真实输入和进行中状态，不提前写结果。
- **统一中文别名。** 已知工具用动作导向名称，例如地点搜索、知识库检索、网页搜索、路线查询、天气查询、班次查询、汇率换算、整理规划。`global_place_search` 在实际调用行与 `search_tools` 的激活摘要中必须得到同一个名字。未知或新 MCP 工具回退到可信中文类别（如查询旅行信息、处理旅行信息），严禁把 `toolName`、provider 名或下划线标识作为显示兜底。
- **处理激活摘要，而非只改标题。** 对 `search_tools` 的“激活工具：…”结果做语义化展示投影，把内部名映射成中文能力列表或归纳；截图中的 global／knowledge／brave／firecrawl／free_web／tavily 名称在折叠、展开、`title`、aria 文案中均不得出现。其内部 query 也不作为旅行者输入展示。按工具语义处理整类情况，不建立只匹配截图单句的黑名单。
- **结果分层且计数真实。** 有公开摘要就显示摘要；有多条结果且公开摘要给出明确总数时，显示“返回 X 条结果”，并保留下方白名单预览与来源。总数不得取 `resultPreview.length`。无法确认总数时只显示摘要或“已返回结果”，不猜数。空结果、失败、降级、参考资料沿用真实状态。
- **只使用公开安全字段。** 输入从现有 `args_summary` 解析为中文标签和已知可读值；结果来自 `toolResultText` 对应的安全投影与 `result_preview`。不直接渲染原始 args JSON、`sanitized_result`、内部异常、合同字段或原始思维链。继续遵守 INV-UI-003，历史会话也同样过滤。
- **动态更新稳定。** 新 SSE 到达不随意收起用户已打开的工具详情，不把阶段跳回旧状态；展开详情不会触发行位置的大幅跳动或页面横向溢出。若提供自动跟随，只在用户仍位于底部时启用，上翻查看历史后不得强制拉回。动画沿用现有短时／reduced-motion 规则，不添加无依据的参考站动效。
- 普通聊天可保留既有较完整的过程外观，但中文别名、内部名过滤、计数与详情安全必须共享，不能形成第二套映射。

执行者自己决定：连续动态的具体组件边界、是否保留细分组、内容列宽与间距、详情采用原生 disclosure 或按钮区域、各已知工具的最终中文名，以及纯函数拆分方式。优先扩展现有 `toolDisplay` 与 `ThinkingChain`，不新建平行数据通道。

不许碰：后端、API/SSE 字段与事件顺序、Run／审批事实、工具执行与 Provider、原始结果内容、真实用户数据、行程和地图、无关页面；不提交不推送。若认为必须修改后端才能满足全部别名要求，先停止并提供不能被现有公开字段覆盖的具体例子，不自行扩合同。

## 5 停下来报告的情况

- 发现某类公开展示必须依赖当前 SSE／历史字段之外的原始数据，或无法在不暴露内部名的情况下解析；记录具体事件形状后停止。
- 实际根因超出上述工具展示投影，或需要修改后端摘要、公开协议、Run 事实才能完成；不要以新增多个正则兜底继续。
- 与 `20261029-2325-workspace-followup-composer` 共用面板；若并行执行导致所有权冲突，先协调，由同一执行者顺序完成最稳妥。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. workspace 过程区是连续动态而非外层大卡／嵌套阶段卡；工具折叠行紧凑可扫描，2000px 下没有超宽稀疏阅读列，320／390px 下无横向溢出。
2. 每个工具行均可通过点击和键盘展开，详情显示统一中文工具名、可读输入、结果摘要／预览／来源及真实状态；无公开输入或结果时有中性空状态，无伪造内容。
3. 对截图两条激活摘要及普通工具调用，`global_place_search`、`knowledge_search`、`brave_*`、`firecrawl_*`、`free_web_search`、`tavily_search` 等内部名不出现在可见文本、title 或无障碍名称中；同一工具在各入口别名一致，未知工具也有中文兜底。
4. “找到 4 个结果：…”且只有 2 条预览的夹具显示“返回 4 条结果”而非 2；摘要仍可读。无明确总数时不显示虚构计数。原始 JSON、机器载荷、内部 query 与异常文本仍被拦截。
5. 实时展开状态在后续事件到达时保持，阶段和运行／完成／停止状态不回归；用户上翻后不被新事件强制拉回底部。历史恢复使用同一展示结果，普通聊天无功能回归。

### 6.2 必须运行的检查

在 frontend 下：

- `npm run type-check`
- `npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts`
- `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '研究|工具|research|tool' --workers=1`

扩展现有真实组件／合成 SSE 夹具，至少覆盖截图中的两种激活摘要、已知与未知工具、只有摘要无预览、2 条预览但真实总数 4、无输入／无结果、JSON 防泄露、长输入完整展开、键盘操作和后续事件保持展开。不得调用模型或真实 Provider。

### 6.3 实屏证据（执行者提供）

- 2000×880：运行中的连续动态、完成后的连续动态；各一张，能看到非卡片层级与合理阅读列。
- 2000×880：展开一个地点搜索，显示中文工具名、输入、“返回 4 条结果”、摘要和白名单预览；再展开一个 `search_tools`，证明激活摘要无内部名。
- 390×844：长输入与结果展开、中文别名、无横向溢出。
- 保存到 `output/polish/20261029-2325-work-activity-feed/`；附关键桌面行高、内容列宽和横向溢出测量。

### 6.4 真人验收（用户操作）

1. 开始或恢复一次规划 → 右侧像连续工作动态，不再是一层层卡片；当前阶段和每项行动容易扫读。
2. 查看“整理规划／激活能力”及任一实际工具 → 只看到中文别名，看不到 global、brave、tavily 等内部名。
3. 点击工具行 → 看到工具显示名、输入和过滤后的结果；多条结果有真实“返回 X 条结果”，来源可打开，再点击可收起。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 00:14 · pi／Claude

- 改动摘要：workspace 过程区去掉外层面板边框、圆角、阴影与嵌套卡片观感，改为限宽连续动态列表和轻量阶段分隔；每个工具行都可用鼠标或键盘展开，详情固定为“工具／输入／结果”，无公开输入或结果时显示中性空状态。统一中文动作别名，`search_tools` 的“激活工具：…”按工具语义投影为中文能力列表，内部能力 query 不作为输入展示；普通纯文本摘要中的内部工具标识也转成中文类别。结果计数只从公开摘要中的明确总数提取，例如 2 条预览、摘要写明 4 条时显示“返回 4 条结果”；继续使用 `toolResultText` 与白名单预览，拦截 JSON、内部异常和原始载荷。用户已展开的工具用父级状态保持，后续状态事件不会收起详情。保留并集成工作区已有的恢复提示、会话状态测试与其他任务 CSS 改动。
- 改动文件：`frontend/src/features/chat/model/toolDisplay.ts`、`frontend/src/features/chat/model/toolDisplay.test.ts`、`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/index.css`、`frontend/e2e/fixtures/research-progress.tsx`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/session-state.spec.ts`。`frontend/src/app/layout/TripWorkspaceShell.tsx` 的恢复提示改动保持原样。
- 偏离方案及理由：无
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts`：3 个文件、24 项测试全部通过。新增覆盖中文别名一致性与未知工具兜底、两类激活摘要内部名过滤、普通摘要内部标识替换、明确总数解析、内部 query 不作为输入。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`：14 项通过；覆盖 320／390／1440／2000px、两种激活摘要、已知与未知工具、仅摘要无预览、2 条预览但真实总数 4、无输入无结果、JSON 防泄露、长输入、键盘展开、后续事件保持展开、阶段标题与横向溢出。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '研究|工具|research|tool' --workers=1`：1 项通过（历史恢复的调研工具详情）。
  - 附加运行完整 `session-state.spec.ts`：31 项通过、1 项失败；失败项为恢复提示浮层拦截面板标题点击（`浮动的恢复提示不改变工作区几何、滚动位置与键盘焦点`），不属于本任务第 6.2 节命令，也未改动该恢复提示逻辑。
- 实屏证据：`output/polish/20261029-2325-work-activity-feed/`：`workspace-2000-running-activity.png`、`workspace-2000-completed-activity.png`、`workspace-2000-expanded-place.png`、`workspace-2000-expanded-activation.png`、`workspace-390-expanded-query.png`、`desktop-measurements.json`。测量结果：桌面阶段行高 32px、工具折叠行高 42px、内容列宽 1040px、无边框与阴影、横向溢出 0；390px 横向溢出 0。
- 遗留问题或需要指挥决定的事：第 6.2 节指定检查均通过。附加完整 `session-state.spec.ts` 的恢复提示浮层点击冲突属于另一任务的提示层行为，建议交回对应恢复提示任务或由指挥判断，不在本任务内扩大修改。

### 第 2 轮 · 2026-10-30 00:43 · pi／GPT-5.5

- 改动摘要：按指挥验收 R1 修复公开输入绕过安全投影的问题。工具输入值和由其派生的折叠主题统一经过 `publicProgressText`、技术字段／异常文本识别及内部标识中文别名替换；机器载荷、合同字段、异常堆栈和内部工具／Provider 名不再出现在“输入”或折叠行，正常旅行查询与长查询保持完整，未清空普通输入。补充机器载荷、合同字段、内部标识、异常文本和长查询的模型断言，并在真实组件夹具中加入对应工具行，验证输入详情无泄露、内部标识转为中文且长输入仍可展开阅读。
- 改动文件：`frontend/src/features/chat/model/toolDisplay.ts`、`frontend/src/features/chat/model/toolDisplay.test.ts`、`frontend/e2e/fixtures/research-progress.tsx`、`frontend/e2e/research-progress.spec.ts`。
- 偏离方案及理由：无（输入值同源的折叠主题一并纳入同一投影，避免同一参数在折叠行继续泄露）。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts`：3 个文件、25 项测试全部通过；新增断言覆盖机器载荷、合同字段、内部标识、异常堆栈、正常及长查询。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`：14 项全部通过；真实组件检查覆盖机器载荷输入、合同字段输入、内部标识转换、异常文本输入、正常／长输入、既有激活摘要、真实计数、JSON 防泄露、键盘展开和后续事件保持展开。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '研究|工具|research|tool' --workers=1`：1 项通过（历史恢复的调研工具详情）。
  - 完整离线回归 `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：40 项全部通过，包含恢复提示、后续补充输入、会话恢复与工具详情；上一轮恢复提示浮层点击冲突未再出现。
- 实屏证据：沿用 `output/polish/20261029-2325-work-activity-feed/` 的第 1 轮实屏与测量；本轮组件回归重跑并更新相关截图，未新增需单独保存的布局证据。
- 遗留问题或需要指挥决定的事：无。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-30 · 代码与实屏检查

- 结论：返工。连续动态、中文别名、真实结果计数、工具三段详情和实屏布局符合方向；发现公开输入还有一条未经过滤的渲染路径。
- R1：`ToolActivity` 的 `display.inputs` 值直接写入 `dd`，未经过 `publicProgressText` 或等价安全投影。工具参数中的查询值若含 JSON／合同字段、内部工具标识或异常文本，会在“输入”区域绕过结果摘要的防泄露边界。将公开输入纳入同一展示过滤，保留正常旅行查询与长文本，补查询值为机器载荷和内部标识的定向单测及真实组件检查；不得简单清空所有输入或只在 DOM 上覆盖原文。
- 修复后重跑本任务 6.2 检查，并配合完整离线 session-state 回归，确认恢复提示返工没有破坏工具详情。

### 第 2 轮 · 2026-10-30 · R1 返工验收

- 结论：通过，转待真人验收。工具输入与同源折叠主题已统一经过公开投影，机器载荷、合同字段、技术异常和内部标识不会绕过“输入”区域；正常旅行查询及长文本仍完整可读。
- 已查看运行／完成态连续动态、地点搜索与激活摘要展开、390px 长输入证据。中文别名、真实结果总数、三段详情、键盘展开和安全来源符合第 6 节，无卡片套卡片或预览数冒充总数。
- 指挥独立运行 type-check、相关 21 项单测和 research-progress 14/14 通过；执行者完整离线 session-state 40/40 通过。未改后端、API/SSE 或 Run 事实。

## 9 真人验收（指挥代录）
