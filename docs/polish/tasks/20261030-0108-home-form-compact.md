# 首页条件表单缩紧，目的地开关留在首行

- 编号：20261030-0108-home-form-compact
- 状态：待真人验收
- 创建：2026-10-30 01:08
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、docs/invariants.md、frontend/README.md、frontend/e2e/README.md、[本轮所有权与基线](../references/20261030-0108-feedback-workflow.md)

## 1 用户反馈

> 截图1首页按条件规划：出发地太长要缩短；目的地删除显眼六点拖动把手及“拖动右侧把手或按方向键调整顺序”的教学提示（保留实际排序与键盘无障碍）；“关闭新增”按钮始终在第一排，目的地多时不被挤至第二排；去掉“精确日期 最长14天”“同行”这一行可视标签（保留14天真实约束与可访问名称）；日期占位简化为“开始日期 → 结束日期”，缩短控件；同行人数缩短；预算移至日期同行同排，输入框直接提示“预算（可选）”，不再单独外部标签/占位12000/下方占行。

截图：`output/polish/20261030-0108-feedback-workflow/feedback/feedback-1.png`。指挥已 read 看图，不再复制。

## 2 现象与发生条件

首页“按条件规划”，常用出发地深圳、已选北京/上海/长春，新增搜索展开。原图为局部放大截图，不能从其像素直接推断 CSS 视口；回归以 2000×880、1440×900、390×844 为准。需覆盖 0/1/3/5 站、长城市名、删除末站、已有草稿与更多偏好。目的地组件也用于首页卡内 intake，日期组件也被 intake 复用，不能只修初始首页而破坏确认路径。

## 3 根因

- `frontend/src/features/travel/components/planning/TripPlanner.tsx:466–520` 将日期与同行放两列，预算放偏好行下的独立带标签控件；`frontend/src/index.css:1256–1261、1539–1544` 对出发地/目的地和日期/同行按比例分配大宽度，布局没有日期+同行+预算三控件的紧凑一排。
- `DestinationTokenField.tsx:534–590` 将拖动指针事件仅绑定专用六点 span；`:611–612` 输出可视教学。不能仅删 span，否则鼠标/触屏排序也消失。`:591–609` 的开关 footer 与 token 同处 wrap flex；`index.css:1277–1298、1492–1498` 的 list display:contents、footer margin-left:auto 只会推到当前行末尾，不会为第一行保留独立按钮位。
- `DateRangePicker.tsx:170–184` 无条件输出可视“精确日期/最长14天”标签区，且按钮占位含“选择”；真实日期限制在 `:155–165` 的 select 及日期单元格禁用逻辑，显示冗余不是约束本身。
- `TripPlanner.tsx:485–496` 外层 Field 输出“同行”；`:510–519` 预算外部标签/12,000 占位与用户目标相反。现有金额解析仍是正确责任边界，不改预算规则。

关联旧任务 `20261029-1252-home-form-rhythm`、`20261029-1252-destination-tokens` 与 `20261029-1207-calendar-date-limits` 已保留基础交互，本轮替代的是可视把手/提示与部分排布，不回退五站、14天、草稿、排序或双模式稳定。

## 4 方案

目标状态：首行出发地紧凑，目的地区域更充裕，新增/关闭按钮稳定在其第一排；日期、同行、可选预算在桌面同一排，偏好不再被预算占行；页面更短但控制仍可发现、可操作。

必须做：

- 缩短出发地、日期和同行的桌面占宽，不截断关键值或破坏候选；日期空态严格为“开始日期 → 结束日期”。隐藏首页的“精确日期/最长14天”和外部“同行”可视标签，保持日期/同行/预算的可访问名称与焦点可见性。日历内真实天数、禁用范围/有效反馈可保留。
- 预算移到日期/同行同一行，输入 placeholder 为“预算（可选）”，不显示外部标签或 12,000 占位；使用 sr-only label 或等价可访问命名。金额输入继续是 text/decimal，保留人民币、空值可选、正金额/千分位校验与提交语义，不默认填 12000。
- 已选 token 可以换行，新增/关闭/满站入口在目的地区域第一排独立保留，不随第 3/5 站挤到第二排；移动端也保留开关首排可见，剩余站点在自己的内容区换行。不能靠横向滚动或遮住地点/按钮实现。
- 删除可见六点图标与整行教学；为 token 正文提供不显眼但真实可用的拖动命中面，保留鼠标/触屏同排及跨行排序、方向键/删除键、排序通知、删除按钮独立点击与输入法保护。无障碍说明不得继续说“右侧把手”。真实触摸从非排序区域纵向滚动页面仍可用。
- 保留零站基础搜索常驻，删末站恢复；五站限制只禁新增，不禁排序；关闭额外搜索不生成空站。保留候选 Escape/失焦/延迟结果保护、多段未确认草稿、自动保存、刷新/提交顺序。
- 与自然模式切换保留草稿和共享主按钮稳定；更多偏好、首次出发地设置、错误、390px 不重叠。移动端日期/同行/预算可以合理折行，不强塞三列。

执行者自己决定：响应式列宽、token 非显眼拖动区域/手势阈值、日期共用组件采用局部变体还是统一无可视标签；优先在责任组件与既有样式中修改，不新增平行表单。

不许碰：后端、API/SSE/持久化、地点身份与五站/14天规则、预算解析规则、真实数据/外部 Provider、右侧素材、恢复浮框/续聊旧改动。backend 完成需求任务后，由唯一 frontend 写入者顺序执行本项。仅拥有 TripPlanner / DestinationTokenField / DateRangePicker、必要 PlaceField 呈现、首页/确认离线测试及对应 CSS 增量；本任务文档只改状态与第7节。`index.css` 含既有混合改动，禁止整文件暂存；不自行提交/推送。

## 5 停下来报告的情况

- 去掉把手导致触屏排序和正常纵滚无法兼顾，或需要变更地点/草稿公开字段时，提供真实触摸证据后报告，不删功能冒充完成。
- 若任务2改变 intake 行为，既有浏览器用例需等待后端交接与更新合成响应，不能通过自动批准/跳过澄清保持旧断言。
- 如果本轮 CSS/测试增量不能在 HEAD 上独立成立，按本轮基线文档报告提交依赖；不清理旧修改。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 桌面出发地/日期/同行宽度均比反馈明显缩短，日期+同行+预算同排；可视冗余标签/12,000 消失，名称仍可被 getByRole/getByLabel 正确定位，金额数据无变化。
2. 0/1/3/5站与长名下开关首排位置稳定；无横向滚动，站点自然换行；新增/关闭/满额、删末站与候选异步边界正确。
3. 鼠标、真实触摸、键盘排序与删除/空退格仍可用，提交/保存/恢复顺序一致；无六点把手或可视教学，aria 不指向不存在的把手。
4. 14天含首尾有效、15天禁用、过去日期禁用和跨月/年/DST 不回归；自然模式、主按钮与 reduced-motion 保持原约束。

### 6.2 必须运行的检查

前提：只启动/复用 Vite，先确认 8088 对应本 checkout；若没有，串行 `cd frontend && npm run dev -- --host 127.0.0.1 --port 8088 --strictPort`。浏览器 API/地图/外网全部拦截，未匹配请求要失败，不连真实后端。

```bash
cd frontend
npm run type-check
npm run test -- src/features/travel/model/tripIdentityValidation.test.ts
JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --workers=1 --output=../output/polish/20261030-0108-home-form-compact/playwright-home
JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1 --output=../output/polish/20261030-0108-home-form-compact/playwright-intake
```

扩展既有首页几何/目的地/日历用例验证三控件同排、开关第一排、无障碍名称和新拖动命中面；真实触摸使用 CDP touch，而非 dispatchEvent/mouse 冒充。旧测试绑把手、外部标签或预算所在行的断言应按新目标改写，不删排序/14天行为检查。不跑 live-planning/写真实数据套件。

### 6.3 实屏证据（执行者提供）

存 `output/polish/20261030-0108-home-form-compact/`：2000×880 和1440×900 三站新增展开、五站与零站各必要状态；390×844 三站/五站与更多偏好。附首排开关/各控件矩形、无横向溢出、拖动前后与提交/恢复顺序；至少一份真实触摸跨行排序结果。指挥必须 read 查看，不用 DOM 几何代替视觉验收。

### 6.4 真人验收（用户操作）

1. 首页按条件规划选深圳和北京/上海/长春，打开新增 → 出发地紧凑，开关在第一排，六点与教学消失。
2. 看日期/同行/预算并输入预算 → 一排紧凑、空日期为“开始日期 → 结束日期”、预算框提示“预算（可选）”，无外部冗余标签。
3. 拖动/方向键换站序，加至五站再删除并刷新 → 排序/新增与恢复仍正常；日历不可选超过14天。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 02:10 · frontend

- 改动摘要：出发地列收窄；日期、同行、预算在桌面同一排，390px 日期独占一排、同行与预算并排。日期空态改为“开始日期 → 结束日期”，首页隐藏“精确日期/最长14天”和外部“同行”标签，保留可访问名称与日历内 14 天约束。预算输入去掉外部标签和 12,000 占位，直接提示“预算（可选）”，仍是 text/decimal 与原有金额解析。目的地开关与 token 列表改为两列网格，开关固定第一排，五站时 token 在自己的列内换行。删除六点把手与可视排序教学，鼠标/触摸拖动改到 token 本体（长按 180ms 进入排序，删除按钮独立），保留方向键/Delete、排序后 `aria-live` 通知、跨行排序和真实触摸滚动；`aria-label` 不再指向不存在的把手。
- 改动文件：`frontend/src/features/travel/components/planning/TripPlanner.tsx`、`DateRangePicker.tsx`、`DestinationTokenField.tsx`、`frontend/src/index.css`、`frontend/e2e/home-inspiration.spec.ts`、`planner-intake.spec.ts`、`live-planning.spec.ts`、本任务第 7 节。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；完整前端单测 `npm run test` → 107 passed。
  - `npm run test -- src/features/travel/model/tripIdentityValidation.test.ts` → 3 passed；同轮相关单测合计 34 passed。
  - `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --workers=1` → 16 passed，含 2000/1440/390 几何、0/1/3/5 站、鼠标/键盘/真实 CDP touch 同排与跨行排序、14 天/跨年/DST。
  - `npx playwright test e2e/planner-intake.spec.ts --workers=1` → 7 passed，确认首页日期组件在 intake 中仍可用、手机与桌面交接不回归。
- 实屏证据：`output/polish/20261030-0108-home-form-compact/` 下 `home-2000-three-expanded.png`、`home-1440-three-expanded.png`、`home-390-three-expanded.png`、各宽 `*-five-limit.png`/`*-zero.png`、`home-390-three-more-preferences.png`；`geometry.json` 记录首排开关、控件矩形与横向溢出，`touch-orders.json` 记录真实触摸同排/跨行结果。
- 未运行/已知风险：live-planning 只更新了日期可访问名称，未运行真实付费套件。触摸排序使用 token 本体作为排序面，页面纵向滚动从 token 外的非排序区开始；长按进入排序避免和普通滑动冲突。390px 首排 token 较多时会在自身列内换行，开关仍固定第一排。
- 后端整合结论：本任务未改后端、API/SSE、地点身份、五站/14 天或预算规则；`index.css` 的既有恢复浮框/续聊/研究样式未删除。

## 8 指挥验收（指挥填写）

### 本轮独立复核 · 2026-10-30

- 结论：本项代码验收通过，待真人验收；不表示整批需求计划任务已通过或已提交。
- 本轮抽查：核对 TripPlanner 的日期/同行/预算同排与可访问名称、DateRangePicker 的14天规则未改、DestinationTokenField 的 token 排序入口及首排按钮布局；read 查看三张原反馈和 `home-1440-three-expanded.png`、`home-390-three-expanded.png`，与目标相符。
- 检查范围：沿用需求计划任务第8节“第4轮后独立复验”已运行的前端34项单测/type-check、过程21项、首页5项、intake7项、session19项及关键实屏结论；本轮纯后端排除修复未触碰前端，不重复运行，也不冒称本轮新跑。此次后端相关组合重新运行289 passed、定向Ruff及diff检查通过，但发现需求计划任务有非研究住宿展示要求重新启用被排除研究的P2，已另记返工，不属于本项视觉/交互缺陷。
- 边界：baseline存档16个哈希一致，无关恢复浮框、InputArea、followupComposer与旧任务原样保留，索引为空；本次不改产品代码、不暂存或提交。隔离dirty后的候选提交树留下一阶段独立验证，未计为通过；无真人结果，未标“已验收”。

### 第 6 轮后复核补记 · 2026-10-30

- 结论：本项仍为代码验收通过、待真人验收；需求计划任务上一轮的非研究住宿要求覆盖研究排除P2现已修复，整批未发现新的阻断项。未将任何任务标为“已验收”。
- 本轮重新运行后端相关组合293 passed、排除语义定向9 passed、Ruff及diff检查通过；两个原审查探针均通过，真实补充/批准/分派链路无住宿工具执行意图。详见需求计划任务第8节“第6轮后独立复验”。
- 本轮抽查四项任务覆盖、相关组件/断言与既有实屏；没有重跑前端单测/type-check或浏览器，先前结果仍为历史记录。baseline存档16个哈希及无关既有改动保留情况已核对；产品代码只读、index为空，未暂存/提交/推送。候选提交树交下一阶段独立验证，真实Provider端到端及真人验收未运行。

## 9 真人验收（指挥代录）
