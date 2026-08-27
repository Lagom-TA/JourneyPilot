# 设计文档（design）

这一层放**设计文档**：一套机制为什么长成这样、边界画在哪、下一步往哪走。

与既有三层的分工：

| 目录 | 回答的问题 | 时效 |
|---|---|---|
| `../architecture/overview.md` | 系统由哪些进程/存储组成 | 随部署形态变 |
| `../adr/` | 某个**已经做出**的选择，当时的替代方案，为什么没选 | 一次性，不改 |
| `../invariants.md` | 所以**什么必须永远成立**，谁保证，哪个测试钉住 | 随代码变 |
| **`./`（本层）** | 一套机制的**完整设计**：前提 → 拓扑 → 生命周期 → 契约 → 预算 | 随设计演进 |

## 本层文档

| 文档 | 是什么 | 状态 |
|---|---|---|
| [`agent-workflow.md`](agent-workflow.md) | **规范文档**。JourneyPilot Agent 框架的完整设计。独立成立，读者不需要看过代码。 | 撰写中 |
| [`comparative-study.md`](comparative-study.md) | **对照研究**。读 codex-main 与 openpi 之后，在三个轴上的对照结论与由此确定的设计决策。 | 撰写中 |

## 为什么拆成两份

两份文档的**生命周期不同**：

- `agent-workflow.md` 是规范。它描述 JourneyPilot 自己的设计，不引用外部项目的实现细节。
  它要能被单独交给一个没看过 codex 的人。
- `comparative-study.md` 是论证。它锚定在两个外部仓库的某个具体 commit 上，会随对方演进而过期。
  它的产物是编号决策（DD-xx），这些决策被采纳后**折进** `agent-workflow.md` 成为规范内容，
  并在真正落地时升级为 `../adr/` 里的一条 ADR。

这与本仓已有的 ADR / invariants 分工是同一个模式：论证与规范分开放，规范引用编号而不重复历史。

## 阅读顺序

1. `agent-workflow.md` §1 设计前提 —— 全部决定的来源，先读这一章
2. `comparative-study.md` §1 前提对照表 —— 决定后面所有结论是否可迁移
3. `comparative-study.md` §2–4 三个轴
4. `agent-workflow.md` 其余章节
