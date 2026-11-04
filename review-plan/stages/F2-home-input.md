# F2 首页与需求输入

`前端页面` · 前置 [F1](F1-frontend-foundation.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/components/planning/`
- `frontend/src/features/chat/components/`：`ConversationThread`、`InputArea`、`MessageBubble`、`ContextCompactionNotice`、`hallmark/`
- `frontend/src/features/presets/components/PresetSelector.tsx`
- `frontend/src/app/layout/`

## 截图清单

⭐ 为[展示镜头](../analysis.md#达标线)。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| H1 ⭐ 一句话规划 | 默认；输入长文本；补充偏好已选；提交中；提交失败 | 全部 + B | ⬜ |
| H2 按条件规划 | 无常用出发地；已有出发地；目的地 1 / 3 / 5（上限）；更多偏好展开；校验错误；配置读取中；配置读取失败 | 全部 + B | ⬜ |
| H3 目的地搜索 | 搜索中；有候选；无结果；出错；拖拽排序中 | M、D | ⬜ |
| H4 日期选择 | 桌面双月；手机底部弹层单月；只选了开始日；已选区间；14 天上限；跨月和跨年 | M、D、B（639 / 640） | ⬜ |
| H5 ⭐ 旅行灵感图 | 四个场景；悬停 | 全部 | ⬜ |
| H6 分流确认卡 | 各种按钮组合 | M、D | ⬜ |
| H7 推荐目的地后转入规划 | 选择目的地；继续规划 | M、D | ⬜ |
| H8 普通问答 | 用户和助手气泡；流式输出中；已停止生成；错误卡；安全拦截卡；载入更早的对话；已整理较早对话的提示 | M、D、W | ⬜ |
| H9 输入区 | 常规；运行中（停止按钮）；已停止；补全描述的结果和失败；风格选择弹层的各种状态；待发送消息队列（排队中、已暂停） | M、D | ⬜ |
| H10 用量与上下文弹层 | 上下文透镜（条目多和少）；成本账本（运行中、已完成） | M、D | ⬜ |

## 审查项

- [ ] 两种规划模式来回切换时，已填写的内容不丢失。
- [ ] 灵感卡片填入表单后的滚动和聚焦。
- [ ] 目的地的键盘排序、删除和上限提示。
- [ ] 日期选择的边界：过去的日期、最长天数、清除日期。
- [ ] 首页提交后到进入工作台之间的等待状态。

## 参考

- 首页与首屏：[a1 · AI](https://www.a1.gallery/category/ai)、[a1 · Travel](https://www.a1.gallery/category/travel)、[a1 · Sections](https://www.a1.gallery/sections)、[minimal · AI](https://minimal.gallery/tag/ai/)、[minimal · Travel](https://minimal.gallery/tag/travel/)、Hero 条目 [Daisy AI](https://supahero.io/hero/daisy-ai) / [Klook](https://supahero.io/hero/klook) / [Airbnb Homes](https://supahero.io/hero/airbnb-homes)
- 组件：[Hero](https://component.gallery/components/hero)、[Segmented control](https://component.gallery/components/segmented-control)（模式切换）、[Combobox](https://component.gallery/components/combobox)（目的地搜索）、[Datepicker](https://component.gallery/components/datepicker)
- 动效：[60fps · AI](https://60fps.design/shots/filter/ai)、[60fps · Chat](https://60fps.design/shots/filter/chat)（H8）、[60fps · Onboarding](https://60fps.design/shots/filter/onboarding)

## 影响下游

- 改动输入区或分流卡 → [F3](F3-generation-workspace.md)、[F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [ ] 来自 F1-05、F1-06：首页样式已分文件并统一 token 与断点 → 请复核宽窄屏布局、日历和目的地候选。

## 问题与修复

- （暂无）
