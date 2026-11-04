# F5 我的行程与偏好资料

`前端页面` · 前置 [F1](F1-frontend-foundation.md)、[B5](B5-tools-models-data.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/pages/MyTripsPage.tsx`
- `frontend/src/features/settings/`、`frontend/src/features/presets/`、`frontend/src/features/knowledge/`
- `frontend/src/app/layout/MainLayout.tsx`、`frontend/src/app/components/`
- `frontend/src/components/ui/`：`Modal`、`Sheet`、`ConfirmAction`、`PageShell`、`RequestFailureNotice`

## 截图清单

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| P1 导航 | 桌面顶部导航；手机抽屉；偏好子导航 | M、T、D、B（1023 / 1024） | ⬜ |
| P2 我的行程 | 加载中；失败；空；搜索无结果；一条；很多条；各种状态标签；生成记录展开 | 全部 | ⬜ |
| P3 我的偏好 | 加载中；失败；常用出发地；偏好标签；记忆为空和有内容；行内二次确认；全部删除弹窗；状态提示 | M、D、W | ⬜ |
| P4 旅行风格 | 一列、两列、三列网格；空；搜索无结果；筛选；创建向导四步（含 AI 生成失败、保存失败）；编辑；激活 | 全部 | ⬜ |
| P5 资料来源 | 空；有资料；添加文本；上传中；查看和编辑正文（读取中、失败）；删除确认；底部提示条 | M、D、W | ⬜ |
| P6 全局 | 初始页面骨架；页面加载失败；地址栏视图参数无效时的回落 | M、D | ⬜ |

## 审查项

- [ ] 从“我的行程”打开当前结果、继续一趟旅行、只读查看历史记录，分别落到哪里。
- [ ] 激活风格后跳转到规划页，以及风格失效时的提示。
- [ ] 各类删除操作的确认、撤销和失败反馈。
- [ ] 上传文件的类型、大小限制和失败提示。

## 参考

- 导航：[navbar · Side bar](https://navbar.gallery/type/side-bar)、[navbar · Dropdowns](https://navbar.gallery/type/dropdowns)、[navbar · Full screen](https://navbar.gallery/type/full-screen)、[Navigation](https://component.gallery/components/navigation)、[Drawer](https://component.gallery/components/drawer)
- 列表与表单：[Empty state](https://component.gallery/components/empty-state)、[Form](https://component.gallery/components/form)、[File upload](https://component.gallery/components/file-upload)、[Modal](https://component.gallery/components/modal)、[60fps · Empty State](https://60fps.design/shots/filter/empty)

## 影响下游

- 改动导航或共享弹层 → [F2](F2-home-input.md)、[F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[F6](F6-motion-a11y.md)

## 收到的提醒

- （暂无）

## 问题与修复

- （暂无）
