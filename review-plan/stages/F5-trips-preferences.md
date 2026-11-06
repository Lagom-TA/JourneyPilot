# F5 我的行程与偏好资料

`前端页面` · 前置 [F1](F1-frontend-foundation.md)、[B5](B5-tools-models-data.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/pages/MyTripsPage.tsx`
- `frontend/src/features/settings/`、`frontend/src/features/presets/`、`frontend/src/features/knowledge/`
- `frontend/src/app/layout/MainLayout.tsx`、`frontend/src/app/components/`
- `frontend/src/components/ui/`：`Modal`、`Sheet`、`ConfirmAction`、`PageShell`、`RequestFailureNotice`

采用「开放式旅行档案＋资料正文主从分栏」，代码提交 `cc0f252`。见 [设计方案](../F5-design-options.md)与 [验收记录](../F5-acceptance.md)。下表按实际代表覆盖记进度，不表示完整状态矩阵均已重跑。

## 截图清单

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| P1 导航 | 桌面顶部导航；手机抽屉；偏好子导航 | M、T、D、B（1023 / 1024） | ✅ D / M 导航、手机抽屉与返回路径 |
| P2 我的行程 | 加载中；失败；空；搜索无结果；一条；很多条；各种状态标签；生成记录展开 | 全部 | ✅ 代表布局、当前结果与历史只读入口 |
| P3 我的偏好 | 加载中；失败；常用出发地；偏好标签；记忆为空和有内容；行内二次确认；全部删除弹窗；状态提示 | M、D、W | ✅ 代表布局、独立保存、部分失败与删除范围 |
| P4 旅行风格 | 一列、两列、三列网格；空；搜索无结果；筛选；创建向导四步（含 AI 生成失败、保存失败）；编辑；激活 | 全部 | ✅ D / M 列表、四步创建与两类失败、使用及失效 |
| P5 资料来源 | 空；有资料；添加文本；上传中；查看和编辑正文（读取中、失败）；删除确认；底部提示条 | M、D、W | ✅ 空态、正文、草稿保留、上传限制与失败 |
| P6 全局 | 初始页面骨架；页面加载失败；地址栏视图参数无效时的回落 | M、D | ✅ 骨架同步版式；共享错误边界和参数回落沿用 F1，未重跑全部组合 |

## 审查项

- [x] 当前结果进入交付，历史记录带指定 Run 进入只读交付；等待输入、运行中和取消记录使用对应动作名称。
- [x] 使用风格新建旅行，首页可见当前选择；失效选择被清除并提供重新选择入口。
- [x] 删除均有确认，成功与失败对象明确；没有引入后端不支持的撤销。全部记忆删除保留手填设置，失败保留资料草稿与风格条目。
- [x] 上传支持 TXT、Markdown、PDF、DOCX，上限由运行配置提供；类型、大小、文本添加和保存失败的反馈已定向验证。

## 参考

- 导航：[navbar · Side bar](https://navbar.gallery/type/side-bar)、[navbar · Dropdowns](https://navbar.gallery/type/dropdowns)、[navbar · Full screen](https://navbar.gallery/type/full-screen)、[Navigation](https://component.gallery/components/navigation)、[Drawer](https://component.gallery/components/drawer)
- 列表与表单：[Empty state](https://component.gallery/components/empty-state)、[Form](https://component.gallery/components/form)、[File upload](https://component.gallery/components/file-upload)、[Modal](https://component.gallery/components/modal)、[60fps · Empty State](https://60fps.design/shots/filter/empty)

## 影响下游

- 改动导航或共享弹层 → [F2](F2-home-input.md)、[F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[F6](F6-motion-a11y.md)

## 收到的提醒

- [x] 来自 B5-12：记忆使用详情说明手动管理内容参与后续总结，以及旧画像的使用边界；单条删除反馈与全部删除确认分别表达范围。
- [x] 来自 B5-16：保留接口排序，不增加时间标签或前端二次排序，更新过的事实沿用接口的新近顺序。
- [x] 来自 B6-01：全部删除确认覆盖自动画像、关联、摘要、手动管理内容及旧任务；浏览器夹具验证手填偏好和出发地保留，后台清除逻辑沿用 B6 结论。
- [x] 来自 B5-02、B5-03、B5-05、B5-08：偏好、出发地和记忆分别呈现读取错误；保存、资料索引失败与记忆去重结果就近反馈，失败不冒充空列表。
- [x] 来自 F1-03、F1-04、F1-05、F1-06：正式链接、手机导航与浏览器后退、当前和历史结果、行内确认焦点回归通过；共享加载骨架与档案版式同步。

## 问题与修复

- [x] F5-01 〔P2-D/M-study-default.png〕名称、生成次数和装饰封面重复 → 开放列表只显示一次名称与状态，移除对话摘要和统一装饰封面。〔P2-D/M-implemented-r1.png；提交 cc0f252〕
- [x] F5-02 〔P2-M-study-default.png〕默认展开记录挤占首屏 → 历史默认收起，单次记录直接打开，长标题三行截断，取消状态不暗示自动恢复。〔P2-M-implemented-r1.png、P2-M-live-r1-default.png；提交 cc0f252〕
- [x] F5-03 〔P3-D/M-study-default.png〕偏好大容器与用途说明重复 → 开放设置分组与就近保存反馈，保留出发地作用范围。〔P3-D/M-implemented-r1.png；提交 cc0f252〕
- [x] F5-04 〔P4-D/M-study-default.png〕风格嵌套卡片和使用读数主次不足 → 开放网格、简短摘要和明确使用入口，规划方式按需展开。〔P4-D/M-implemented-r1.png；提交 cc0f252〕
- [x] F5-05 〔P5-D/M-study-default.png〕资料空态比例失衡 → 紧凑空态与上传约束，正文采用桌面主从、手机进入与返回。〔P5-D/M-document-r1.png、P5-D/M-live-r1-default.png；提交 cc0f252〕
- [x] F5-06 常用出发地保存只调用本地状态 setter → 调用保存 API，并以浏览器请求体验证持久化边界。〔browser-check-r2.log；提交 cc0f252〕
- [x] F5-07 部分记忆读取失败仍可能呈现空态，偏好读取失败可保存空选择 → 三项资源独立错误与重试，失败的偏好禁止保存；全部删除不覆盖手填编辑状态。〔browser-check-r2.log；提交 cc0f252〕
- [x] F5-08 风格删除失败缺少反馈，回到首页不显示所选风格 → 保留失败条目；使用入口新建旅行，首页显示选择及失效提示；创建的 AI 与保存错误分别保留。〔browser-check-r2.log；提交 cc0f252〕
- [x] F5-09 资料失败提示与正文编辑路径分散 → 默认阅读、显式编辑，失败保留草稿，离开未保存的正文可取消切换；手机返回原入口。〔browser-check-r2.log；提交 cc0f252〕
- [x] F5-10 上传入口缺少大小限制 → 从公开配置读取实际上限，前端预检格式与大小，服务端最终校验；非默认上限通过定向 API 与浏览器验证。〔backend-tests.log、browser-check-r2.log；提交 cc0f252〕
- [x] F5-11 〔综合验收〕手机抽屉末项已是“资料来源”，导航规格仍期望焦点绕回“我的偏好” → 规格按现链接顺序断言，焦点循环用例通过。（提交 3bd2b42）
- [x] F5-12 〔综合验收〕上传上限改为读取公开配置后，离线会话夹具没有 `/config` 响应 → 夹具补返回上传上限，档案相关用例通过。（提交 3bd2b42）
