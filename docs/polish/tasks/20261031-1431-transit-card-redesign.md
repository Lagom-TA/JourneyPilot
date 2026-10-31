# 公共交通卡片：线路、换乘链与整卡跳转

- 编号：20261031-1431-transit-card-redesign
- 状态：待代码验收
- 创建：2026-10-31 14:31
- 执行前先读：[工作目录 README](../README.md)、[行程结果页视觉方向](../references/20261029-itinerary-redesign.md) 第 3.4 节、frontend/README.md、frontend/e2e/README.md、docs/invariants.md、AGENTS.md；关联任务 [transport-display](20261029-1917-transport-display.md)、[transit-route-facts](20261029-1917-transit-route-facts.md)

## 1 用户反馈

用户原话（2026-10-31）：

> 我们的目前的这个公共交通体系啊，它是不是应该给一些更详细的信息，比如说我们哪个线路，什么方向，对吧？我觉得我们对于交通这个部分的指示块的设计要更加的现代化，更加的简洁、高效、优美。
>
> 还有就是说啊我们在给有关于这个地铁相关的路径的时候，我们这几段路径是不包含步行的，我们只有换乘才说路径。就是你从哪个地方走到地铁站，再从地铁站走到另一个地方，这个是不算在地铁范围内的。只有地铁包含换乘的时候，我们才这么说。比如说一个地铁，它如果是直达的，那我们就不显示其他的路径，如果说他中间需要换乘，然后我们再说，并且我们不同的线路是有不同的名称的，不只是地铁、有轨电车、公交车等等。我们在换乘的时候应该显示一个比较简约的，比如说从一条线路的名称，然后一个箭头到另一条线路，就代表着它有换乘，然后用户点击就可以看这两段的信息。
>
> 还有就是我们对于空间的利用实在是太差了，也不好看，也不美观。你弄那么大一块，然后显示很少的信息，让用户感觉空荡荡的，非常的丑。
>
> 还有就是我们不需要单独地查看路线的按钮啊，任何一个都不需要啊，你只要点击这个块，它不就应该自动跳转到这个部分吗？

截图 `output/polish/20261031-1431-transit-card-redesign/feedback-1.png`：第 N 天日程中的“有轨电车”卡片，头部只有“有轨电车”，主行“东安门大街 → 神武门”，下方“38 分钟 / ¥2”，展开“收起路线步骤”后依次显示步行、有轨电车（103路(北京站西--动物园枢纽站)）、步行三段；卡片下方另有橙色“查看路线”按钮。

## 2 现象与发生条件

已交付行程的交互日程（interactive itinerary）中，公共交通 leg 的卡片。数据包含步行接驳段与乘车段，乘车段有 `line_name`（如“103路(北京站西--动物园枢纽站)”或“地铁2号线”）。桌面视口（截图约 1200px 宽）与 390px 手机视口均出现。高铁、飞机、出租车等非公共交通不在重新设计范围，但“查看路线”按钮的移除适用于所有交通卡片。

## 3 根因

- 首屏只显示交通方式，不显示线路。`TransportLegCard.tsx:270-279` 的 `TransitCard` 通过 `CardShell` 使用 `transitModeLabel`（`transportPresentation.ts:49-52`），该函数只把 `metro/bus/tram` 映射为“地铁/公交/有轨电车”；线路名只在展开后的 `SegmentRow` 的 `MetaLine`（`TransportLegCard.tsx:44-51`）出现。`legService`（`transportPresentation.ts:233-244`）只被 `scheduled` 族使用（`TransportLegCard.tsx:195`），公共交通没有消费线路身份。
- 步行被当作路线步骤。`SegmentDisclosure`（`TransportLegCard.tsx:55-71`）在 `leg.segments.length > 1` 时把全部 `leg.segments` 渲染为“路线步骤”，没有过滤 `walk/bike`；因此“步行→乘车→步行”会显示 3 个步骤，直达也出现展开入口。
- 换乘没有线路链。`legSummary`（`transportPresentation.ts:169-178`）只输出“换乘 N 次”，`confirmedMetroTransferCount`（`:183-207`）只统计纯地铁的线路变化；没有“线路A → 线路B”的呈现，也没有把混合公交的线路名展示出来。
- 卡片空间利用率低。`TransitCard` 依次渲染头部、`TransitStationLine`、带 `border-t` 的 `LegSummaryRow`、`SegmentDisclosure`（`TransportLegCard.tsx:270-279`）；外层 `journey-transport-card` 又加一层 `padding: 13px 15px` 和边框（`index.css:3431`），`journey-place-card` 的交通行还有 13px 上下内边距（`index.css:3429`）。信息少、容器多、留白大。
- 独立按钮。`ItineraryCardFlow.tsx:109` 的 `routeActionVisible` 只对交通使用 `transportRouteActionVisible`（`transportPresentation.ts:225-227`，仅隐藏高铁/飞机），`:180-186` 在卡片外渲染“查看路线”按钮并调用 `selectOnMap`；卡片本身只有悬浮联动（`:132-143`），没有点击/键盘选择。
- 已有可复用的选择链路：`ItineraryCardFlow.tsx:112-120` 的 `selectOnMap` 会带上 `entityId/occurrenceKey/day/entityType`，`DeliveryWorkspace.tsx:409-420` 的 `handleCardSelect` 会打开路线图层并在手机端关闭日程面板；`restorePlaceFocus`（`:182-201`）依赖 `[data-map-focus-trigger]` 恢复焦点。移除按钮时必须把该属性与可聚焦能力放到卡片上。

## 4 方案

目标状态：公共交通卡片像一条紧凑的交通行程条。首屏直接读到线路身份与方向、上下车站、时间/时长/费用；有换乘时用“线路A → 线路B”表示，点击线路链才展开各乘车段；步行不出现在路线步骤里；整张卡片可点击跳转到地图对应路线，不再有单独的“查看路线”按钮；卡片在桌面和 390px 手机上都紧凑、不空荡、不横溢。沿用现有暖纸面、字体与交通方式色，不引入新的视觉体系。

密度目标（示意，不是逐像素合同）：

```text
直达（步行 + 乘车 + 步行）：
┌──────────────────────────────────────────────────────────┐
│ [tram] 103路 · 往神武门                     09:00–09:38  │
│ 东安门大街 → 神武门                    38 分钟      ¥2   │
└──────────────────────────────────────────────────────────┘

换乘：
┌──────────────────────────────────────────────────────────┐
│ [metro] 2号线 → 4号线                       15:00–15:38 │
│ 北大街站 → 大雁塔站                    38 分钟      ¥6   │
│   2号线  北大街站 → 小寨站   16 分钟 · 3.8 公里           │
│   4号线  小寨站 → 大雁塔站   22 分钟 · 3.8 公里           │
└──────────────────────────────────────────────────────────┘
```

必须做：

1. **首屏线路与方向**
   - 对 `transit` 族（metro/bus/tram）从 `leg.segments` 提取乘车段（排除 `walk`、`bike`），按顺序得到线路链。
   - 线路标签优先使用 `service_number`，其次 `line_name`；两者都没有时退回 `TRANSPORT_MODE_LABELS[mode]`。不得编造线路名。
   - 单段乘车：首屏显示线路标签与方向；方向取该乘车段的到达站（优先下一乘车段的 `from_endpoint.name`，最后一段用 `alighting_stop.name`）；如果这些都不是已证实站点，则省略方向，不用 POI 或接驳端点补位，也不从字符串猜测线路终点。
   - 多段乘车：首屏显示“线路A → 线路B（→ 线路C）”的线路链，箭头表示换乘/衔接；每段的完整方向、上下车站、时长/距离/运营方在展开行中可读。线路链必须使用线路名（如“地铁2号线 → 公交5路”），不能只写“地铁 → 公交”；缺线路名时才退回方式名。
   - 保留现有 `boarding_stop → alighting_stop` 的站点事实；没有正式站点时不要用 POI 或接驳端点补位。

2. **只展示乘车段的路线步骤**
   - `SegmentDisclosure` 只消费乘车段。直达（1 个乘车段，无论前后有多少步行段）不显示展开入口，也不显示任何路线步骤。
   - 同一线路被 Provider 拆成多段时不产生线路链/换乘；连续相同线路合并为一项。线路身份缺失时不推断换乘；只有两端都有可核实的线路名且不同才算换乘。
   - 多个乘车段（不同线路或不同方式）才显示线路链与展开入口；展开后只列乘车段，不列步行/骑行段。每行至少包含线路标签、该段方向、上车站 → 下车站；有数据时再显示出发/到达时间、时长、距离、运营方。
   - 混合公交（地铁+公交等）按线路链展示，不把通用服务换乘数写成“地铁换乘 N 次”；纯地铁的真实换乘才保留换乘含义。线路链已经表达换乘时，不再重复“换乘 N 次”文案。
   - 保留 `route_status` 的 pending/unavailable 提示与无价格、无时长时的省略规则；保留 `IntentExplanationList`、`TransportProviderNote`、`LegBadge` 等有意义的来源/状态信息，紧凑化不能删除事实。

3. **紧凑、现代的空间利用**
   - 交通卡片只保留一层紧凑容器；去掉外层与内层重复的边框/内边距（`journey-transport-card` 与 `CardShell`/`journey-place-card` 的叠加留白），不要出现“大块空白只放几行字”。
   - 首屏合并为紧凑的两行左右布局：左侧线路链/方向与上下车站，右侧时间范围、时长、费用；用水平空间承载信息，不再用多条 `border-t` 分隔行和独立摘要行。
   - 展开的乘车段用紧凑行呈现，避免大图标、重复标题和多余分隔线。
   - 390px 下自然换行，不横向溢出；桌面主验收尺寸下信息不挤在窄列里。

4. **整卡跳转地图，移除按钮**
   - 删除所有交通卡片的“查看路线”按钮（包括 `journey-card-actions` 中交通分支），不再保留 `transportRouteActionVisible` 的交通按钮逻辑。
   - 对原本有“查看路线”入口的交通 leg（公共交通、道路、自行前往等，排除高铁/飞机），整张卡片成为地图入口：鼠标点击/触摸、Enter/Space 均可触发与旧按钮相同的 `onSelectEntity` 选择；有 `cursor: pointer` 与可见的 focus 反馈；提供包含线路/站点信息与地图动作的可访问名称，避免只写“在地图中查看”而覆盖卡片内容。
   - 高铁/飞机保持既有展示与无路线入口，不因本任务变成可点击；它们原本就没有按钮，移除按钮不影响其行为。
   - 卡片内的换乘线路链、展开控件、来源说明等嵌套交互：点击它们只执行自身动作，不触发整卡跳转（阻止冒泡）；键盘焦点顺序与 `aria-expanded`/`aria-controls` 正确。
   - 把 `data-map-focus-trigger` 放到卡片本身（或卡片内等价的唯一焦点目标），保证关闭地图详情后 `restorePlaceFocus` 仍能聚焦回卡片。
   - 地图详情面板里的同一张卡片（`TimelineEntityDetails`）已经是选中项，不重复做地图入口；没有传入选择回调的其他调用点保持非交互。不可绘制路线的交通卡片不显示按钮，也不做点击入口。

执行者自己决定：

- 线路链的视觉形式（线路徽标、模式色、箭头样式）、方向文案的措辞与省略策略、长线路名（如 `103路(北京站西--动物园枢纽站)`）在首屏是否省略括注、完整名称放在展开行的位置。
- 组件拆分（例如新增 `TransitLineChain`/`TransitRideRow`）、CSS 类名、是否保留 `legSummary` 的换乘字段、单测与 e2e 的具体断言。
- 是否在总时长旁用极轻的方式说明“含步行”，只要不把步行列为路线步骤、不增加视觉噪音。

不许碰：

- 后端路线事实、Provider 选择、公开 API/SSE 契约、费用/预算规则、真实用户数据、地图投影与路线几何。
- 不得编造线路名、方向、终点站、换乘次数或站名；缺数据时省略。
- 不改动与本任务无关的页面；保留工作区中 `frontend/src/index.css` 等文件已有的其他未提交改动。

依赖与所有权：本任务改变 `20261029-1917-transport-display` 已实现的公共交通卡片分段/按钮/换乘呈现；高铁与飞机的既有展示保持不变。执行时以本任务为准，旧任务中与公共交通卡片冲突的 e2e 断言需要同步更新。相关文件：`TransportLegCard.tsx`、`transportPresentation.ts`、`ItineraryCardFlow.tsx`、`index.css`、`transportPresentation.test.ts`、`session-state.spec.ts`、`xianBundle.ts`。

## 5 停下来报告的情况

- 现有数据在用户场景（有轨电车/公交/地铁）里没有可用的 `line_name`/`service_number`，导致首屏无法显示线路身份；报告缺失字段，不用方式名假装线路名。
- 整卡点击与换乘展开、焦点恢复或地图选择契约发生冲突，必须改 `DeliveryWorkspace` 的选择语义才能成立。
- 390px 下无法在不隐藏事实的前提下保持紧凑，需要产品取舍。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 公共交通首屏出现线路身份（`service_number`/`line_name`）与方向；有线路名时不出现“地铁/公交”单独作为标题；缺线路名时退回方式名且不编造。
2. 直达（步行+乘车+步行）没有展开入口、没有任何步行步骤；多个乘车段才出现线路链，展开后只有乘车段。
3. 同线路拆段不产生换乘链；混合公交按线路链显示且不冒充纯地铁换乘；纯地铁真实换乘的线路链与 `confirmedMetroTransferCount` 一致。
4. 所有交通卡片都没有“查看路线”按钮；原本有该入口的交通卡片可点击/键盘选择，手机端打开地图；高铁/飞机保持无路线入口；点击换乘链不会触发地图选择；关闭地图详情后焦点回到卡片。
5. 卡片只有一层紧凑容器，首屏信息在两行内可读，桌面无大块空白；390px 无横向溢出。
6. `route_status`、站点事实、费用缺失、无时长等既有规则未被破坏。

### 6.2 必须运行的检查

在 `frontend/` 下：

- `npm run type-check`
- `npm run test -- src/features/travel/model/transportPresentation.test.ts`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'mixed transport display|desktop itinerary' --workers=1`（端口按实际 Vite 服务替换；不调用 Provider）

扩展或新增 `transportPresentation` 单测：步行过滤、同线合并、不同线路链、缺线路名回退、直达无展开、混合公交不冒充地铁换乘。更新 e2e 中旧的“展开 3 个路线步骤”“查看路线”断言，改为线路链/整卡点击断言。

### 6.3 实屏证据（执行者提供）

1440×960 与 390×844，各覆盖：

- 步行 + 单段乘车 + 步行（如截图中的有轨电车 103 路，含长线路名）；
- 两段地铁换乘（收起与展开两种状态）；
- 地铁 + 公交混合；
- 无线路名/无价格/route pending 或 unavailable 的降级状态。

要能看到：首屏线路与方向、无“查看路线”按钮、点击卡片后地图详情出现、点击换乘链只展开不跳图。保存到 `output/polish/20261031-1431-transit-card-redesign/`。

### 6.4 真人验收（用户操作）

1. 打开含直达有轨电车/地铁的一天 → 卡片首屏能读到线路和方向，没有展开步骤，也没有“查看路线”；点击卡片 → 地图选中并显示该路线。
2. 打开含地铁换乘的一天 → 首屏显示“线路A → 线路B”；点击线路链 → 只展开两段乘车信息，没有步行；点击卡片其他位置 → 地图跳转。
3. 看桌面与手机 → 卡片紧凑、不空荡、不横向滚动；换乘链和费用/时长不挤在一起。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-31 15:10 · ZCode / DeepSeek V4.1 Flash

- 改动摘要：
  - 公共交通首屏改为紧凑两行：第一行线路身份/方向与时间范围，第二行上下车站与时长/费用。线路标签优先 `service_number`，其次 `line_name`，缺失时退回方式名；线路名末尾的端点括注在首屏省略，完整名称保留在展开行。
  - 新增乘车段与线路链模型：过滤步行/骑行，按顺序提取乘车段；同线拆段或线路身份缺失时合并，不推断换乘；只有不同线路或不同方式才显示“线路A → 线路B”和展开入口。方向取下一乘车段的上车站，最后一段取 `alighting_stop`；缺少已证实站点时省略。
  - 公共交通不再把步行/骑行列为路线步骤；直达无展开入口；展开后只列乘车段（线路、方向、上下车站、时间、时长、距离、运营方）。移除卡片中的“换乘 N 次”文案，`confirmedMetroTransferCount` 保留并用单测保证纯地铁线路链与换乘数一致。
  - 删除所有交通卡片的“查看路线”按钮；公共交通、道路、自行前往与其他交通的整张卡片成为地图入口（点击/触摸/Enter/Space），带 `cursor: pointer`、焦点环与包含线路/站点/费用的可访问名称。高铁/飞机保持既有展示与无路线入口。线路链与展开控件阻止冒泡，`aria-expanded`/`aria-controls` 正确；`data-map-focus-trigger` 放在卡片容器，关闭地图详情后焦点回到卡片。
  - 交通卡片压缩为单层容器并减小内外重复内边距与间距；桌面两行密度提升，390px 自然换行且无横向溢出。
  - 离线夹具新增 103 路有轨电车（长线路名）、无线路名、route pending 三种场景；更新 e2e 断言与证据截图。
- 改动文件：
  - `frontend/src/features/travel/model/transportPresentation.ts`
  - `frontend/src/features/travel/model/transportPresentation.test.ts`
  - `frontend/src/features/travel/components/workspace/TransportLegCard.tsx`
  - `frontend/src/features/travel/components/workspace/ItineraryCardFlow.tsx`
  - `frontend/src/index.css`
  - `frontend/e2e/fixtures/xianBundle.ts`
  - `frontend/e2e/session-state.spec.ts`
- 偏离方案及理由：
  - 混合公交首屏不再给上下车站加“地铁/公交”前缀：线路链已逐段标明方式与线路，站点行去掉前缀可减少重复并保持两行紧凑；对应旧 e2e 断言已更新。
  - `legSummary` 不再输出换乘字段；换乘由线路链表达，避免与“线路A → 线路B”重复。`confirmedMetroTransferCount` 仍保留，并用单测保证纯地铁场景与线路链一致。
  - route pending/unavailable 卡片继续只显示方式名与状态文案，不展示未就绪的线路/站点事实，保留既有降级语义。
  - 长线路名的端点括注只在首屏省略，完整名称在展开行展示；直达没有展开行，因此首屏只显示简称（如“103路”），属于任务允许的首屏取舍。
  - 高铁/飞机之外的班次交通（普通火车、长途巴士、轮渡）原本有“查看路线”，现按任务改为整卡地图入口；高铁/飞机严格保持无入口。
- 实际运行的检查与结果：
  - `cd frontend && npm run type-check`：通过。
  - `cd frontend && npm run test -- src/features/travel/model/transportPresentation.test.ts`：27 个测试全部通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'mixed transport display|desktop itinerary' --workers=1`：4 个测试全部通过（14.2s）。覆盖首屏线路/方向、直达无展开、换乘链仅含乘车段、混合公交不冒充地铁换乘、无线路名/无价格/pending 降级、无“查看路线”、整卡点击与 Enter 打开地图、线路链只展开不跳图、关闭详情后焦点回到卡片、390px 无横向溢出。
  - `cd frontend && npm run test`：19 个文件、161 个测试全部通过（额外运行）。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：55 个测试全部通过（额外运行，1.7m）。
  - 全程使用离线夹具与已运行的 8088 Vite，外部瓦片被拦截，未调用真实模型、Provider 或真实会话。
- 实屏证据：
  - `output/polish/20261031-1431-transit-card-redesign/transit-desktop-1440.png`：1440×960，飞机/高铁/直达地铁/换乘（收起）/混合。
  - `.../transit-transfer-collapsed-1440.png`、`.../transit-transfer-expanded-1440.png`：两段地铁换乘收起与展开。
  - `.../transit-tram-1440.png`：103 路有轨电车直达（长线路名简称、无展开）。
  - `.../transit-degraded-1440.png`：无线路名、无价格、route pending。
  - `.../transit-map-detail-1440.png`：点击卡片后地图详情出现。
  - `.../transit-phone-390.png`：390×844，换乘链展开。
  - `.../transit-tram-phone-390.png`、`.../transit-degraded-phone-390.png`：手机直达电车与降级状态。
  - `.../transit-map-detail-phone-390.png`：手机点击卡片关闭面板并显示地图详情。
  - 已逐张查看；卡片为单层容器、两行首屏，桌面无大块空白，390px 无横向溢出。
- 遗留问题或需要指挥决定的事：无。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
