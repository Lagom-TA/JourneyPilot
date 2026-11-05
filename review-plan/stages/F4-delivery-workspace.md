# F4 交付工作台

`前端页面` · 前置 [F1](F1-frontend-foundation.md)、[B3](B3-planning-delivery.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/components/workspace/`：`DeliveryWorkspace`、`TripOverview`、`DaySummaryCard`、`DayHeader`、`ItineraryCardFlow`、`DayTimeline`、`TravelEntityCards`、`TransportLegCard`、`TransportProviderNote`、`WeatherStrip`、`BundleMapLeaflet*`、`FullReportView`、`TripFactReadout`、`IntentExplanationList`、`TimelineNodeMark`
- 对应的 `frontend/src/features/travel/model/` 和 `frontend/src/features/travel/types/`

已实现地图画幅＋旅程对页：全程以地图主导，单日展开对页，以大胆构图和克制表达形成视觉冲击。见 [设计方案](../F4-design-options.md)与 [验收记录](../F4-acceptance.md)。代码提交：`047bbd2`。

## 截图清单

⭐ 为[展示镜头](../analysis.md#达标线)。下表保留状态清单，进度只记本轮代表样本的覆盖，不表示全部组合均已重跑；按作者要求控制检查范围。素材入口为 `output/review/F4/manifest.md`。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| D1 ⭐ 全程总览 | 1 天；4–7 天；14 天；标题很长；含“尚未安排” | 全部 + B | ✅ 代表布局已复核 |
| D2 每日卡片 | 景点；餐饮；跨夜住宿；自定义项；详情展开；“在地图查看” | M、D、W | ✅ 单日、展开与联动已复核 |
| D3 交通卡 | 铁路和航班班次；公共交通（线路链、乘车明细展开）；驾车；步行和骑行；短距离接驳；路线更新中；路线不可用；方式已锁定；数据来源弹层；路线步骤展开 | M、D | 📸 铁路、来源；未重跑全部交通类型 |
| D4 天气 | 预报；降雨；季节参考；新鲜度展开；没有天气 | M、D | 📸 季节参考；未触发真实刷新 |
| D5 ⭐ 地图 | 加载中；底图失败降级；没有数据；当天没有可定位的地点；选中地点后的详情卡；卡片悬停联动；堆叠图钉展开；图层弹层；按天切换；地图模块加载失败 | 全部 | ✅ 代表布局、无数据、瓦片失败、聚合与联动已复核 |
| D6 旅中查看 | 当天恰好是今天；预览模式 | M、D | 📸 预览模式 |
| D7 调整（对话）模式 | 对话中；出现待确认的方案；只读时不可用 | M、D、W | ✅ 调整门、只读与返回焦点；未重跑模型 |
| D8 ⭐ 阅读版 | 封面；目录；亮点；每日；参考资料；报告整理中；报告失败 | 全部 | ✅ 桌面、手机及异常代表状态已复核 |
| D9 PDF 导出 | 空闲；准备中；成功；行程刚更新；失败 | M、D | ✅ 实际导出与失败反馈；版本冲突沿用 B3 结论 |
| D10 手机布局 | 全屏地图 + 底部抽屉的两档高度；手机日程导航 | M、T、B（1023 / 1024） | ✅ 布局、日期选择与焦点已复核 |
| D11 历史结果 | 只读 | M、D | ✅ 夹具验证入口身份与调整禁用 |
| D12 PDF 文件 | 导出的 PDF 逐页转成图片，检查排版、分页和字体 | — | ✅ 18 页转图检查，来源分组已修正 |

## 审查项

- [x] 全程、某天、旅中预览、对话的代表切换及返回路径已覆盖，阅读往返保留地图实例。
- [x] 卡片与地图的选中、高亮、聚合放大和 `Esc` 焦点归还已通过浏览器回归。
- [x] 工作台、阅读版与 PDF 采用同一交付；现有 14 日样本的 50 条缺口在 PDF 全部保留，相关单日与阅读版提示可见。
- [x] 交付更新继续消费当前 Bundle，阅读版整理中与失败分开；未新增刷新逻辑，真实天气刷新及全流程闪动由 F6 接续复核。
- [x] M、T、L、D、W、U 与 1023 / 1024 断点代表布局已采集，补充样本未见横向溢出或页面异常。

## 参考

- 地图与手机抽屉：[60fps · Map](https://60fps.design/shots/filter/map)、[60fps · Bottom Sheet](https://60fps.design/shots/filter/bottom-sheet)、[60fps · Tabs](https://60fps.design/shots/filter/tabs)
- 组件：[Tabs](https://component.gallery/components/tabs)、[Card](https://component.gallery/components/card)、[Popover](https://component.gallery/components/popover)（数据来源弹层）、[Badge](https://component.gallery/components/badge)、[Toast](https://component.gallery/components/toast)、[Accordion](https://component.gallery/components/accordion)（详情展开）
- 整页观感：recent.design 定格素材（`output/review/_refs/recent.design/`）

## 影响下游

- 改动卡片或报告结构 → [F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [x] 来自 F3-02、F3-06：交付使用完整 Bundle，不重复生成态摘要；缺口在相关日期可见，调整门回归通过。
- [x] 来自 F2-04：沿用已有交付、非只读的调整队列前提；本轮调整门与窄屏会话回归通过，队列业务状态未改动，完整交互接续 F6。
- [x] 来自 F1-01、F1-02、F1-05、F1-06、F1-07：地图层级、卡片联动、阅读往返及焦点回归通过，复用现有样式与动效 token。
- [x] 来自 B4-03、B4-07：继续以当前 Run / Bundle 恢复交付；历史只读夹具回归通过，执行租约和历史类型未改动。
- [x] 来自 B3-04 至 B3-09：缺口和来源按需可达，保留单项价格；实际导出保留 50 条缺口，版本冲突沿用 B3 已验收逻辑。
- [x] 来自 B2-03：调整门保留同行上下文，进入与返回焦点回归通过；多轮追问数据逻辑沿用 B2 结论，未调用模型重跑。
- [x] 来自 S0 地图标记：内部端点标记正确渲染，外部文本继续转义；F4-01 已关闭。
- [x] 来自 S0 第 6 天缺口：自定义“自由休息”条目保留，同时直接展示尚未安排的原始说明；全程、阅读版与 PDF 均可到达完整缺口。
- [x] 来自 S0 只读历史：手机未打开日程面板时即可看到“历史结果 · 只读”，调整入口不出现，夹具回归通过。

## 问题与修复

- [x] F4-01 〔D1-D-study-overview.png〕地图标记出现原样 HTML → 分开处理内部端点标记和需转义的外部文本，单元测试与实际截图通过。〔D1-D-overview-r3.png；提交 047bbd2〕
- [x] F4-02 〔D5-M-study-map.png〕14 日日期条末端不易发现且与地图控件相邻 → 城市停留段导航、桌面日期换行和手机直接选日，D14 可达并恢复目录焦点。〔D2-M-day6-r3.png、浏览器回归；提交 047bbd2〕
- [x] F4-03 〔D8-D/M-study-cover.png〕阅读版标题及站名不自然断行 → 短封面、按车程分行与语义单元换行，Terra r2 复核关闭。〔D8-D/M-cover-r2.png；提交 047bbd2〕
- [x] F4-04 未安排与事实来源在默认视图中不易找到 → 单日直接展示相关缺口，全程保留完整入口，来源就近展开并合并重复记录；三处内容保留验证通过。〔D2-D-day6-r3.png、D3-D-sources-r2.png、pdf-validation.json；提交 047bbd2〕
- [x] F4-05 〔D1-D-overview-r1.png〕密集地图标记叠压 → 按缩放与距离聚合、重合点展开，保持卡片高亮和选中联动；Terra r2 与浏览器回归通过。〔D5-D-cluster-expanded-r2.png、D5-D-selection-r2.png；提交 047bbd2〕
- [x] F4-06 PDF 来源标题、摘录与检索信息跨页分离 → 按来源组分页，2 项纯测试及实际 18 页导出检查通过，B3 已登记复核。〔pdf-final-sources.jpg；提交 047bbd2〕
- [x] F4-07 手机日程遮挡地图且只读身份隐藏 → 两档非模态面板、地图空间避让、入口只读标记和关闭焦点归还，浏览器回归通过。〔D5-M-map-r3.png、D2-M-day6-r3.png；提交 047bbd2〕
- [x] F4-08 PDF 失败反馈仅供读屏、报告整理中与失败不易区分 → 可见状态反馈并区分两种阅读状态，失败夹具回归通过。〔D8-D-report-pending-r2.png、D8-D-report-failed-r2.png；提交 047bbd2〕
