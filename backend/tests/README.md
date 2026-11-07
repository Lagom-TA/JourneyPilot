# 后端测试指南

后端测试围绕公开接口、核心业务流程与持久化状态组织，通过从公共入口构造业务场景来验证输入解析、状态流转与最终输出，并对外部网络与第三方供应商边界做隔离替身。

## 目录分工

- `api/`、`bootstrap/`、`cli/`：HTTP/SSE 接口、应用生命周期管理与命令行工具测试。
- `planning/`、`conversation/`、`memory/`、`knowledge/`：行程规划、多轮对话、偏好记忆与知识库检索的业务流程测试。
- `runtime/`、`llm/`、`tools/`、`config/`：并发与预算控制、模型适配器、工具注册调用及配置校验测试。
- `integrations/`：第三方数据服务适配器与响应解析测试（离线运行，不发起真实外部请求）。
- `fixtures/`、`support/`：跨测试共享的样本数据构造器、外部服务替身与辅助工具。
- `db/`：面向真实 PostgreSQL 的事务、约束、租约、数据库迁移及备份恢复测试；其中 `db/test_offline_sql.py` 用于离线生成并校验迁移 SQL。
- `conftest.py`：管理测试环境与数据库隔离，运行数据库测试时会自动创建独立的临时数据库（`jp_test_*`）并在测试结束后清理。

## 运行测试

在仓库根目录下执行（将 `UV_PROJECT_ENVIRONMENT` 指向根目录 `.venv`）：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"

# 运行单元测试与离线迁移 SQL 检查（无需启动数据库，与默认 CI 一致）
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
uv run --project backend pytest -c backend/pyproject.toml backend/tests/db/test_offline_sql.py -q

# 运行 PostgreSQL 数据库集成测试（需本地或远程 PostgreSQL 可连接）
JP_TESTS_REQUIRE_POSTGRES=1 uv run --project backend pytest -c backend/pyproject.toml backend/tests/db -q
```

关于 CI 工作流中自动化测试与数据库集成测试的划分，请参阅 [ADR-0009](../../docs/adr/ADR-0009-ci-never-spends-on-providers.md)。
