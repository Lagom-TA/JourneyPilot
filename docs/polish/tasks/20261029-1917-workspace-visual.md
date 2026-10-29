# 加宽行程面板，重排全程目录与开放式日标题

- 编号：20261029-1917-workspace-visual
- 状态：待真人验收
- 创建：2026-10-29 19:17
- 执行前先读：[工作目录 README](../README.md)、[本轮参考与布局方向](../references/20261029-itinerary-redesign.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md、AGENTS.md

## 1 用户反馈

> 这5个卡片太丑了，我们需要优化。
>
> 这个天气放在右上角，也就是和我们的第一天日期、周几、地址放在同一排。还有就是我们的第一天都不要用这个卡片的东西来写，太公式化了，太丑了。你还是要继续去调研这些网站，找一些适合我们这种旅行场景的，非常好看的、惊艳的这种视觉设计。我们左边的这一整块啊这个信息面板区域，可以宽度更多，我给你更多的空间，你效果要好。视觉效果要好
>
> 以下是关于界面布局框架的一些参考网站，你来好好给我收集一下，多多学习，我们的界面现在太丑了

14 个参考站名称、URL、本次访问结果及可用结论完整收录于本轮参考文档。

- `output/polish/20261029-1917-workspace-visual/feedback-1.png`：4096×1800，左侧五张等样式天卡片，地图占据绝大部分空间。
- `output/polish/20261029-1917-workspace-visual/feedback-2.png`：单日顶部被包在圆角卡内；天气因宽度与布局落在标题下面，红箭头要求移到日期行右端。

## 2 现象与发生条件

已完成旅行的“全程”与某天日程视图。参考截图包含 5 天北京／上海行程。用户明确允许加宽桌面信息面板，要求沿用现有行程工作台提高视觉质量。移动端仍需可读可用。标题自然化归 `natural-titles`，本任务可用样例标题验版，不自行在前端生成正式标题。

## 3 根因

- `frontend/src/index.css:2887` 的 `.journey-floating-panel` 固定 420px，`:3024` 大屏也只有 440px；`:2904` 起全程行再次加描边、底色与内边距，形成连续的同质卡片。
- `frontend/src/features/travel/components/workspace/DaySummaryCard.tsx:48` 紧凑模式把彩色日序胶囊、元信息、长主题和角箭头挤在窄行，旅行内容缺少主次。
- `frontend/src/features/travel/components/workspace/DayHeader.tsx:15` 把日期／主题放入同一内部左列、天气作为整个左列的并列子项；外部还有圆角描边和背景。宽度不足时天气掉到标题下，不能保证与日期对齐。
- `frontend/src/index.css:3225` 起日程统一大卡片；`:3279` 交通再用虚线框与通用标题，内容语义被同一套框线压平。
- 加宽还涉及 `DeliveryWorkspace.tsx:524` 的固定 `overlayOffset=460`、`index.css:2912` 的地图控件 left 常量；只改面板宽度会使地点被遮挡或控件重叠。

## 4 方案

目标状态：暖纸旅行刊物的阅读层级，配合稳定的大地图。全程是按天的连续目录；单日有开放式页头和清楚的时间顺序；用户第一眼看到真实安排。

必须做：

- 以本轮参考文档第 3 节和本地布局稿作为方向，明显重做五天概览与日标题，不能只改边框颜色／圆角。
- 桌面增加信息面板宽度：2000px 约 600–640px，1440px 约 560px，1280px 约 520px 是起始建议；执行者据实屏微调。保留足够地图可视区域，宽度不能在断点处遮挡地图操作。
- 面板宽度、地图控件避让、相机 padding／offset 使用一致的布局依据。清理与本任务相关的旧宽度常量，不能复制更多相互独立的固定偏移值。
- 全程行使用日序、日期／城市、自然标题和必要地点线索建立层级；去掉五张独立圆角描边的卡片堆叠。整行明确可点击，键盘可激活，当前日与 focus-visible 清楚。
- 日头移除自身卡片外框、独立底色和过大的容器感。第一行“第 N 天、日期、周几、地点”，天气在同一行右端；主题另起一行。该规则适用于所有天，不只第一天。
- 桌面 1280／1440／2000px 的常见短地点名应同排；极长地名或窄屏允许有序折行，不隐藏重要元信息，不把字缩到不可读。
- 时间线弱化通用卡片重复边框，让地点与衔接自然连读；交通视觉留出单一标题行、站名和左时长／右费用，给后续 `transport-display` 接入。保留真实有意义的详情入口、来源与必要状态。
- 继续沿用同一工作台、全程↔单日、阅读／PDF／旅中／调整、历史只读和减少动态效果能力。地图保持同一实例；不新增整页确认或结果路由。
- 对 1／5／14 天、长标题、无天气、历史天气与季节参考、全程返回滚动与焦点做定向核对。天气语义和来源标签不因视觉精简变成精确预报。

执行者自己决定：最终字级与留白、目录线条、日序样式、地点活动是否采用开放时间线或局部容器、具体断点。可超越布局稿的细节，但要说明并提供更好的实屏结果。无需采购字体、图片或新组件库。

不许碰：后端、公开 API/SSE、正式 Bundle 事实、价格／预算／天气业务语义、生成与审批页面、Logo 和无关页面。不能用纯前端模板替换正式行程标题。保留既有工作区改动；不提交不推送。

依赖与所有权：先完成 `hover-intent`；本任务拥有本轮前端布局阶段的 DeliveryWorkspace、DaySummaryCard、DayHeader、ItineraryCardFlow 与相关 CSS。完成后再执行 `transport-display`；`natural-titles` 的前端标题优先级改动应串行交接。

## 5 停下来报告的情况

若需要新增服务端字段才能完成纯布局，先提供现有字段不足的证据。用已有天气／主题／节点数据改版、改变内部布局与测量方式均在授权范围内，不构成停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 五张同质卡片已变为有清楚阅读层级的日目录；日期与主题不争抢同一视觉层级。
2. 日头没有独立圆角卡／描边背景；桌面天气位于日期行右端，长文案与缺失数据不破版。
3. 面板宽度增加，地图控件和选中地点正确避让；仍能看地图、切日和打开详情。
4. 1／5／14 天均可读可操作；390px 无横向溢出，键盘焦点与返回恢复正常；普通悬浮不带来相机移动。
5. 没有不使用的新样式／组件或与旧设计并存的双路径；没有把本地布局稿的占位说明带进产品。

### 6.2 必须运行的检查

在 `frontend/` 下：

- `npm run type-check`
- `npm run test -- src/features/travel/model/mapModel.test.ts src/features/travel/model/mapPlaces.test.ts src/features/travel/model/workspaceTransition.test.ts`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'desktop itinerary|mixed transport|reading and map|phone sheet|phone card selection' --workers=1`
- `VITE_OUT_DIR=../output/polish/20261029-1917-workspace-visual/build npm run build`

在现有离线夹具里增加 5／14 天、长主题与缺少天气的布局场景；仅保留能证明天气同行、无溢出、点击与地图避让的必要检查，不为每条 CSS 写镜像测试。端口按实际 Vite 服务替换，不调用真实 Provider。构建不要覆盖已有 backend/static 产物。

### 6.3 实屏证据（执行者提供）

- 2000×880：5 天全程、选中某天后的页头与交通／地点内容。
- 1440×960 和 1280×900：天气与日期同行、地图控件和定位避让。
- 390×844：全程、单日，焦点与滚动可达；14 天滚动、长标题／无天气可合并记录。
- 所有截图用同一批离线数据，保存本任务 output；逐张自看后交验。布局稿截图只是方向，不能替代执行后截图。

### 6.4 真人验收（用户操作）

1. 打开全程 → 左侧更宽，五天像连续目录，能一眼分清日期、标题和地点。
2. 点击第 1 天及其他天 → 页头没有单独卡片；天气与日期、周几、地点同行靠右，安排自然向下展开。
3. 切日、返回全程、在地图查看、打开阅读版再返回 → 操作稳定；地图不被加宽面板挡住，悬浮不乱跳。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 21:54 · OpenPI / GPT-5.5

- 改动摘要：桌面信息面板改为 1280px 520px、1440px 560px、2000px 640px；面板实际右缘同时驱动地图控件左边界与相机 overlayOffset，移除旧 420/440/464/484/460 常量。全程概览改为连续日目录：大号日序、日期／周几／城市、自然标题与地点线索，不再使用五张同质圆角卡。日头移除卡片底色和描边，第一行统一为“第 N 天 · 日期 · 周几 · 地点”，天气同排靠右，主题另起一行；长标题自然换行。单日日程改为左侧时间／节点、右侧内容的开放式时间线，减少重复外框；交通保留单一容器层次，内部字段留给后续任务。阅读版复用同一日头样式。离线夹具新增 1／5／14 天、长标题、混合天气与无天气场景，并新增布局证据检查。
- 改动文件：
  - `frontend/src/features/travel/components/workspace/DeliveryWorkspace.tsx`
  - `frontend/src/features/travel/components/workspace/BundleMapLeaflet.tsx`
  - `frontend/src/features/travel/components/workspace/DaySummaryCard.tsx`
  - `frontend/src/features/travel/components/workspace/DayHeader.tsx`
  - `frontend/src/features/travel/components/workspace/DayOrdinalChip.tsx`（删除，已无引用）
  - `frontend/src/features/travel/components/workspace/TripOverview.tsx`
  - `frontend/src/features/travel/components/workspace/ItineraryCardFlow.tsx`
  - `frontend/src/features/travel/components/workspace/WeatherStrip.tsx`
  - `frontend/src/index.css`
  - `frontend/e2e/fixtures/xianBundle.ts`
  - `frontend/e2e/session-state.spec.ts`
- 偏离方案及理由：相机聚焦偏移的既有 e2e 断言原为固定 230px，已改为从面板实测右缘推导，避免测试复制布局常量；`MapViewport` 在面板宽度变化后按新 overlay 重新适配无选中项的视野。天气徽标取消灰底，但保留天气语义、数据时效按钮与历史／季节标签。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/travel/model/mapModel.test.ts src/features/travel/model/mapPlaces.test.ts src/features/travel/model/workspaceTransition.test.ts`：3 个文件、23 个测试全部通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'desktop itinerary|mixed transport|reading and map|phone sheet|phone card selection' --workers=1`：8 个测试全部通过（15.1s）。
  - 追加运行 `--grep 'phone itinerary layout evidence'`：14 天无天气与 1 天布局 2 个测试通过；14 天场景将移动 Sheet 展开到 92% 后滚动到最后一天并返回，焦点恢复通过。
  - `VITE_OUT_DIR=../output/polish/20261029-1917-workspace-visual/build npm run build`：构建成功，产物写入本任务 output，未覆盖 `backend/static`。
- 实屏证据：`output/polish/20261029-1917-workspace-visual/overview-2000.png`、`day-2000.png`、`day-1440.png`、`day-1280.png`、`phone-overview-14.png`、`phone-day-14.png`、`phone-day-1.png`。均使用本地离线夹具并拦截外部请求，已逐张查看。
- 遗留问题或需要指挥决定的事：交通内部字段、重复标签与操作仍是既有 `TransportLegCard` 内容，按依赖留给 `transport-display`；本任务只完成了容器层次与单行标题区域，未改交通字段语义。

## 8 指挥验收（指挥填写）

### 集成验收 · 2026-10-29

通过。已查看最终桌面 2000／1440／1280 与手机 390 的布局及长标题／1／5／14 天证据；实测面板宽度与地图控件／相机避让同源，日目录去重复卡片，日头开放、天气同行靠右。最终前端类型检查、39 项单测、13 项定向浏览器检查及构建通过。最终集成外观见 output/polish/20261029-1917-batch/final-overview-2000.png、final-day-2000.png；截图为离线夹具，不代表真实地图 Provider 或模型文案质量。

本机服务已重启，8001 与 8080 就绪接口均 HTTP 200、status=ready。工作区既有改动保留，未提交、未推送。

## 9 真人验收（指挥代录）
