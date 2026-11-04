# T1 界面文案

`文字内容` · 前置 [F1](F1-frontend-foundation.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)、[分析规范](../analysis.md#通用视觉检查每张截图都要过)

## 范围

- `frontend/src/` 中所有用户可见的中文：组件内联文案；`features/*/model/` 中的标签表、错误引导、工具展示；`lib/` 中的错误文案
- 后端返回给界面的文案：`backend/travel_agent/planning/presentation.py`、`backend/travel_agent/planning/delivery/` 中的展示相关文件、`backend/travel_agent/api/chat_errors.py`、`backend/travel_agent/tools/display.py`、`backend/travel_agent/public_note.py`
- F2–F5 的截图和素材清单：`output/review/F2/`–`output/review/F5/`

## 审查项

- [ ] **术语表**：先建一张术语表，划清近义词的使用边界，例如旅行、行程、规划；方案、计划、设想；研究、调研；交付、生成、结果。然后全站按表统一。
- [ ] **语气**：用第二人称，简洁；不外露技术词，如运行、交付包、token、Provider。
- [ ] **状态文案成套**：加载、失败、取消、中断、停止、只读这几种状态，在不同页面上的说法一致。
- [ ] **错误文案**：讲清发生了什么、用户可以做什么；不暴露内部错误。
- [ ] **按钮和标题**：动词统一；长度适合按钮宽度和手机屏幕。
- [ ] **格式**：中英文混排的空格、全角和半角标点、省略号写法、数字与单位（¥、天、晚、人）。
- [ ] **空状态**：说明这里会出现什么，并给出下一步。
- [ ] **读屏文字**：读屏文字与可见文案一致。

## 影响下游

- 文案长度变化 → [F2](F2-home-input.md)–[F5](F5-trips-preferences.md) 复拍并复核对应的截图

## 收到的提醒

- （暂无）

## 问题与修复

- （暂无）
