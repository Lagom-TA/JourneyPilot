# F4 交付工作台

`前端页面` · 前置 [F1](F1-frontend-foundation.md)、[B3](B3-planning-delivery.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/components/workspace/`：`DeliveryWorkspace`、`TripOverview`、`DaySummaryCard`、`DayHeader`、`ItineraryCardFlow`、`DayTimeline`、`TravelEntityCards`、`TransportLegCard`、`TransportProviderNote`、`WeatherStrip`、`BundleMapLeaflet*`、`FullReportView`、`TripFactReadout`、`IntentExplanationList`、`TimelineNodeMark`
- 对应的 `frontend/src/features/travel/model/` 和 `frontend/src/features/travel/types/`

## 截图清单

⭐ 为[展示镜头](../analysis.md#达标线)。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| D1 ⭐ 全程总览 | 1 天；4–7 天；14 天；标题很长；含“尚未安排” | 全部 + B | ⬜ |
| D2 每日卡片 | 景点；餐饮；跨夜住宿；自定义项；详情展开；“在地图查看” | M、D、W | ⬜ |
| D3 交通卡 | 铁路和航班班次；公共交通（线路链、乘车明细展开）；驾车；步行和骑行；短距离接驳；路线更新中；路线不可用；方式已锁定；数据来源弹层；路线步骤展开 | M、D | ⬜ |
| D4 天气 | 预报；降雨；季节参考；新鲜度展开；没有天气 | M、D | ⬜ |
| D5 ⭐ 地图 | 加载中；底图失败降级；没有数据；当天没有可定位的地点；选中地点后的详情卡；卡片悬停联动；堆叠图钉展开；图层弹层；按天切换；地图模块加载失败 | 全部 | ⬜ |
| D6 旅中查看 | 当天恰好是今天；预览模式 | M、D | ⬜ |
| D7 调整（对话）模式 | 对话中；出现待确认的方案；只读时不可用 | M、D、W | ⬜ |
| D8 ⭐ 阅读版 | 封面；目录；亮点；每日；参考资料；报告整理中；报告失败 | 全部 | ⬜ |
| D9 PDF 导出 | 空闲；准备中；成功；行程刚更新；失败 | M、D | ⬜ |
| D10 手机布局 | 全屏地图 + 底部抽屉的两档高度；手机日程导航 | M、T、B（1023 / 1024） | ⬜ |
| D11 历史结果 | 只读 | M、D | ⬜ |
| D12 PDF 文件 | 导出的 PDF 逐页转成图片，检查排版、分页和字体 | — | ⬜ |

## 审查项

- [ ] 全程、某天、旅中、对话四个场景之间切换，以及返回路径。
- [ ] 卡片和地图之间的双向联动：选中、高亮、镜头移动、`Esc` 后焦点归还。
- [ ] 同一个行程在工作台、阅读版、PDF 三处内容一致。
- [ ] 交付后修改或刷新天气时，界面如何更新、有没有闪动。
- [ ] 大屏下地图区和浮动面板的比例；矮屏下浮动面板的滚动。

## 参考

- 地图与手机抽屉：[60fps · Map](https://60fps.design/shots/filter/map)、[60fps · Bottom Sheet](https://60fps.design/shots/filter/bottom-sheet)、[60fps · Tabs](https://60fps.design/shots/filter/tabs)
- 组件：[Tabs](https://component.gallery/components/tabs)、[Card](https://component.gallery/components/card)、[Popover](https://component.gallery/components/popover)（数据来源弹层）、[Badge](https://component.gallery/components/badge)、[Toast](https://component.gallery/components/toast)、[Accordion](https://component.gallery/components/accordion)（详情展开）
- 整页观感：recent.design 定格素材（`output/review/_refs/recent.design/`）

## 影响下游

- 改动卡片或报告结构 → [F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [ ] 来自 F2-04：待发送队列只在已有会话和交付、非只读的调整路径可产生，不属于首页首次规划 → 请与 F3 一起复核排队、暂停、编辑删除及继续发送；本轮 F2 未将其记为已通过。
- [ ] 来自 F1-01、F1-02、F1-05、F1-06、F1-07：会话重放、中断展示、并行流、地图层级和样式 token 已调整 → 请复核交付工作台与地图联动。
- [ ] 来自 B4-03、B4-07：过期执行者不能提交交付，失败和中断会保存对应历史类型 → 请复核交付页恢复与会话展示。
- [ ] 来自 B3-04 至 B3-09：公开交付保留未安排日期和缺口、PDF 已展示缺口及逐事实引用，价格不再汇总、导出期间版本变化会冲突 → 请复核工作台和阅读版的缺口、来源及单项价格展示。
- [ ] 来自 B2-03：交付后的连续追问会与回答一起传入后续分流和调整 → 请复核多轮追问、刷新和再次提交的体验。
- [ ] 来自 S0：真实 14 日交付截图 `output/review/S0/sessions/fourteen-days-chengdu-chongqing-extended-result.png` 的地图区域出现原样 `<span style=...>` 标记文本；请检查地图标记内容与渲染。
- [ ] 来自 S0：该 Bundle 的 `itinerary.unresolved` 包含第 6 天“尚未安排具体活动”，但 D6 界面显示“自由休息”且未展示缺口；B3 已支持未安排日期并在 PDF 展示，请复核工作台与阅读版。该 Bundle 共 50 条缺口，其中 49 条是“接驳尚未核实”。
- [ ] 来自 S0：D11 历史结果的只读素材在 `output/review/S0/states/history-readonly-*.png`（请求拦截所得）；手机端需先点“查看旅行日程”才看到只读标记。

## 问题与修复

- （暂无）
