# JourneyPilot 定版审查方案

> 基线：分支 `main` · 提交 `4aa1d11` · 开始日期 `2026-11-04`
>
> 本页是审查入口，只放基调、进度和索引。规则、规范和各阶段的内容在 [`review-plan/`](review-plan/) 中，用到时再打开。截图、录屏和素材清单放在 `output/review/`。

## 审查基调

JourneyPilot 是个人代表作，不是商用产品。达标线是“拿得出手，让人想多看一眼”：

- **第一眼**：首页首屏、生成过程、交付结果的画面可以直接放进作品集和 README。
- **手感**：过渡、反馈、加载和动效流畅，有质感，不像模板拼装。
- **演示路径**：打开仓库 → 读 README → 本地跑起来 → 完成一次规划 → 导出 PDF，全程没有断点，也没有粗糙的地方。
- **经得起细看**：读代码的人看到的分层、命名和文档清楚可信。
- **设计原则**：只使用一套界面主题；不安排减少动态效果等无障碍专项设计与验收。

界面、设计和动效按展示级标准审查；后端和文字以支撑演示、经得起细看为准。只有商用产品才需要的运维、容量、计费与合规不在本次范围内。

## 从哪里读起

| 角色 | 阅读顺序 |
|---|---|
| 所有人 | 本页 → [工作规则](review-plan/rules.md) → 自己负责的阶段文件 |
| `前端页面` · 采集与修复 | 另读 [采集规范](review-plan/capture.md)，以及[参考库](review-plan/references.md)中标 🎬 的站点 |
| `前端页面` · 分析与复核 | 另读 [分析规范](review-plan/analysis.md)、[参考库](review-plan/references.md) |
| `文字内容` · T1 | 另读[分析规范](review-plan/analysis.md)中的“通用视觉检查” |

## 进度总览

**进度**：后端逻辑 6/6 · 前端页面 1/6 · 文字内容 0/3 · [待决事项](review-plan/decisions.md) 0 项

状态：⬜ 未开始 · 🔍 审查中 · 🔧 修复中 · ✅ 已完成 · ↩️ 需复核 · ⏸️ 搁置

| 编号 | 阶段 | 标签 | 前置 | 状态 | 负责人 | 未处理提醒 | 完成日期 / 提交 |
|---|---|---|---|---|---|---|---|
| S0 | [审查准备](review-plan/stages/S0-setup.md) | — | — | ✅ | Codex | — | 2026-11-04 |
| B1 | [后端分层与依赖边界](review-plan/stages/B1-backend-layers.md) | `后端逻辑` | S0 | ✅ | Codex | 0 | 2026-11-04 / dc5a9e4、80e6344 |
| B2 | [规划主链（上）：理解、研究设想与确认](review-plan/stages/B2-planning-intake.md) | `后端逻辑` | B1 | ✅ | Codex | 0 | 2026-11-04 / 65f8269 |
| B3 | [规划主链（下）：调研、组合与交付](review-plan/stages/B3-planning-delivery.md) | `后端逻辑` | B2 | ✅ | Codex | 0 | 2026-11-04 / 8a92eb4 |
| B4 | [运行控制、会话与流式](review-plan/stages/B4-runtime-streaming.md) | `后端逻辑` | B1 | ✅ | Codex | 0 | 2026-11-04 / b8a073d、c76a8aa、b8af718、80e6344 |
| B5 | [工具、模型、外部数据与用户资料](review-plan/stages/B5-tools-models-data.md) | `后端逻辑` | B1 | ✅ | Codex | 0 | 2026-11-04 / 0373c45、9c8f755、6678aff、80e6344、5ed4726 |
| B6 | [数据、配置与工程发布](review-plan/stages/B6-data-config-release.md) | `后端逻辑` | B1 | ✅ | Codex | 0 | 2026-11-04 / 8d994d8、9d9a185、3a61d1c、ac523de |
| F1 | [前端结构、状态与样式体系](review-plan/stages/F1-frontend-foundation.md) | `前端页面` | S0、B4 | ✅ | Codex（采集 / 修复） | 0 | 2026-11-04 / 38bd919、286d9e8 |
| F2 | [首页与需求输入](review-plan/stages/F2-home-input.md) | `前端页面` | F1 | ↩️ | Codex（采集 / 修复） / GPT 6.1 Terra（分析） | 1 | 2026-11-05 / 669f83a |
| F3 | [生成工作台](review-plan/stages/F3-generation-workspace.md) | `前端页面` | F1、B2、B4 | ⬜ | | 9 | |
| F4 | [交付工作台](review-plan/stages/F4-delivery-workspace.md) | `前端页面` | F1、B3 | ⬜ | | 8 | |
| F5 | [我的行程与偏好资料](review-plan/stages/F5-trips-preferences.md) | `前端页面` | F1、B5 | ⬜ | | 5 | |
| F6 | [动效与交互](review-plan/stages/F6-motion-a11y.md) | `前端页面` | F2–F5 | ⬜ | | 2 | |
| T1 | [界面文案](review-plan/stages/T1-ui-copy.md) | `文字内容` | F1 | ⬜ | | 5 | |
| T2 | [提示词与模型产出](review-plan/stages/T2-prompts-outputs.md) | `文字内容` | B2、B3 | ⬜ | | 5 | |
| T3 | [文档与开源门面](review-plan/stages/T3-docs-showcase.md) | `文字内容` | 其余全部 | ⬜ | | 8 | |

三类标签可以并行推进；同一标签内按编号顺序进行；前置阶段完成后才能开始。状态只在这张表里维护。

后端 B1–B6 的综合验收记录见 [acceptance-backend.md](review-plan/acceptance-backend.md)：质量门、提醒收口、验收中的修复，以及仍需关注的事项。

## 标签与人选

| 标签 | 覆盖内容 | 适合的审查者 | 需要的环境 |
|---|---|---|---|
| `后端逻辑` | 分层与依赖、流程编排、状态与并发、数据一致性、工程与发布 | 擅长长链路代码推理，能在大量文件之间追踪调用和状态流转，对边界条件敏感 | Python 环境、pytest、ruff、本地服务、当前数据库 |
| `前端页面` · 采集与修复 | 驱动浏览器截图和录屏、写素材清单、修改前端代码、复拍；F1 的代码结构审查 | 工具操作稳定，熟悉 CSS 布局和 React 状态，命名和记录规范 | 本地服务、Playwright、多视口、ffmpeg |
| `前端页面` · 分析与复核 | 看截图和录屏，判断视觉、布局、动效和交互是否达到展示级；对照参考库；复核修复结果 | 视觉判断力强、审美在线，能看出像素级偏移和节奏问题 | 素材包、参考库；不需要操作浏览器 |
| `文字内容` | 界面文案、提示词、模型产出的文字、项目文档 | 中文表达好，对语气、术语和信息密度敏感；审提示词还需要理解模型上下文的组织方式 | 截图（来自前端页面阶段）、源码、真实运行样例 |

- 同一标签的阶段尽量交给同一位审查者连续完成，减少重复熟悉代码的成本。
- `前端页面` 由两个模型配合完成：操作型模型负责采集、修复和复拍，看图模型负责分析和复核。两者只通过素材包交接。
- T1 需要看截图，要选能读图的模型。

## 文件索引

```text
REVIEW-PLAN.md               入口：基调、进度、人选、索引
review-plan/
├── rules.md                 工作规则：阶段闭环、前端交接、跨阶段提醒、边界、记录格式
├── capture.md               采集规范：视口、状态获取、边角场景、命名、录屏与抽帧、素材清单
├── analysis.md              分析规范：达标线、展示镜头、通用视觉检查、动效判断、结论写法
├── references.md            外部参考库：收录站点、入口、获取方式
├── decisions.md             待决事项
├── acceptance-backend.md    后端 B1–B6 综合验收记录
├── b4-events.md             B4 流式事件清单
└── stages/                  每个阶段一个文件：范围、审查项、清单、参考、提醒、问题与修复
    ├── S0-setup.md
    ├── B1-backend-layers.md … B6-data-config-release.md
    ├── F1-frontend-foundation.md … F6-motion-a11y.md
    └── T1-ui-copy.md … T3-docs-showcase.md
```
