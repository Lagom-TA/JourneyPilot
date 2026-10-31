# 连接恢复提示改为不推挤工作区的上层浮框

- 编号：20261029-2325-floating-recovery-notice
- 状态：待真人验收
- 创建：2026-10-29 23:25
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、frontend/README.md、frontend/e2e/README.md、[本轮调研](../references/20261029-ai-work-activity.md)

## 1 用户反馈

> 截图顶部这个框，应该是一个上层浮框，这个框用来提示就行了，不要占据顶部高度。

截图：`output/polish/20261029-2325-floating-recovery-notice/feedback-1.png`（原始 4096×1804）。正式规划工作区已完成、正在恢复已保存结果；“连接中断，正在从已保存的旅行结果恢复。重试”位于全局导航下方，整个提示区域把工作区向下推。

## 2 现象与发生条件

`TripWorkspaceShell` 的 `deliveryBundleLoadState` 为 `error` 或 `loading` 时出现提示。错误文案可由 `useDeliveryEventRecovery` 在已有正式结果、连续同步失败后写入。提示包含恢复状态和“重试”按钮；恢复期间用户仍应能查看已有过程或旅行结果。截图视口约 2000×880 CSS px，浏览器类型未知；布局根因可由代码确认。

## 3 根因

- `frontend/src/app/layout/TripWorkspaceShell.tsx:63–77` 把提示放在根 flex 列的普通文档流中，外层还是 `flex-none`；`trip-workspace-layout` 在 `:79` 才作为下一个 `flex-1` 区域出现，因此提示自身高度和 padding 必然压缩工作区高度。
- 提示已有独立边框、背景和阴影，不需要再占一个通栏布局层。恢复状态与重试逻辑分别在 `useDeliveryEventRecovery.ts:176–184` 和 `TripWorkspaceShell.tsx:23–40`，本次问题只在呈现位置，不需要改恢复算法。
- [Component Gallery 的 Toast 定义](https://component.gallery/components/toast/)明确将其描述为位于其他内容之上的层；本项目提示有持续状态和动作，可借鉴非模态浮层，不应擅自自动消失。

## 4 方案

目标状态：提示以工作区顶部居中的小型浮框出现，覆盖在内容上方；出现、文案变化和消失都不改变工作区的尺寸或滚动位置。已有内容保持可读、可操作，重试行为不变。

必须做：

- 将 loading／error 提示移出普通布局流，锚定现有工作区容器顶部；使用足够且符合现有层级的 z-index，不被地图、浮动日程面板或过程面板遮住，也不压住全局导航和模态框。
- 非模态、无全屏遮罩、无焦点陷阱。只有浮框本身接收指针事件，浮框外的工作区仍可点击；出现时不主动抢焦点。
- 保留现有状态真值、错误／加载文案、重试按钮、loading 禁用以及 Run／session 归属检查。恢复成功后仍由原有状态清除提示，不新增独立定时器或本地“假成功”。
- 桌面浮框紧凑、内容一行优先；390px 下允许文案换行，重试保持可见可点，无横向溢出。键盘可到达重试，读屏状态通知不因改定位而丢失。
- 不通过给工作区加固定顶部 padding 来“补偿”，否则仍然占高；不用 `visibility` 隐藏溢出掩盖布局问题。

执行者自己决定：浮框放在 shell 的哪一相对定位层、精确宽度／间距／阴影、是否抽成小组件，以及 loading 使用 `status` 还是沿用现有提醒语义。优先最小改动。

不许碰：恢复轮询、事件序号、Bundle 确认与重试请求合同、Run 状态、后端/API/SSE、真实用户数据、无关页面；不提交不推送。

## 5 停下来报告的情况

若现有层叠上下文使浮框无法在不改无关地图／模态层级的情况下正确显示，记录具体元素和 z-index 冲突后停止，不通过全局提高所有层级绕过。若需要改变恢复状态机才能满足本任务，也说明证据后停止。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 同一 Run 内容下，提示从无到有时 `trip-workspace-layout` 的宽高和顶部位置不变，工作区滚动位置不跳；提示计算样式为脱离文档流的定位。
2. 浮框位于工作区上方且非模态；框外原有按钮可用，重试仍调用原 `retryCurrentBundle`，loading 时不重复提交。
3. 2000px 与 390px 均无横向溢出，长文案和按钮不互相挤压；键盘与读屏名称完整，出现时不抢焦点。
4. 未改变恢复、重试、Bundle／Run 身份与审批合同。

### 6.2 必须运行的检查

在 frontend 下：

- `npm run type-check`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '恢复提示|recovery notice' --workers=1`

在现有离线会话夹具中增加 loading／error 提示状态，测量提示出现前后的工作区几何与滚动位置，验证重试请求和框外交互；不调用模型或外部 Provider。若采用其他现有套件承载同一检查，记录实际命令，不能用无断言截图代替行为验证。

### 6.3 实屏证据（执行者提供）

2000×880：与反馈相同的“已完成、恢复正式结果”状态，浮框不推挤左右工作区；390×844：长提示换行、重试可见。保存到 `output/polish/20261029-2325-floating-recovery-notice/`，并附一组提示前后工作区矩形与滚动位置测量。

### 6.4 真人验收（用户操作）

1. 在规划结果恢复或连接中断时出现提示 → 提示浮在工作区上方，左右内容高度和位置完全不动。
2. 点击浮框外的过程条目，再点击“重试” → 原交互仍可用，重试期间不会反复提交，恢复后提示消失。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 00:02 · pi / deepseek-v4.1-flash

- 改动摘要：把 loading／error 恢复提示从 shell 的普通 flex 列移出，改为锚定工作区外壳顶部居中的非模态浮框（`position: absolute`，`top`／`width`／`z-index` 由新增的 `.recovery-notice` 统一定义）。桌面单行紧凑浮框（`min(46rem, 100% - 48px)`），390px 下窄边距内换行；只有浮框本体接收指针事件，没有全屏遮罩、没有焦点陷阱、出现时不抢焦点。状态真值、loading／error 文案、`重试`按钮、loading 禁用与 `retryCurrentBundle` 的 Run／session 校验、Bundle 确认逻辑全部保持原样，提示仍由原状态清除。层级取舍：移动端 `z-index: 1050`（高于地图顶栏 `1000`／地图底部的浮动日程按钮，低于 Sheet `1100`、导航抽屉 `1110–1120` 与模态框 `1200`，打开抽屉或画布 Sheet 时不会压住它们）；桌面 `z-index: 1150`（高于桌面行程浮面板 `1100`，仍低于阅读版层 `1200`、Sheet 与模态框 `1200`）。没有给工作区加补偿 padding，也没有用 `visibility` 掩盖溢出。
- 改动文件：`frontend/src/app/layout/TripWorkspaceShell.tsx`（提示移出布局流并在 shell 根上加 `relative`，新增 `data-testid="delivery-recovery-notice"`／消息节点 testid）、`frontend/src/index.css`（`.recovery-notice` 定位、宽度与响应式层级）、`frontend/e2e/session-state.spec.ts`（离线夹具新增 `notice`／`noticeRestoreError` 场景与 `triggerRecoveryNotice`／`setNoticeBundle`／`restoreNoticeEvents` 控制，新增 3 个恢复提示用例）。
- 偏离方案及理由：无功能偏离。补充说明两点实现选择：① 浮框放在 shell 根（工作区外壳）内、`trip-workspace-layout` 之后，而不是给工作区容器单独建 `isolation` 栈上下文，避免把 Sheet／模态框一起限制在壳内；② 手机端宽度用 `100% - 48px`，既保持“小型浮框”的边距，也让 19 字的长提示在 390px 真实换行（未改文案）。
- 实际运行的检查与结果：
  - `cd frontend && npm run type-check` → 通过（tsc 两个 project 均无报错）。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '恢复提示|recovery notice' --workers=1` → 3 passed（几何／滚动／焦点、桌面＋手机非模态与重试单次提交、已完成规划恢复失败三例）。
  - 额外回归：`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts` → 32 passed（含原有恢复、地图、Sheet、模态框、日期选择器等用例，无回归）。
  - 额外回归：`cd frontend && npm run test` → 16 files / 95 tests passed。
- 实屏证据：`output/polish/20261029-2325-floating-recovery-notice/desktop-2000-completed-recovery-error.png`（2000×880，已完成规划面板＋恢复正式结果失败浮框）、`desktop-2000-completed-recovery-notice.png`、`desktop-2000-loading-notice.png`、`phone-390-recovery-notice.png`（390×844，长文案换行、重试可见可点）、`desktop-scroll-before-notice.png`／`desktop-scroll-during-notice.png`（真实滚动位置对照），测量数据见 `desktop-geometry.json`（提示前后 `trip-workspace-layout` 矩形完全一致，`2000×560` 下滚动容器 `scrollTop` 240 → 240；浮框 `position: absolute`、z-index 1150）、`desktop-completed-geometry.json`（2000×880 已完成态工作区 height 816 = 880 − 64 顶栏，未因浮框变矮）、`phone-geometry.json`（390×844 工作区 height 788 = 844 − 56，消息两行高 40px、重试按钮完整落在浮框内、无横向溢出，z-index 1050 且低于导航抽屉）。
- 遗留问题或需要指挥决定的事：① 离线夹具无法在不调用真实模型／不驱动真实 SSE 交付的前提下复现“SSE 完成后断线”，因此 2000×880 的“已完成”证据走恢复失败路径（提示文案为“暂时无法加载这趟旅行的正式结果，请稍后重试。”）；“提示从无到有”的前后对照测量用同一 Run 的“规划中→恢复正式结果”路径完成，几何与滚动结论一致。② 桌面 1024–1439px 宽度下若在已交付视图里触发提示，浮框（1150）会盖住左侧行程浮面板（1100）的顶部边缘而不是被其遮住，符合“不被浮动面板遮住”的要求；若指挥希望改为让出行程面板区域可再定。

### 第 2 轮 · 2026-10-30 00:42 · pi / deepseek-v4.1-flash（返工 R1）

- 改动摘要：只修 R1 的指针拦截。恢复提示容器继续保持覆盖定位，但改为 `pointer-events: none`，非交互文案区域不再接收指针事件，点击直接落到下方工作区；仅 `.recovery-notice > button` 恢复 `pointer-events: auto`，重试按钮保持可点。重试按钮仍在 DOM 中正常可聚焦，未加 `tabindex`、未改键盘顺序，提示出现时也不抢焦点。未使用 `force` 点击、未删除或放宽原有“提示下过程标题可展开”的断言；反之在夹具测量中新增 `pointerEvents`／`retryPointerEvents` 字段并要求分别为 `none`／`auto`，让点击穿透成为显式断言。恢复状态真值、轮询、Bundle 确认与重试合同、Run／session 校验、文案与层级均未改动。
- 改动文件：`frontend/src/index.css`（`.recovery-notice` 增加 `pointer-events: none`，新增 `.recovery-notice > button { pointer-events: auto; }`）、`frontend/e2e/session-state.spec.ts`（`recoveryNoticeFacts` 记录指针事件，恢复提示几何用例与桌面／手机用例新增对应断言；其余场景与断言原样保留）。
- 偏离方案及理由：无。仅按“非交互内容不阻断工作区、重试保持指针／键盘可用”的最小改动处理，未调整浮框位置、尺寸或 z-index。
- 实际运行的检查与结果：
  - `cd frontend && npm run type-check` → 通过（两个 tsc project 均无报错）。
  - `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep '恢复提示|recovery notice' --workers=1` → 3 passed（含 R1 复现场景：2000×560 下提示覆盖过程标题时，原 `.click()` 不再被 `.recovery-notice intercepts pointer events` 拦截，展开成功；桌面／手机非模态与重试单次提交；已完成规划恢复失败）。
  - `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1` → 40 passed（完整离线 session-state 套件，含恢复、后续输入框、研究过程、地图、Sheet、模态框与日期选择器，无回归）。
  - 全部测试仅使用 127.0.0.1:8088 的现有 Vite 服务与离线夹具，未调用模型或真实 Provider，未读写真实用户数据。
- 实屏证据：同目录截图已由本轮定向用例重新生成并在 2000×880 与 390×844 复核：`desktop-2000-completed-recovery-notice.png`、`desktop-2000-completed-recovery-error.png`、`desktop-2000-loading-notice.png`、`phone-390-recovery-notice.png`、`desktop-scroll-before-notice.png`／`desktop-scroll-during-notice.png`。测量文件同步刷新：`desktop-geometry.json` 记录 `pointerEvents: none`、`retryPointerEvents: auto`、2000×560 提示前后工作区矩形一致（y 64、height 496）、`scrollTop` 240 → 240；`phone-geometry.json` 记录 390px 下重试按钮完整可见、无横向溢出；`desktop-completed-geometry.json` 记录 2000×880 工作区 height 816 未被浮框压缩。
- 遗留问题或需要指挥决定的事：① 按 R1 要求，点击穿透后提示自身背景／边框区域不再拦截指针，视觉上仍是浮框但空白处等价于“穿透”；如果指挥希望提示文案可选中复制，需要另行决定是否给文案区单独放开指针事件。② 第 1 轮已记录的离线夹具限制仍在：2000×880“已完成”证据走恢复失败路径，不驱动真实 SSE 断线。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-30 · 代码、实屏与回归检查

- 结论：返工。浮层定位、工作区几何、滚动和桌面／手机截图符合方案，但完整链路存在真实点击冲突。
- R1：指挥独立复现 `浮动的恢复提示不改变工作区几何、滚动位置与键盘焦点`，在 2000×560 下提示覆盖过程标题并拦截点击，Playwright 明确报告 `.recovery-notice` intercepts pointer events。提示出现时其覆盖下的过程标题仍必须可操作；非交互提示区域不得阻断下方工作区，重试按钮保持可点、键盘可达，不能通过强制点击或删除该断言验收。修复后运行恢复提示定向用例及完整离线 session-state 回归，更新实屏证据。
- 证据：`output/polish/20261029-2325-floating-recovery-notice/commander-before-rework/`。首次从仓库根误运行 Playwright 导致测试加载错误，随后在 frontend 下使用项目依赖复现上述产品失败；加载错误不计为产品回归。

### 第 2 轮 · 2026-10-30 · R1 返工验收

- 结论：通过，转待真人验收。非交互提示区已允许点击穿透，只有重试按钮接收指针操作；2000×560 下原失败的过程标题点击现在正常展开，未强制点击或削弱断言。提示出现前后工作区矩形与 `scrollTop=240` 完全不变，重试仍保持键盘可达和单次请求。
- 已复核更新的桌面／手机实屏与几何 JSON，确认 `pointer-events: none`／重试 `auto`、无横向溢出、层级及焦点行为符合方案。执行者恢复提示定向 3/3、完整离线 session-state 40/40 通过；指挥后续独立类型检查、相关单测及完整回归中的恢复提示用例也通过。

## 9 真人验收（指挥代录）
