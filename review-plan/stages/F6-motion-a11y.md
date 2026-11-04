# F6 动效、键盘与无障碍

`前端页面` · 前置 [F2](F2-home-input.md)–[F5](F5-trips-preferences.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md#录屏与抽帧) · 分析员读[分析规范](../analysis.md#动效判断看录屏或抽帧联系表)

## 范围

- `frontend/src/lib/motion.ts`、`frontend/src/app/motion/`、`frontend/src/app/navigation/`
- `frontend/src/index.css` 中的关键帧动画和减少动态效果规则
- 所有引入了动效库的组件

## 录屏清单

⭐ 为[展示镜头](../analysis.md#达标线)，录屏同时作为 README 演示动图的素材。

| 场景 | 录制内容 | 视口 | 进度 |
|---|---|---|---|
| V1 视图切换 | 各页面互相切换；进入和返回工作台；新建对话 | M、D | ⬜ |
| V2 ⭐ 首页 | 模式切换；灵感图轮播和视差；提交后卡片变化 | M、D、W | ⬜ |
| V3 ⭐ 生成过程 | 首页 → 工作台交接；过程 ↔ 确认门交接；确认门退场；分组展开和收起；进行中动画 | M、D | ⬜ |
| V4 ⭐ 交付 | 浮动面板进入；场景切换；阅读版进出；地图镜头移动；卡片与地图联动；卡片依次进入 | M、D、W | ⬜ |
| V5 弹层 | 模态框；底部抽屉拖拽和吸附；日期选择；导航抽屉；行内二次确认 | M、D | ⬜ |
| V6 减少动态效果 | 开启后把 V1–V5 重录一遍 | M、D | ⬜ |
| V7 键盘与读屏 | 各页面的 Tab 焦点序列；弹层打开和按 `Esc` 关闭前后；无障碍树快照 | D | ⬜ |

## 审查项

- [ ] **动效一致性**：时长和缓动都来自 token（采集侧查代码）；同类动作使用同类动效；没有布局跳动；动画进行中点击不会引发状态错乱。
- [ ] **减少动态效果**：每个动画都有降级方案，降级后的最终状态正确。
- [ ] **键盘**：Tab 顺序、焦点可见、`Esc` 只关最上层、焦点归还、弹层内的焦点约束、各快捷键（回车发送、`⌘` / `Ctrl` + 回车提交、方向键排序）。
- [ ] **鼠标与触屏**：悬停效果只在鼠标下生效；触屏点击目标的尺寸。
- [ ] **读屏**：状态播报、警告、骨架屏标签；可见文字与读屏文字一致。
- [ ] **性能体感**：首屏加载、地图懒加载、长列表和长调研记录的滚动流畅度（采集侧实测，写进清单）。

## 参考

- 动效：[60fps · Motion](https://60fps.design/motion)、[60fps · Stagger](https://60fps.design/shots/filter/stagger)、[60fps · Spring Physics](https://60fps.design/shots/filter/spring-physics)、[60fps · Bottom Sheet](https://60fps.design/shots/filter/bottom-sheet)
- 键盘与焦点：[Modal](https://component.gallery/components/modal)、[Drawer](https://component.gallery/components/drawer)、[Popover](https://component.gallery/components/popover) 中各设计系统的无障碍要求

## 影响下游

- 改动交互流程 → [T1](T1-ui-copy.md)
- ⭐ 录屏定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- （暂无）

## 问题与修复

- （暂无）
