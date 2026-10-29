# 首个目的地全宽常驻，已选地点使用可排序的小块

- 编号：20261029-1252-destination-tokens
- 状态：待真人验收
- 创建：2026-10-29 12:52
- 执行前先读：[工作目录 README](../README.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md、backend/tests/README.md

## 1 用户反馈

> 关于添加目的地这一方面，我们最多是添加5个目的地，之后我们默认是一个目的地，就是现在这个样子，但是如果他点击了添加目的地，那我们就应该加入更多的选项，当用户点击添加目的地之后，我们这个输入框就会变形。用户每添加一个目的地，那它实际上就是占据一个小块，放在这个输入框里面。
> 用户每点击一次添加目的地，我们就会让用户进行搜索，他点击这个输入框就能加入更多的目的地。然后如果要想删除的话，他可以直接退格。或者说是长按，然后去调整左右的顺序，因为它是一横排排列的。
> 当目的地已经满了情况下，就是满了5个，那我们这个添加目的地的这个按钮就会改变，变成这个最多5个目的地这几个字。其实这里面的交互比较有讲究，我觉得我们还可以再讨论一下。

截图：output/polish/20261029-1252-destination-tokens/feedback-1.png。以下微交互按常规可撤回方案实现，最终交用户体验讨论。

2026-10-29 真人反馈以第 9 节最新原话为准。最新要求补正首站与新增的关系：初始必须保留一个全宽首站输入，右侧为“新增目的地”；已选目的地恢复紧凑小块，空间不足自然换行，后续新增搜索在下方展开。第 2–6 节为当前方案，历史反馈和执行记录保留。

## 2 现象与发生条件

首页“按条件规划”的“去哪里”区域在尚未选站时，左侧直接显示“关闭新增”，搜索框在右侧；第一站也能被收起。选站后每站变成占满整行的编号列表，和用户要求的一站一个小块不符。首页卡内需求确认与恢复草稿也共用该组件。本轮没有新增截图。

## 3 根因

- `frontend/src/features/travel/components/planning/DestinationTokenField.tsx:263–266、312、380–397、502–609` 将“尚无已确认站点”直接等同于新增区 `open=true`；按钮文案和关闭动作只判断 `open`，未区分首个必需输入与可选新增。初始因此显示“关闭新增”，点击后可让零站状态连输入也没有。
- `frontend/src/index.css:1259–1272` 对零站强制横排，却保留 DOM 中按钮在搜索框之前的顺序，使关闭按钮位于输入左侧；`:1274–1290` 将已选容器写成纵向列、每个 token 固定 `width:100%`，变成整行列表。
- `DestinationTokenField.tsx:432–451` 仅按纵坐标寻找排序目标，与恢复紧凑小块和自动换行后的二维排列不符。
- 上轮方案和验收只要求“首站入口可发现”，把首站选择后的表现交给执行者，没有约束首站始终可编辑以及初始按钮状态；这属于方案缺漏，不能只替换按钮文案。

## 4 方案

目标状态：首屏始终有一个占满目的地区域的基础输入，右侧提供“新增目的地”。确认地点后以紧凑小块承载每一站，支持拖动和删除；空间不足自然换行，保留此前下方单个新增搜索区的交互。

必须做：

- 区分首站基础输入与后续新增开关。零站时首站输入常驻，目的地区域全宽，新增按钮位于右侧且显示“新增目的地”；此时点击按钮只聚焦首站输入，不得关闭、隐藏它或凭空确认地点。
- 选好首站后显示紧凑地点小块，右侧保留新增入口；每站独立可删除、可排序，不再强制每站占满整行或显示大段编号。小块在同一容器中自然换行，不依赖横向滚动查看全部地点。
- 有已选站点时点击“新增目的地”，在下方展开唯一新增搜索并聚焦，按钮才切为“关闭新增”；关闭只收起额外搜索，保留已选小块。不能因首站默认可见就显示“关闭新增”。使用正确的 aria-expanded/aria-controls。
- 删除最后一个已选站后，恢复全宽首站输入及“新增目的地”。至少保留一个可编辑目的地入口；真正的地点仍须由用户从候选中确认，无目的地不能提交，不用虚构地点或伪造 PlaceIdentity 满足 UI。
- 鼠标、真实触屏把手拖动及键盘排序适配同排和换行后的排列；根据实际横纵位置寻找目标，满五站也能排序。保留删除、空输入 Backspace 与中文输入法保护，普通页面纵向滚动可用。
- 继续只允许最多五个真实、互异的已确认站点；满站关闭额外搜索，入口显示“目的地到达上限”，删除后恢复新增。纯输入与开关不增加已选数量；关闭额外搜索后不得因空站阻塞提交。
- 首页条件规划、卡内确认、草稿恢复共用同一行为。未处理的恢复查询队列必须完整自动保存，提交、摘要及刷新后站点顺序一致。保留候选错误、Escape、失焦、切换模式和过期搜索关闭边界。

执行者自己决定：基础输入与右侧按钮的容器实现、小块尺寸及视觉细节、二维排序算法和可访问键盘方式；在现有草稿字段内表达未确认查询。只改责任组件与对应样式/检查，保留其他工作区改动。

不许碰：既有五站合同及其他旅行规则、预算、地点合法种类、公开 API／SSE／持久化结构、后端规划流程、真实数据和付费服务。不提交、不推送。

## 5 停下来报告的情况

若满足基础输入常驻或草稿恢复必须改变公开字段/持久化结构，报告具体冲突；不得静默丢弃多段未确认草稿。其余按工作目录 README 的通用停止条件执行。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 零站首屏及删至零站时，首站输入始终可见，输入与右侧“新增目的地”共同占满区域；点击按钮不产生关闭状态。无首站时提交仍被校验拒绝。
2. 2000px 和 390px 下，1/2/5 站显示紧凑小块，空间不足换行，无每站强制整行和目的地区横向滚动。右侧入口可见可用。
3. 确认首站后“新增目的地 → 关闭新增 → 新增目的地”只控制下方额外搜索；关闭和延迟候选不改变已确认数量/顺序，候选不会重开。
4. 同排与跨行、含满五站的鼠标和真实触屏排序可用，键盘及删除/退格/中文输入法保护可用；提交、确认摘要、自动保存和恢复顺序一致，多段查询不丢失。
5. 五站限制只限制新增；删除后恢复入口，删除最后一站恢复基础输入，不存在零站且无输入的界面。

### 6.2 必须运行的检查

在 `frontend/` 下运行：

- `npm run type-check`
- `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --grep '目的地|真实触摸|双模式共享稳定主按钮' --workers=1`
- `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1`

更新已有目的地定向用例，覆盖初始按钮与右侧几何、首站不可关闭、删除末站恢复、小块同排/换行、二维排序、五站边界及原草稿/候选保护。触屏使用真实触摸事件；API 使用离线夹具，不调用模型或写真实用户数据。8088 已有本地 Vite 服务，使用前检查能否复用。

### 6.3 实屏证据（执行者提供）

2000×880 与 390×844 的初始首站、两站收起/展开、五站状态，以及删至零站的截图；提供首站输入与右侧按钮几何、紧凑小块换行几何，以及一次跨行排序后的提交/恢复顺序。存原任务 output 目录并以本轮命名，不覆盖旧反馈和证据。

### 6.4 真人验收（用户操作）

1. 进入条件规划 → 首个目的地输入全宽、右侧为“新增目的地”；点击该按钮仍能填写首站。
2. 选首站并新增第二站 → 每站为可拖动、可删除的小块，下方仅有一个新增搜索；点击“关闭新增”后小块保留。
3. 加至五站、拖动排序、删除 → 满站仅停止新增；排序正常、删一站可继续新增。删至最后一站再删除 → 恢复首站输入，不能把目的地区域关空。
4. 缩窄窗口、刷新草稿并进入确认 → 地点小块自然换行、无横向滚动，地点和顺序不丢失。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 13:25 · pi 编码代理

- 改动摘要：新增横向目的地标签输入，复用真实地点搜索与 `PlaceIdentity` 选择；默认单站，添加后在同一容器内显示标签与搜索输入，最多五站。支持点击空白/添加入口聚焦搜索、候选选择、空输入 Backspace 删除最后一站、输入法 composing 保护、标签删除、键盘左右排序、桌面拖动与触屏长按拖动；满五站入口显示“最多5个目的地”，只读输入仍可退格删除。首页与页内确认共用同一组件，排序同时写入 `controlled_trip_identity` 与 intake 草稿。前后端上限统一为 5。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`（新增）、`frontend/src/features/travel/components/planning/TripPlanner.tsx`、`frontend/src/features/travel/components/planning/GuidedIntakeQuestions.tsx`、`frontend/src/features/travel/components/planning/PlaceField.tsx`、`frontend/src/features/travel/model/tripIdentityValidation.ts`、`frontend/src/index.css`、`frontend/e2e/home-inspiration.spec.ts`、`frontend/e2e/planner-intake.spec.ts`、`backend/travel_agent/planning/requirements/identity_contracts.py`、`backend/tests/api/test_trip_intake.py`。
- 偏离方案及理由：拖动优先使用 Pointer Events，不新增依赖；触屏长按 380ms 后按位置排序，桌面按下即可拖动，轻点不改变顺序。满站保留一个只读紧凑输入承接空退格，避免五站后无法按用户描述删除最后一站。其余沿用既有搜索和身份合同。
- 实际运行的检查与结果：`npm run type-check` 通过；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --workers=1` 通过（12 项，含标签添加/五站上限/空退格/输入法/键盘与拖动排序）；同环境 `e2e/planner-intake.spec.ts` 通过（3 项，含提交顺序与 intake 草稿顺序）；`uv run --project backend pytest -c backend/pyproject.toml backend/tests/api/test_trip_intake.py -q` 通过（8 项，含五站通过、六站拒绝）；`ruff check backend/travel_agent/planning/requirements/identity_contracts.py backend/tests/api/test_trip_intake.py` 通过。
- 实屏证据：`output/polish/20261029-1252-destination-tokens/destination-2000-single.png`、`destination-2000-five.png`、`destination-390-search.png`、`destination-390-five.png`；提交顺序断言为 `['苏州','青岛']`，草稿 `confirmed_destinations` 顺序一致。
- 遗留问题或需要指挥决定的事：长按/拖动与满站只读输入的最终手感建议交用户体验讨论后再微调；当前为可撤回的第一版。


### 第 2 轮 · 2026-10-29 14:05 · pi 编码代理

- 改动摘要：R1 把触屏协调改成从手势起点开始：标签始终 `touch-action: none`，未长按时由代码接管横向位移驱动容器滚动，长按后同一指针转为排序，不再等 CSS 切 `none`；保留 Pointer Capture 并在结束/取消时释放。R2 为候选 portal 增加外部 pointerdown、Escape、失焦、面板隐藏检测和搜索序号/关闭标记，关闭后旧延迟结果不能重开。R3 恢复草稿时把超出已确认站点数量的末尾 `destination_queries` 保留为未确认搜索文字，不生成确认标签。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`、`frontend/src/features/travel/components/planning/GuidedIntakeQuestions.tsx`、`frontend/src/index.css`、`frontend/e2e/home-inspiration.spec.ts`、`frontend/e2e/planner-intake.spec.ts`。
- 偏离方案及理由：触屏横滑不再依赖原生横向 pan，而由 token 指针移动直接控制容器 `scrollLeft`；这样普通横滑和长按排序在同一个手势起点下可区分，代价是触屏从标签上纵向拖不再驱动页面滚动，可从标签外区域滚动页面。
- 实际运行的检查与结果：`npm run type-check` 通过；`e2e/home-inspiration.spec.ts -g "目的地标签|真实触摸|目的地候选"` 3 项通过；其中 R1 使用 Chromium `hasTouch:true,isMobile:true,390×844` 与 CDP `Input.dispatchTouchEvent`，断言普通横滑 `scrollLeft > 40` 且顺序不变、长按 430ms 后拖到相邻站顺序变为杭州→苏州；R2 断言 Escape、Tab 失焦、切换自然模式后候选消失且等待 600ms 不被旧搜索重开，之后重新输入仍可选择；`e2e/planner-intake.spec.ts` 5 项通过，R3 断言恢复后仅 1 个确认标签、末尾“苏州”保留在搜索框。
- 实屏证据：`output/polish/20261029-1252-destination-tokens/destination-390-touch-reorder.png`；此前单站/五站/候选截图继续有效。
- 遗留问题或需要指挥决定的事：触屏从标签上纵向拖动不滚页面，改由标签外区域滚动；若真人验收要求标签区域也支持纵向页面滚动，需要再定义双轴手势阈值。

### 第 3 轮 · 2026-10-29 14:45 · pi 编码代理

- 改动摘要：R4 修复鼠标拖动的 pointer capture/release。`startPointer` 现在对所有指针类型先设置 capture，鼠标再进入拖动；`onLostPointerCapture` 在异常丢失捕获时清理拖动状态，字段外释放会正常收到 `pointerup` 并清除 `is-dragging`。触屏长按、普通横滑和候选/恢复逻辑保持不变。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`、`frontend/e2e/home-inspiration.spec.ts`。
- 偏离方案及理由：无。
- 实际运行的检查与结果：`npm run type-check` 通过；`e2e/home-inspiration.spec.ts -g "目的地标签|真实触摸"` 2 项通过，其中新增真实 `page.mouse` 拖到字段外再释放，断言 `.destination-token.is-dragging` 数量为 0；指挥独立 probe 重跑结果为 `swipeScrollLeft=69`、横滑顺序不变、长按后 `杭州,苏州,南京,宁波,绍兴`、`mouseDraggingAfterReleaseOutside=0`、无页面错误。
- 实屏证据：本轮无需新增截图；沿用目的地任务已有单站/五站/触摸排序截图。
- 遗留问题或需要指挥决定的事：无。

### 第 4 轮 · 2026-10-29 15:15 · pi 编码代理

- 改动摘要：按 R5/R6 把目的地改为上方逐站纵向列表，下方由同一个入口展开、收起单个搜索区。入口有“新增目的地 / 关闭新增 / 目的地到达上限”三种形态；首站选择后自动收起，之后连续确认会逐行增加，满五站收起搜索并禁用入口，删除后恢复。展开、输入或关闭都不生成空站，关闭后提交与草稿只带已确认地点。排序改为右侧把手拖动（鼠标与真实触摸）和上下方向键，保留逐站删除、Delete/Backspace 与空输入 Backspace 删除末站；列表正文保留浏览器纵向滚动。恢复草稿时把末尾 `destination_queries` 作为搜索文字而不是地点，多段旧草稿按队列逐个带到单个搜索框。移除横向滚动容器、横向手势和满站只读伪输入。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`、`frontend/src/features/travel/components/planning/GuidedIntakeQuestions.tsx`、`frontend/src/index.css`、`frontend/e2e/home-inspiration.spec.ts`、`frontend/e2e/planner-intake.spec.ts`。
- 偏离方案及理由：空列表时的首站搜索与“关闭新增”同排，避免新增入口让首屏表单增高一整行，同时保留可发现的首站搜索；首次从零选站后自动收起，后续新增区保持展开以便连续选择；触屏排序使用右侧专用把手而不是整行长按，使列表正文仍能正常纵向滚动页面。未改后端五站合同。
- 实际运行的检查与结果：`npm run type-check` 通过；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --grep '目的地' --workers=1` 通过（2 项，覆盖纵向几何、开关/连续添加/五站上限、空退格与输入法、鼠标拖动、上下键排序、390px 无横向溢出、候选关闭边界）；同环境 `e2e/planner-intake.spec.ts` 通过（5 项，覆盖桌面/手机确认后提交顺序、关闭后无空站、失败重试保留地点、恢复两站顺序与末尾搜索草稿）；额外全量 `e2e/home-inspiration.spec.ts` 通过（15 项，含既有双模式高度、reduced-motion、真实触摸排序和延迟候选用例）；`git diff --check` 通过。
- 实屏证据：`output/polish/20261029-1252-destination-tokens/destination-r5-2000-two-collapsed.png`、`destination-r5-2000-two-expanded.png`、`destination-r5-2000-five-limit.png`、`destination-r5-390-two-collapsed.png`、`destination-r5-390-two-expanded.png`、`destination-r5-390-five-limit.png`、`destination-r5-390-search.png`、`destination-r5-390-touch-reorder.png`、`destination-r5-intake-sorted.png`。`destination-r5-geometry.json` 记录 2000px 两站展开时最后一行 bottom=415.77、搜索框 top=492.27，390px 最后一行 bottom=491.25、搜索框 top=567.75，及 2000px 五行逐行递增、无横向滚动。planner-intake 断言提交与草稿顺序均为 `['苏州','青岛']`。
- 遗留问题或需要指挥决定的事：无阻塞。已知交互取舍：空列表时搜索与关闭按钮同排；首次从零选站后自动收起；用户主动关闭新增会丢弃尚未确认的搜索草稿（已确认站点不变）。若真人验收希望关闭后仍保留草稿，可再讨论。

### 第 6 轮 · 2026-10-29 16:03 · pi 编码代理

- 改动摘要：R7 移除排序入口对满站的误拦截，五站时鼠标、真实触屏与键盘仍可调整已选顺序，数量上限只禁用“新增目的地”；R8 把当前搜索文字和后续草稿队列一起写入现有 `queries`，恢复归一化、编辑、选择、删除与排序都保留尚未处理的队列，选择当前草稿后继续把后续草稿带入下方唯一搜索框。主动关闭新增仍按既定行为丢弃未确认草稿，已确认站点不受影响；未改公开字段、后端上限或规划流程。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`、`frontend/e2e/home-inspiration.spec.ts`、`frontend/e2e/planner-intake.spec.ts`。
- 偏离方案及理由：无。
- 实际运行的检查与结果：`npm run type-check` 通过；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --grep '目的地' --workers=1` 通过（2 项，覆盖纵向几何、开关/连续添加/五站上限、候选关闭边界，以及满五站鼠标拖动和上下键排序）；同环境 `e2e/planner-intake.spec.ts --workers=1` 通过（7 项，新增桌面/手机五站满额拖动、键盘调整后提交，断言 controlled identity 与草稿顺序均为青岛、苏州、南京、绍兴、宁波；新增恢复 confirmed=[青岛]、queries=[青岛,苏州,杭州] 后自动保存、刷新、逐项确认与再次刷新）；额外 `e2e/home-inspiration.spec.ts --grep '真实触摸' --workers=1` 通过（1 项，CDP 真实触摸在五站满额时把杭州、苏州换为苏州、杭州）。`git diff --check` 通过。
- 实屏证据：`output/polish/20261029-1252-destination-tokens/destination-rework-r7r8-2000-two-collapsed.png`、`destination-rework-r7r8-2000-two-expanded.png`、`destination-rework-r7r8-2000-five-limit.png`、`destination-rework-r7r8-390-two-collapsed.png`、`destination-rework-r7r8-390-two-expanded.png`、`destination-rework-r7r8-390-five-limit.png`、`destination-rework-r7r8-390-search.png`、`destination-rework-r7r8-390-touch-two-reorder.png`、`destination-rework-r7r8-390-touch-five-reorder.png`、`destination-rework-r7r8-intake-two-sorted-2000.png`、`destination-rework-r7r8-intake-five-sorted-2000.png`、`destination-rework-r7r8-intake-two-sorted-390.png`、`destination-rework-r7r8-intake-five-sorted-390.png`。`destination-rework-r7r8-geometry.json` 记录 2000px 两站最后一行 bottom=415.77、搜索框 top=492.27，390px 最后一行 bottom=491.25、搜索框 top=567.75，五行逐行递增且无横向滚动；`destination-rework-r7r8-intake-five-order-2000.json` 与 `-390.json` 记录满站鼠标、键盘与提交顺序；`destination-rework-r7r8-draft-saves.json` 记录五次自动保存均为 queries=[青岛,苏州,杭州]，确认站点依次为 [青岛]、[青岛]、[青岛,苏州]、[青岛,苏州]、[青岛,苏州,杭州]。
- 遗留问题或需要指挥决定的事：无阻塞。主动关闭新增仍会丢弃尚未确认的搜索草稿（既定行为，已确认站点不变）；满五站选择最后一站时新增区自动收起。未修改后端。

### 第 7 轮 · 2026-10-29 17:42 · pi 编码代理

- 改动摘要：按 R9/R10 区分首站基础输入与可选新增。零站时首站搜索常驻，与右侧“新增目的地”共同占满目的地区域；此时点击按钮只聚焦首站输入，不关闭、不隐藏、不生成地点。选站后恢复紧凑地点小块，小块在容器内自然换行，右侧继续保留新增入口；有站时新增才在下方展开唯一搜索区并把按钮切为“关闭新增”，关闭只收起额外搜索。删除末站回到基础输入，并保留尚未确认的当前文字与后续草稿队列。拖动排序改为按指针横纵坐标寻找最近的小块中心，同排、跨行及满五站均可用；键盘增加左右方向键排序。移除每站编号与整行宽度，保留删除、空输入 Backspace、输入法 composing 保护、候选异步关闭和五站限制。
- 改动文件：`frontend/src/features/travel/components/planning/DestinationTokenField.tsx`、`frontend/src/index.css`（仅 destination 相关选择器）、`frontend/e2e/home-inspiration.spec.ts`、`frontend/e2e/planner-intake.spec.ts`。未改 `TripPlanner.tsx`、`GuidedIntakeQuestions.tsx`、后端或公开字段；`tripIdentityError` 的空列表拒绝沿用既有校验。
- 偏离方案及理由：无。
- 实际运行的检查与结果：`npm run type-check` 通过；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --grep '目的地|真实触摸|双模式共享稳定主按钮' --workers=1` 通过（4 项，覆盖零站/右侧按钮几何、首站不可关闭、紧凑小块同排与换行、二维鼠标排序、真实 CDP 触摸同排与跨行排序、满五站排序与删除末站恢复）；同环境 `e2e/planner-intake.spec.ts --workers=1` 通过（7 项，覆盖两站/五站提交顺序、多段草稿自动保存与刷新恢复、删除末站后基础输入及 `queries=[苏州,杭州]` 持续保存）；额外全量 `e2e/home-inspiration.spec.ts --workers=1` 通过（15 项）。`git diff --check` 通过。
- 实屏证据：`output/polish/20261029-1252-destination-tokens/destination-r9r10-2000-initial.png`、`destination-r9r10-390-initial.png`、`destination-r9r10-2000-two-expanded.png`、`destination-r9r10-2000-two-collapsed.png`、`destination-r9r10-390-two-expanded.png`、`destination-r9r10-390-two-collapsed.png`、`destination-r9r10-2000-five-limit.png`、`destination-r9r10-390-five-limit.png`、`destination-r9r10-390-zero.png`、`destination-r9r10-390-mouse-cross-row.png`、`destination-r9r10-390-touch-two-reorder.png`、`destination-r9r10-390-touch-five-cross-row.png`、`destination-r9r10-intake-two-sorted-2000.png`、`destination-r9r10-intake-two-sorted-390.png`、`destination-r9r10-intake-five-sorted-2000.png`、`destination-r9r10-intake-five-sorted-390.png`。`destination-r9r10-geometry.json` 记录 2000px 初始搜索宽 321.75、按钮 106 且位于右侧、组合宽度覆盖 433.75 的字段；两站同排、五站四加一换行；390px 五站三加二换行、文档无横向溢出；跨行鼠标排序后为苏州、南京、宁波、杭州、绍兴。`destination-r9r10-touch-orders.json` 记录真实触摸同排与跨行顺序；`destination-r9r10-delete-last-queue.json` 记录删末站后基础输入保留“苏州”、自动保存及刷新后 `queries=[苏州,杭州]`，再选苏州后搜索框继续带出“杭州”；`destination-r9r10-draft-saves.json` 与 `destination-r9r10-intake-five-order-2000/390.json` 记录多草稿、提交与草稿顺序。本轮开始前的文件和 SHA-256 基线、以及仅本轮的差异保存在 `output/polish/20261029-1252-destination-tokens/baseline-r9r10/`，未覆盖旧证据。
- 遗留问题或需要指挥决定的事：无阻塞。触屏从把手拖动时页面不纵向滚动，把手外区域仍可正常滚动；零站新增按钮的 `aria-expanded` 为 `true`（受控基础输入始终可见），有站时随额外搜索开合。最终手感交第 6.4 节真人验收。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 指挥

- 结论：返工。已核对标签单站/五站、390px 候选与横向滚动截图；指挥独立抽查的首页两项定向用例通过，但鼠标拖动无法证明触屏长按可用。
- R1（必须修复）：审查代理使用 Chromium 390×844、hasTouch/isMobile 与 CDP Input.dispatchTouchEvent 真实触摸事件，复现长按 430ms 后横拖触发 pointercancel，顺序保持不变。CSS 从 pan-x 到长按后的 none 改得太晚，浏览器在手势开始时已决定原生滚动。修复后必须同时保留普通横滑和长按重排，用真实触摸事件分别证明，不能仅用 dispatchEvent 或鼠标模拟。
- R2：DestinationSearch 候选 portal 到 document.body，当前只依赖 candidates/error 显示，缺少失焦、Escape、外部点击及面板隐藏时的收起边界。需验证并修复切换到自然模式/确认区域隐藏时的悬空候选，且旧搜索结果不能重开已关闭弹层；候选点击选择仍须正常。
- R3：核对已有确认站点加未确认搜索文字时刷新恢复，当前 initialDraft 分支优先 confirmed_destinations，可能丢掉末尾 destination_queries。未确认文字应保留为搜索文字且不能误算成已确认地点；增加定向恢复检查。

### 第 2 轮 · 2026-10-29 · 指挥

- R1–R3 已复核：指挥独立 CDP touch probe 得到普通横滑 scrollLeft=69 且顺序不变，长按后顺序变为杭州、苏州、南京、宁波、绍兴；候选切换模式后关闭；恢复搜索草稿的离线用例通过。
- R4：本轮触屏修复把 pointer capture 放到 touch 分支，mouse 分支提前 return，导致鼠标拖出字段后放开仍保留 is-dragging。指挥独立 probe 的 mouseDraggingAfterReleaseOutside=1。鼠标也必须完整 capture/release，字段外释放或丢失捕获后不残留拖动态；补真实 page.mouse 移出再释放的回归，并保留已通过触屏行为。

### 第 3 轮 · 2026-10-29 · 指挥

- 结论：R4 通过，目的地任务转待真人验收；本批四项任务代码验收全部通过。
- 核对：鼠标/触屏在分支前统一设置 Pointer Capture，结束时释放，异常 lost-capture 清理拖动态。改动止于本组件和相关回归；未再改已通过的 inline/generation 任务。
- 指挥独立复测：`node output/polish/20261029-1252-destination-tokens/commander-touch-probe.mjs`，普通横滑 scrollLeft=69、顺序不变；长按激活并重排为杭州、苏州、南京、宁波、绍兴；鼠标字段外释放后 mouseDraggingAfterReleaseOutside=0；pageErrors=[]。结果保存在同目录 commander-touch-probe.json。`git diff --check` 通过。
- 验证范围：执行者类型检查与目的地两项定向回归通过；指挥前两轮独立运行的首页几何/目的地、确认与恢复/生成工作区检查及本轮真实输入 probe 共同覆盖本批行为。五站/六站前后端边界和初轮后端检查记录已核对；未请求付费模型或改真实数据。
- 已知交互取舍：标签区域由自定义手势承接横滑/长按，在标签上纵向拖动不会滚动页面；页面可从标签外区域滚动。记录供真人评价手感，不影响本次横向排列/排序要求。
- 真人步骤：按第 6.4 节添加至五站、空退格删除、拖动/长按排序；同时观察切换模式后候选是否正常收起。

### 第 4 轮 · 2026-10-29 · 真人反馈后修订

- 结论：返工；用户调整交互方向，原先“始终横向一排”的方案由纵向逐站列表与下方单个可收起新增区替代。第 2–6 节已重写，历史执行记录保留。
- R5：将已选列表与新增搜索可见性分离，完成三种按钮形态、纵向排列和满站边界；不能只给原横向容器改换行。
- R6：同步检查排序方向、触屏纵向滚动、恢复中的未确认文字、关闭后的空站校验与候选异步关闭，更新原横滑用例并提供本轮实屏证据。

### 第 5 轮 · 2026-10-29 · 本轮实现代码验收

- 结论：返工。纵向布局、下方单个搜索区及三种入口形态已查看截图并符合方向，但两个状态边界不通过。已对照执行前基线并核对责任代码；独立浏览器检查使用合成数据、全 API 拦截。
- R7：`DestinationTokenField.tsx:466–467` 的满站条件同时阻止指针排序。五站时排序把手仍显示，但真实鼠标拖动不进入 dragging、顺序不变；删除至四站后相同操作成功，触屏共享此入口。数量上限只能限制新增，满五站时已选列表仍必须支持鼠标、真实触屏与键盘排序；补满站实际拖动和提交顺序检查。
- R8：`DestinationTokenField.tsx:33–36、294–311` 的恢复归一化只向上游写当前编辑文字，没有保留队列中的后续草稿。合成恢复 confirmed=[青岛]、queries=[青岛,苏州,杭州]，用户尚未关闭或编辑，自动保存已变成 [青岛,苏州]；杭州仅存内存，刷新即丢。所有未处理旧草稿必须沿现有草稿合同继续保存，不能把队列仅留在组件内存；补自动保存完成后刷新、逐项选择/处理与已确认顺序的检查。主动关闭新增的既定行为与本项“用户未操作即丢草稿”分开验证。
- 审查证据已归档：`output/polish/20261029-1252-destination-tokens/commander-r5-browser.json`。现有两站/五站桌面与手机截图、几何 JSON 和触摸截图已核对；返工后保留已通过布局、候选关闭和输入法行为，新增证据不要覆盖反馈原图。

### 第 6 轮 · 2026-10-29 · 返工验收

- 结论：R7/R8 通过，转待真人验收。
- 核对责任代码：满站限制已从指针排序入口移除；`queriesFor` 及恢复、选择、编辑、排序路径将当前草稿和队列一并写回现有查询字段。数量限制只管新增，没有改变五站合同或引入空站。
- 独立审查实际验证了桌面/手机满五站鼠标和键盘排序后提交顺序、CDP 真实触摸满站排序，以及多草稿自动保存→刷新→逐项确认→再刷新；无返工项。已对照两个基线，后端通过项未被再次改动。
- 指挥核对了最新桌面展开与手机满站截图，以及本轮执行记录和几何/草稿证据；独立审查逐张查看全部声明截图。指挥额外运行 `cd frontend && JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts e2e/research-progress.spec.ts --grep '恢复多段|旧首页保持|真实 thinking' --workers=1 --output=../output/polish/commander-final-checks-20261029`，合计 4 passed，其中多草稿刷新恢复检查通过。
- 已知交互：主动“关闭新增”会丢弃尚未确认的搜索文字，上方已确认目的地保留；未操作即自动保存/刷新时不丢草稿。最终手感由第 6.4 节真人步骤验收。

### 第 7 轮 · 2026-10-29 · 首站与小块交互反馈后修订

- 结论：返工；原方案混淆首站输入与可选新增，首屏出现“关闭新增”且可关空，未满足“默认一个目的地、右侧新增”的意图。第 2–6 节按最新反馈重写。
- R9：首站基础输入始终可见，右侧为新增按钮；仅额外搜索可开关。删除末站恢复首站，不允许零站且无输入的界面；校验仍要求真实候选。
- R10：已选地点恢复紧凑可删除小块，自然换行并支持同排/跨行的二维排序，五站时仍可拖动。更新首屏和删除末站、几何、真实鼠标/触屏、提交/草稿恢复的检查和截图。

### 第 8 轮 · 2026-10-29 · R9/R10 代码验收

- 结论：R9/R10 通过，转待真人验收。已对照执行前基线审查本轮四个产品/检查文件的差异；初始入口与额外搜索分开呈现，零站按钮只聚焦基础输入，删除末站保留基础输入和未处理查询。小块不再固定整行，排序同时使用横纵坐标，五站只限制新增。
- 实屏核对：已逐张查看本轮 16 张桌面/手机截图（另生成 `commander-r9r10-screens-1.jpg` 至 `-4.jpg` 便于并排核对）；初始右侧按钮、两站展开/收起、五站换行、删除末站以及确认区均符合方案，无目的地区横向溢出。
- 指挥独立复测：`cd frontend && JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts e2e/planner-intake.spec.ts --grep '目的地小块|真实触摸|恢复多段' --workers=1 --output=../output/polish/20261029-1252-destination-tokens/commander-r9r10-checks` 实际匹配并通过 2 项（真实 CDP 触摸同排/跨行排序、多段草稿自动保存/刷新/确认及删除末站保留队列）；再用 `e2e/home-inspiration.spec.ts --grep '目的地首站全宽' --workers=1 --output=../output/polish/20261029-1252-destination-tokens/commander-r9r10-base-check` 通过 1 项（首屏几何与不可关空、小块/五站及鼠标二维排序、末站恢复）。合计独立通过 3 项，`git diff --check` 通过。
- 已核对执行者类型检查、首页全量 15 项与 intake 7 项结果；未重复全量。原 `TripPlanner.tsx`、`GuidedIntakeQuestions.tsx` 与执行前文件完全一致，另对本轮前保存的 79 个无关文件逐一核对 SHA-256，均未改变。无后端或公开合同改动。
- 剩余真人步骤：按第 6.4 节观察首站全宽与右侧新增，添加/收起、拖动和删除至零站，缩窄窗口及刷新草稿。触屏从把手开始的拖动用于排序，把手外仍可滚动页面；未调用真实模型或修改真实会话。

## 9 真人验收（指挥代录）

### 2026-10-29 · 不通过并调整方案

> 关于多个目的地选择，我的想法其实出了一个新的想法，就是当我们点击目的地选择这个按钮的时候，那在它下面出现这个输入框，这样的话它不会影响上面的这个目的地的数量，不会出现那种一直往右边排输入框这种情况。并且呢，如果要是目的地太多了，我们不应该是种横向的，我们应该是直接是竖向的。比如说第一排目的地、第二排目的地这种。就是说在用户点击增加目的地之后，那我们的这个输入框就在下面出现了，然后每出增加一个输入，那就在上面再加一个
> 并且我们如果要是不想再增加目的地了，我们再点一下这个增加目的地的这个按钮，我就可以收起这个输入框。或者说我们在不同形态之后，我们这上面显示内容是不同的，比如说是新增目的地、关闭新增、目的地到达上限

截图：`output/polish/20261029-1252-destination-tokens/feedback-2.png`。

### 2026-10-29 17:22 · 不通过，补正首站与已选小块

> 我们这设计的逻辑有问题啊，它无论如何也应该有一个目的地啊。为什么它一上来就关闭新增啊？我们是一开始它是一个全宽的，然后右边有一个按钮，让用户可以去新增目的地。然后他们的排列方式和我们之前那个版本是一样的，都是一个目的地是一个小块，然后用户可以自由地拖动，可以删除。你为什么弄成这样子的呀？

补充指令：继续。首站常驻指始终保留填写入口，未确认的文字不能视作真实地点；本轮未提供新截图。