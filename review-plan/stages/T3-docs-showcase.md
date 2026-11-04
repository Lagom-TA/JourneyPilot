# T3 文档与开源门面

`文字内容` · 前置其余全部阶段 · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `README.md`、`README.zh-CN.md`、`LICENSE`、`AGENTS.md`
- `docs/`：`README.md`、`architecture/`、`adr/`、`invariants.md`、`configuration.md`、`local-development-troubleshooting.md`、`assets/`
- `frontend/README.md`、`frontend/e2e/README.md`、`backend/tests/README.md`、`backend/mcp/rail/README.md`
- 全仓库的代码注释

## 审查项

- [ ] **README**：中英文内容对齐；功能描述与最终产品一致；在全新环境中按“快速开始”能跑通（与 [B6](B6-data-config-release.md) 的结论核对）。
- [ ] **展示素材**：界面定稿后，按[展示镜头](../analysis.md#达标线)重拍 README 截图和 `docs/assets/`；用 V2–V4 的录屏制作演示动图；确定仓库的社交预览图。
- [ ] **作品集首页**：仓库首页的信息架构，包括一句话定位、演示、技术亮点、架构图、技术栈；读者在第一屏内能看懂这是什么、好在哪里。
- [ ] **设计文档**：ADR 的编号和索引；`invariants.md` 每条保证与代码对应；`overview.md` 与 [B1](B1-backend-layers.md) 的结论一致。
- [ ] **社区文件**：按个人作品的定位，确定是否需要贡献指南、安全披露、行为准则、Issue 和 PR 模板。
- [ ] **注释**：只描述当前行为，不含历史叙事和过程信息。
- [ ] **链接**：文档内的链接全部可以访问。

## 参考

- 演示视频与动图：[posts.design · Launches](https://posts.design/launches)、[posts.design · Best of 2026](https://posts.design/launches/best-2026)、recent.design 定格素材（`output/review/_refs/recent.design/`）
- 社交预览图：[posts.design · OpenGraph](https://posts.design/opengraph)、[a1 · OG images](https://www.a1.gallery/og-images)
- 旅行类门面：[a1 · Travel](https://www.a1.gallery/category/travel)、[minimal · Travel](https://minimal.gallery/tag/travel/)

## 影响下游

- 无（最后执行）

## 收到的提醒

- [ ] 来自 B5-12、B5-13：手动记忆操作会留作后续总结反馈；Node MCP 使用锁定依赖并要求 Node 22 → 请复核公开文档与安装说明。
- [ ] 来自 B6-08、B6-09：第三方 Open-Meteo MCP 默认禁用且 README 已说明；23 个审查过程文件和本机专用审查设置需在审查完成后决定公开范围，删除前列清目标并取得授权。
- [ ] 来自 B6-10：启动脚本复用已有 PostgreSQL 和 Redis 容器，配置变化不会自动重建；请复核中英文快速开始。
- [ ] 来自 B4-11、B4-12：更新了断线恢复、预算估算与租约不变量，并固定本机审查数据库 → 请复核公开文档与本机审查说明的边界。
- [ ] 来自 B3：架构总览与中英文 README 更新了研究并行、部分交付、PDF 和单项价格口径 → 请对照最终实现复核。
- [ ] 来自 B1：架构总览与中英文 README 更新了分层职责和关闭顺序 → 请对照最终实现复核。

## 问题与修复

- （暂无）
