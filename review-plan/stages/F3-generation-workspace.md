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

采用「研究台面＋最新动态」：顶部摘要与四段导航、左侧阶段标题、右侧开放任务；手机改为单列。整块任务点击开合，桌面悬浮显示箭头，手机箭头常显，不增加说明性入口文字或加号。停止按钮位于导航右侧。当前素材、交互与验证范围见 `output/review/F3/manifest.md`，方向与调研见 [F3 设计方案](../F3-design-options.md)。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| G1 进入工作台 | 首页 → 工作台过渡的起始帧和结束帧 | M、D、W | ✅ |
| G2 行程摘要 | 信息齐全；目的地待确认；日期暂定；人数待确认；多个目的地且名字很长 | M、D、W | ✅ |
| G3 理解追问卡 | 单选；多选；日期区间；自由填写；多轮追问替换；目的地待核实；部分研究未完成；提交中 | M、D | ✅ |
| G4 ⭐ 研究方案确认 | 待确认；展开修改；修改未提交时确认按钮禁用；提交中；出错；计划已变化需刷新；方案生成失败；没有方案文本；刷新后恢复 | 全部 | ✅ |
| G5 ⭐ 调研动态 | 空；进行中（多组并行）；工具行展开；来源预览；模型工作说明；里程碑；多轮返回调研；固定查看某一阶段；某阶段没有记录 | M、D、W、U | ✅ |
| G6 四段进度 | 各阶段的进行中、完成、失败、停止；组合阶段 | M、D | ✅ |
| G7 运行终态 | 完成；部分未安排；失败；已取消；正在停止；中断后可继续；中断后不可继续；继续生成中 | M、D、W | ✅ |
| G8 恢复提示 | 正在重新加载；加载失败（看桌面和手机上的浮层位置） | M、D、W | ✅ |
| G9 补充要求输入框 | 各终态下的提示；运行中排队的提示；手机吸底 | M、D | ✅ |
| G10 历史生成记录 | 只读 | M、D | ✅ |

## 审查项

- [x] 过程区和确认门之间的交接：服务端清门后交接，隐藏区域 inert，焦点随当前门切换，刷新直接恢复。
- [x] 停止、继续、返回新旅行按状态与只读条件出现；停止请求中禁用，确认门和追问使用各自操作区。
- [x] 计时、长记录滚动及分组开合：默认折叠，手动展开在阶段结束及补充轮次后保留，新 Run 清除旧展开。
- [x] 刷新和断线恢复经离线 HTTP / SSE 路径核对；并发会话隔离通过，双标签执行者租约沿用 B4 已验约束，不新增模型运行。

## 参考

- 生成过程：[60fps · AI](https://60fps.design/shots/filter/ai)、[60fps · Assistant](https://60fps.design/shots/filter/assistant)、[60fps · Loading](https://60fps.design/shots/filter/loading)、[60fps · Shimmer](https://60fps.design/shots/filter/shimmer)、[60fps · Success State](https://60fps.design/shots/filter/success-state)
- 组件：[Progress indicator](https://component.gallery/components/progress-indicator)、[Stepper](https://component.gallery/components/stepper)、[Skeleton](https://component.gallery/components/skeleton)、[Spinner](https://component.gallery/components/spinner)、[Accordion](https://component.gallery/components/accordion)（分组展开）、[Popover](https://component.gallery/components/popover)（来源预览）
- 侧栏：[navbar · Side bar](https://navbar.gallery/type/side-bar)

## 影响下游

- 改动确认门、追问卡或进度结构 → [F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [x] 来自 F5-01、F5-02：行程改为开放列表，共享新旅行入口统一恢复边界；会话切换、不串内容与历史只读的 3 项共享回归通过，生成过程逻辑未改动。

- [x] 来自 F2-04、F2-07、F2-08、F2-10：共享输入区移除手动整理，普通问答隐藏技术诊断并居中限宽；首页自然输入随内容伸缩，纸组点选只更新当前模式、自动轮换不改草稿；当前真实路径使用简化输入区，旧补全描述、风格弹层及“新对话”不挂载；队列仅已有交付后的调整可产生 → 请复核首页转入、长运行与队列衔接，并决定旧工具的接入或清理。 → 已核对首页交接、长记录输入与会话并发；队列边界通过单元测试，未挂载旧工具保持关闭。
- [x] 来自 B5-07、B5-10、B5-11：同名 MCP 工具保留原归属，汇率参数错误返回失败，费用数据不完整时继续规划 → 请复核工具状态、失败和费用上限提示。 → 公开内容过滤保留，失败分组仍显示未完成；不在主工作台新增费用诊断区。
- [x] 来自 F1-02、F1-05、F1-06、F1-07：中断帧按中断展示，各会话可并行生成，工作台样式与断点已整理 → 请复核中断、恢复和移动工作台。 → 已核对中断、可继续与不可继续，以及 M 至 U 布局。
- [x] 来自 B4-03、B4-04、B4-07、B4-13：失去租约时旧执行者不再覆盖终态，中断帧携带状态，预算/时限耗尽和中断保存可读历史 → 请复核工作台状态、恢复动作与提示。 → 终态标题、恢复动作和已有记录分别展示，过期追问不再保留提交入口。
- [x] 来自 B4-11：用户确认断线即中断，游标恢复已保存状态与交付而不补播过程 → 请复核断线、刷新及多标签页的反馈。 → 恢复读取已保存状态，不承诺过程补播；待确认门可直接恢复。
- [x] 来自 B3-02、B3-06：研究门说明重试时限，未安排日期可进入部分交付 → 请复核提示与状态衔接。 → 重试时限沿用服务端说明，未安排条目的 Bundle 正常转交 F4。
- [x] 来自 B2-02：日期补问和地点重试达到理解轮次上限时结束规划 → 请复核工作台错误提示与下一步操作。 → 终态隐藏过期问题，提供真实错误与返回新旅行入口。
- [x] 来自 S0：研究门终态（取消、失败、中断）的右侧面板里，“取消规划 / 重试未完成的研究”连同两个图标是无样式的纯文本，真实取消截图 `output/review/S0/sessions/trip_9afdaa396afb5b45879c5771099c4c71-state.png` 就有；请检查这块是否漏渲染成按钮与输入框。 → 已补齐主次按钮、输入与间距；终态不再保留可提交的重试门。
- [x] 来自 S0：G7、G10 的失败、中断（可继续、不可继续）、历史只读素材在 `output/review/S0/states/`，来自请求拦截，失败态右侧内容沿用取消 run；“正在停止”“继续生成中”“部分未安排”未覆盖。 → 补齐停止中、继续中、完成、失败、中断及历史只读代表素材，局限已记录。

## 问题与修复

- [x] F3-01 〔G3-D/M-study-real-retry.png〕研究重试门的操作无样式且连排 → 补齐追问、重试与取消的主次和间距，终态隐藏过期问题；复核〔G3-D/M-research-retry-r3.png〕。（提交 e48c3fc）
- [x] F3-02 〔G4-M-study-gate.png、G5-M-study-research.png〕摘要与完整阶段挤占手机首屏 → 顶部摘要与短导航，当前方案或任务直接进入首屏；六视口与断点复核通过。（提交 e48c3fc）
- [x] F3-03 〔G5-D/M-task-expanded-r2.png〕最新动态与展开工作说明重复 → 同一句动态只出现一次，工具、里程碑和公开说明按到达顺序查看；复核〔G5-D/M-task-expanded-r3.png〕。（提交 e48c3fc）
- [x] F3-04 〔G5-D/M-parallel-r2.png〕旧卡片样式、标题焦点框和移动箭头遮蔽破坏开放版式 → 生成样式集中到 generation.css，移除旧覆盖，桌面悬浮和移动箭头分别表达开合；r3 复核通过。（提交 e48c3fc）
- [x] F3-05 〔G8-M-recovery-error-r2.png〕恢复提示挡住目的地 → 生成态提示移至底部，不改变主内容高度或焦点；复核〔G8-M-recovery-error-r3.png〕。（提交 e48c3fc）
- [x] F3-06 停止生成位于任务区下方，长记录中不易触达 → 移到阶段导航右侧，桌面图标与文字、手机图标，停止中显示等待且禁用；复核〔G5-D/M-parallel-r3.png、G7-D/M-stopping-r3.png〕。（提交 e48c3fc）
- [x] F3-07 〔G4-D-keyboard-focus-r3.png〕确认按钮焦点环被交接容器裁切 → 仅当前可见面板放开溢出，隐藏面板仍收起；复核〔G4-D-keyboard-focus-r4.png〕。（提交 e48c3fc）

## 设计与验收结论

- GPT 6.1 Terra 仅依据素材包独立分析，初审问题与焦点补拍均已关闭；G4 / G5 所审画面可作为作品集展示镜头，报告为 `output/review/F3/terra-implementation-review.md`。
- 当前材料为 r3：108 张状态图，另有键盘焦点、表单底部、继续中、存储不可用和 CSS zoom 补充；四段 4.2–6.6 秒录像及 100ms 抽帧联系表。代表变体采用 M / D，基础方案覆盖 M / T / L / D / W / U 和关键断点，终态与恢复补 W；不穷举同构排列。
- 验证：`npm ci` 与 `npm run check` 通过（类型、lint、198 项单元测试、构建）；56 项相关浏览器用例通过，覆盖真实 SSE 解析、追问、确认与版本变化、手动开合、终态、历史只读、恢复和会话隔离。焦点样式补丁后的类型与构建通过，机械设计扫描无发现。
- 边界：接口拦截与合成状态不代表真实模型结果；未调用付费模型、修改数据库或重跑后端全量检查。物理手机软键盘、安全区及整体动效表现在 F6 统一复核；部分未安排进入正式交付，呈现由 F4 负责。
