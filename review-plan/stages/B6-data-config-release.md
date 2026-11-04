# B6 数据、配置与工程发布

`后端逻辑` · 前置 [B1](B1-backend-layers.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `backend/travel_agent/storage/`（含 `maintenance/`）
- `backend/migrations/`、`backend/alembic.ini`
- `backend/travel_agent/config/`、`backend/travel_agent/cli/`、`backend/config.example.yaml`
- `docs/configuration.md`、`docs/config.schema.json`
- `run.sh`、`infra/`、`.github/`
- `backend/tests/`、`frontend/e2e/`（只看组织方式）、`backend/scripts/`
- `backend/pyproject.toml`、`frontend/package.json`、`backend/mcp/package.json`
- 根目录文件：`.gitignore`、`.dockerignore`、`.gitleaks.toml`、`vitest.config.ts`、`AGENTS.md`、`.agents/`、`.zcode/`

## 审查项

- [ ] **存储层**：一张表由一个 store 负责；大 store 文件的职责切分；事务边界。
- [ ] **迁移**：基线迁移与结构指纹一致；`doctor`、`migrate`、`backup`、`restore` 在空库和非空库下的路径。涉及写库的验证须先取得授权。
- [ ] **配置**：示例配置、schema 和生成的文档三者一致；未知字段被拒绝；环境变量覆盖生效。
- [ ] **一键启动**：在全新克隆上按 README 能把服务跑起来；`run.sh` 的每个子命令；Docker 镜像构建和入口迁移。
- [ ] **CI**：各个 job 覆盖的范围与 README 列出的本地检查命令一致；手动触发的集成作业。
- [ ] **测试组织**：测试目录与源码目录对应；fixtures 没有过期；e2e 用例对应当前的界面。
- [ ] **发布面**：逐一过一遍被 Git 跟踪的文件，判断它们该不该出现在公开仓库里。重点是过程文档（`docs/polish/`、`docs/audits/`、`.zcode/`、`.agents/`，以及本审查方案 `REVIEW-PLAN.md`、`review-plan/`）、本地产物、构建产物和根目录配置。
- [ ] **版本号**：后端、前端、MCP 包的版本统一。
- [ ] **质量门**：ruff 的规则范围、前端是否需要 lint、覆盖率门槛。

## 影响下游

- 改动启动方式、配置项或命令 → [T3](T3-docs-showcase.md)（README 快速开始、配置文档）
- 删除或移动过程文档 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [ ] 来自 B4-01、B4-02、B4-03：恢复扫描、控制命令和交付终态按事务与租约令牌收口；后台任务按领取身份隔离 → 请复核存储锁顺序和重试边界。
- [ ] 来自 B4-06、B4-12：会话写入使用行锁；本次审查固定现有 55434 数据库和持久卷 → 请按工作规则使用同一套数据库，勿运行会新建或删除数据库的夹具。
- [ ] 来自 B2：Node 22.23.4 / npm 10.9.9 下 `npm ci` 报锁文件缺少 `@rolldown/binding-wasm32-wasi` 及三个传递依赖；现有依赖下 `npm run check` 通过 → 请复核锁文件和干净安装。
- [ ] 来自 B1-01：MCP 和价格默认数据通过配置模型工厂构造 → 请复核配置默认值与生成文档。
- [ ] 来自 B1-04：组件装配失败时关闭已打开的 checkpointer 连接池 → 请复核启动与维护入口的失败处理。
- [ ] 来自 B1-06：checkpoint 清理脚本显式关闭自己构建的组件 → 请复核维护脚本的资源清理。
- [ ] 来自 B1 验证：前端 `npm ci` 报告 21 项依赖漏洞（14 moderate、5 high、2 critical）→ 请区分实际影响并评估依赖更新。

## 问题与修复

- （暂无）
