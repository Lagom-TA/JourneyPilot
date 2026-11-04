# F3 生成工作台

`前端页面` · 前置 [F1](F1-frontend-foundation.md)、[B2](B2-planning-intake.md)、[B4](B4-runtime-streaming.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/components/workspace/`：`GenerationJourneyPanel`、`UnderstandingQuestionsCard`
- `frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx`
- `frontend/src/features/chat/components/ThinkingChain.tsx`
- `frontend/src/app/layout/TripWorkspaceShell.tsx`
- 对应的 `frontend/src/features/travel/model/` 与 `frontend/src/features/chat/model/`

## 截图清单

⭐ 为[展示镜头](../analysis.md#达标线)。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| G1 进入工作台 | 首页 → 工作台过渡的起始帧和结束帧 | M、D、W | ⬜ |
| G2 侧栏行程卡 | 信息齐全；目的地待确认；日期暂定；人数待确认；多个目的地且名字很长 | M、D、W | ⬜ |
| G3 理解追问卡 | 单选；多选；日期区间；自由填写；多轮追问替换；目的地待核实；部分研究未完成；提交中 | M、D | ⬜ |
| G4 ⭐ 研究方案确认 | 待确认；展开修改；修改未提交时确认按钮禁用；提交中；出错；计划已变化需刷新；方案生成失败；没有方案文本；刷新后恢复 | 全部 | ⬜ |
| G5 ⭐ 调研动态 | 空；进行中（多组并行）；工具行展开；来源预览；模型工作说明；里程碑；多轮返回调研；固定查看某一阶段；某阶段没有记录 | M、D、W、U | ⬜ |
| G6 四段进度 | 各阶段的进行中、完成、失败、停止；组合阶段 | M、D | ⬜ |
| G7 运行终态 | 完成；部分未安排；失败；已取消；正在停止；中断后可继续；中断后不可继续；继续生成中 | M、D、W | ⬜ |
| G8 恢复提示 | 正在重新加载；加载失败（看桌面和手机上的浮层位置） | M、D、W | ⬜ |
| G9 补充要求输入框 | 各终态下的提示；运行中排队的提示；手机吸底 | M、D | ⬜ |
| G10 历史生成记录 | 只读 | M、D | ⬜ |

## 审查项

- [ ] 过程区和确认门之间的交接：焦点去向、不可操作区域、刷新后直接恢复。
- [ ] 停止、继续、返回新旅行这几个按钮在每个状态下是否都出现得正确。
- [ ] 长时间运行时，计时、分组自动展开和收起、滚动位置。
- [ ] 运行中刷新页面、断网后重连、同时打开两个标签页。

## 参考

- 生成过程：[60fps · AI](https://60fps.design/shots/filter/ai)、[60fps · Assistant](https://60fps.design/shots/filter/assistant)、[60fps · Loading](https://60fps.design/shots/filter/loading)、[60fps · Shimmer](https://60fps.design/shots/filter/shimmer)、[60fps · Success State](https://60fps.design/shots/filter/success-state)
- 组件：[Progress indicator](https://component.gallery/components/progress-indicator)、[Stepper](https://component.gallery/components/stepper)、[Skeleton](https://component.gallery/components/skeleton)、[Spinner](https://component.gallery/components/spinner)、[Accordion](https://component.gallery/components/accordion)（分组展开）、[Popover](https://component.gallery/components/popover)（来源预览）
- 侧栏：[navbar · Side bar](https://navbar.gallery/type/side-bar)

## 影响下游

- 改动确认门、追问卡或进度结构 → [F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [ ] 来自 F2-04、F2-07、F2-08、F2-10：共享输入区移除手动整理，普通问答隐藏技术诊断并居中限宽；首页自然输入随内容伸缩，纸组点选只更新当前模式、自动轮换不改草稿；当前真实路径使用简化输入区，旧补全描述、风格弹层及“新对话”不挂载；队列仅已有交付后的调整可产生 → 请复核首页转入、长运行与队列衔接，并决定旧工具的接入或清理。
- [ ] 来自 B5-07、B5-10、B5-11：同名 MCP 工具保留原归属，汇率参数错误返回失败，费用数据不完整时继续规划 → 请复核工具状态、失败和费用上限提示。
- [ ] 来自 F1-02、F1-05、F1-06、F1-07：中断帧按中断展示，各会话可并行生成，工作台样式与断点已整理 → 请复核中断、恢复和移动工作台。
- [ ] 来自 B4-03、B4-04、B4-07、B4-13：失去租约时旧执行者不再覆盖终态，中断帧携带状态，预算/时限耗尽和中断保存可读历史 → 请复核工作台状态、恢复动作与提示。
- [ ] 来自 B4-11：用户确认断线即中断，游标恢复已保存状态与交付而不补播过程 → 请复核断线、刷新及多标签页的反馈。
- [ ] 来自 B3-02、B3-06：研究门说明重试时限，未安排日期可进入部分交付 → 请复核提示与状态衔接。
- [ ] 来自 B2-02：日期补问和地点重试达到理解轮次上限时结束规划 → 请复核工作台错误提示与下一步操作。
- [ ] 来自 S0：研究门终态（取消、失败、中断）的右侧面板里，“取消规划 / 重试未完成的研究”连同两个图标是无样式的纯文本，真实取消截图 `output/review/S0/sessions/trip_9afdaa396afb5b45879c5771099c4c71-state.png` 就有；请检查这块是否漏渲染成按钮与输入框。
- [ ] 来自 S0：G7、G10 的失败、中断（可继续、不可继续）、历史只读素材在 `output/review/S0/states/`，来自请求拦截，失败态右侧内容沿用取消 run；“正在停止”“继续生成中”“部分未安排”未覆盖。

## 问题与修复

- （暂无）
