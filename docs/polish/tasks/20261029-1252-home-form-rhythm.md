# 首页条件表单统一间距、预算输入与主按钮扫光

- 编号：20261029-1252-home-form-rhythm
- 状态：待真人验收
- 创建：2026-10-29 12:52
- 执行前先读：[工作目录 README](../README.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md

## 1 用户反馈

> 优化一下布局和行间距啊，它有点太不正常了
> 在总预算那里，它就是一个纯粹的输入框，右边不要有箭头。
> 我们的开始规划的这个扫光的动效，它实在是太快了，我们慢一点，至少慢个几倍，它现在闪得太快了

截图：output/polish/20261029-1252-home-form-rhythm/feedback-1.png。2000×880 首页条件规划，路线、日期/同行、偏好/预算三行的控件基线与间隔不一致，偏好下方至主按钮留白突兀。上一任务 20261029-1207-home-action-layout 的主按钮稳定要求继续有效。

## 2 现象与发生条件

首页“新旅行”条件模式，已有常用出发地。需兼容自然模式、首次设置、更多偏好展开及 390×844 窄屏。

## 3 根因

TripPlanner.tsx:514 起三行使用不同 Field 布局，index.css:1006–1156 的字段、偏好、预算高度与外边距分别设定；叠层双面板将自然模式较高内容高度保留给条件模式。预算为 type=number（TripPlanner.tsx:583），浏览器显示原生步进箭头。扫光 index.css:975 的 transform 过渡仅 650ms，而且在远超按钮可见范围内移动，可见扫过时间更短。

## 4 方案

目标状态：三行信息排列清晰，标签和输入基线统一；按钮仍位于双模式共享位置，留白分配自然；预算只有金额输入；扫光舒缓。

必须做：

- 调整行间距、行高和基线，合理分配条件面板空白；保留上一任务双模式卡片/主按钮坐标稳定、草稿和键盘页签。
- 预算使用普通金额文本输入和合适 inputMode，无步进/上下箭头，保留正金额校验及人民币预算语义。
- 扫光可见通过时间至少放慢 3 倍，建议约 2.8–3.2 秒，调整实际运动范围避免大部分时间在按钮外；移开鼠标不产生快速反向闪过，disabled/reduced-motion 时关闭扫光。
- 更多偏好、错误、首次出发地和窄屏无重叠裁切。

执行者自己决定：具体间距、响应断点、将隐藏面板高度怎样更自然分配，使用既有离线夹具验证。

不许碰：后端、预算规则、右侧素材、无关功能。不得覆盖既有修改；本轮基线在 output/polish/20261029-1252-home-form-rhythm/baseline/。不提交、不推送。

## 5 停下来报告的情况

无额外条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 三行标签、输入及偏好/预算视觉对齐，间距自然，无明显一块空白集中在按钮上方。
2. 同草稿同视口切模式，卡片与主按钮坐标差 <2px。
3. 金额输入无箭头，非法金额仍拒绝；扫光可见速度变慢且减少动画偏好下关闭。

### 6.2 必须运行的检查

frontend 下 npm run type-check；离线 home-inspiration.spec.ts 定向回归。新增金额校验或动画检查并入现有用例，不为纯文案另建测试。

### 6.3 实屏证据（执行者提供）

2000×880、1440×900、390×844 两模式，至少一张更多偏好展开；坐标证据和扫光 CSS/实屏观察记录。存本任务 output 目录。

### 6.4 真人验收（用户操作）

1. 切两种模式 → 主按钮不跳动，条件表单行间距均匀。
2. 输入预算、悬停开始规划 → 无上下箭头，扫光明显更慢。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 13:25 · pi 编码代理

- 改动摘要：把首页条件表单三行改为统一标签基线、20px 行距和底部收口；预算改为普通文本金额输入，用共享解析函数校验正金额并接受千位分隔符；主按钮扫光改为约 3 秒、按按钮宽度完整扫过，disabled 与 reduced-motion 关闭。双模式共享高度和主按钮坐标继续由同一卡片网格维持。
- 改动文件：`frontend/src/features/travel/components/planning/TripPlanner.tsx`、`frontend/src/features/travel/components/planning/PlaceField.tsx`、`frontend/src/features/travel/model/tripIdentityValidation.ts`、`frontend/src/features/travel/model/tripIdentityValidation.test.ts`、`frontend/src/index.css`、`frontend/e2e/home-inspiration.spec.ts`。另仅把 `frontend/src/features/travel/components/planning/DiscoveryToIntake.tsx`、`frontend/src/features/settings/pages/UserPreferencesPage.tsx` 的 `PlaceField` 导入路径改为新文件；两文件除该导入外的差异是工作区既有改动，不计入本轮。
- 偏离方案及理由：把 `PlaceField` 提取为独立文件，避免后续“首页内展开确认”形成 `TripPlanner` 与 `GuidedIntakeQuestions` 的循环依赖；预算解析抽成纯函数便于边界测试。未改后端与预算规则。
- 实际运行的检查与结果：`npm run type-check` 通过；`npx vitest run src/features/travel/model/tripIdentityValidation.test.ts` 通过（3 项）；`JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --workers=1` 通过（12 项，含金额输入属性、双模式几何、扫光时长与 reduced-motion 断言）。
- 实屏证据：`output/polish/20261029-1252-home-form-rhythm/home-2000-structured.png`、`home-2000-natural.png`、`home-2000-more-preferences.png`、`home-1440-structured.png`、`home-1440-natural.png`、`home-390-structured.png`、`home-390-natural.png`；扫光伪元素实测 `animationName=planner-main-sweep`、`animationDuration=3s`，减少动态效果时为 `none`。
- 遗留问题或需要指挥决定的事：无。目的地微交互的最终手感留在目的地标签任务，按用户要求交体验讨论。


## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 指挥

- 结论：通过，转待真人验收。
- 核对：以本轮 baseline 的 TripPlanner/index.css 和首页测试为基线检查，预算为 text/decimal 输入并保留正金额校验；扫光改为 3s 且运动范围与按钮宽匹配，移开无反向过渡，disabled/reduced-motion 关闭。PlaceField 提取用于解除卡内确认引入的循环依赖，属于合理的结构调整。
- 实屏：已逐张查看 2000/1440/390 双模式和更多偏好截图；标签、行间距及风格/预算对齐符合本轮目标，窄屏通过页面纵向滚动容纳完整表单，无横向溢出。
- 指挥抽查：`cd frontend && JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/home-inspiration.spec.ts --grep '双模式共享稳定主按钮|目的地标签' --workers=1 --output=../output/polish/20261029-1252-home-form-rhythm/commander-review`，2 passed（14.1s）。其中几何用例覆盖三视口卡片/按钮差 <2px、金额输入与扫光偏好；目的地细项结论在独立任务记录。
- 真人步骤：按第 6.4 节核对条件表单行间距、两模式按钮位置、预算输入和悬停扫光。

## 9 真人验收（指挥代录）
