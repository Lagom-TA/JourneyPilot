# 后端测试指南

后端测试围绕公开接口、核心业务流程与持久化状态组织，通过从公共入口构造业务场景来验证输入解析、状态流转与最终输出，并对外部网络与第三方供应商边界做隔离替身。

## 目录分工

- `api/`、`bootstrap/`、`cli/`：HTTP/SSE 接口、应用生命周期管理与命令行工具测试。
- `planning/`、`conversation/`、`memory/`、`knowledge/`：行程规划、多轮对话、偏好记忆与知识库检索的业务流程测试。
- `runtime/`、`llm/`、`tools/`、`config/`：并发与预算控制、模型适配器、工具注册调用及配置校验测试。
- `integrations/`：第三方数据服务适配器与响应解析测试（离线运行，不发起真实外部请求）。
- `fixtures/`、`support/`：跨测试共享的样本数据构造器、外部服务替身与辅助工具。
- `db/`：面向真实 PostgreSQL 的事务、约束、租约、数据库迁移及备份恢复测试；其中 `db/test_offline_sql.py` 用于离线生成并校验迁移 SQL。
- `conftest.py`：隔离用量记录器并管理数据库夹具；使用 `temp_database` 的用例会创建独立的临时数据库（`jp_test_*`）并在测试结束后清理。

## 测试隔离与真实边界

- 每个用例的默认用量记录器使用独立的内存 SQLite，结束后关闭连接并还原单例，待确认记录与失败计数不会传给下一例。测试会话为默认 spool 路径提供临时目录，退出时恢复原环境变量；验证落盘、重新打开与进程中断恢复的用例继续显式使用 `tmp_path`。
- `llm/` 是离线模型适配测试，HTTP 响应由替身提供。该目录自动使用 `offline_http_environment`，临时移除大小写的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`，避免 SDK 初始化同步客户端时被开发机代理影响；结束后恢复。其他目录中需要这项隔离的离线用例显式请求该夹具，真实集成环境不受影响。
- `support/` 的内存仓储用于流程、状态与投影测试。真实 PostgreSQL 中的事务、唯一约束、锁和迁移仍由 `db/` 验证，内存结果不能替代数据库验收。

## 运行测试

在仓库根目录下执行（将 `UV_PROJECT_ENVIRONMENT` 指向根目录 `.venv`）：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"

# 运行单元测试与离线迁移 SQL 检查（无需启动数据库，与默认 CI 一致）
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
uv run --project backend pytest -c backend/pyproject.toml backend/tests/db/test_offline_sql.py -q

# 运行使用临时数据库的集成测试（需可连接且允许创建/删除测试库的 PostgreSQL）
JP_TESTS_REQUIRE_POSTGRES=1 uv run --project backend pytest -c backend/pyproject.toml backend/tests/db -q
```

`JP_TESTS_REQUIRE_POSTGRES=1` 将临时数据库连接不可用视为失败；它不会启用以下配置库回滚测试。这三组需要显式开关，并要求当前配置库已迁移到最新结构：

| 测试文件 | 开关 | 保护行为 |
| --- | --- | --- |
| `db/test_runtime_rollback.py` | `JP_RUNTIME_ROLLBACK_TESTS=1` | 运行事务、租约和恢复 |
| `db/test_memory_extraction_rollback.py` | `JP_MEMORY_EXTRACTION_ROLLBACK_TESTS=1` | 记忆抽取提交与回滚 |
| `db/test_memory_lifecycle_rollback.py` | `JP_MEMORY_LIFECYCLE_ROLLBACK_TESTS=1` | 记忆删除、管理历史与并发状态 |

```bash
# 使用当前配置库的临时表与始终回滚的外层事务
JP_RUNTIME_ROLLBACK_TESTS=1 \
JP_MEMORY_EXTRACTION_ROLLBACK_TESTS=1 \
JP_MEMORY_LIFECYCLE_ROLLBACK_TESTS=1 \
uv run --project backend pytest -c backend/pyproject.toml \
  backend/tests/db/test_runtime_rollback.py \
  backend/tests/db/test_memory_extraction_rollback.py \
  backend/tests/db/test_memory_lifecycle_rollback.py -q
```

回滚夹具直接复制当前表结构，不补建缺失的业务字段；初始化失败也会释放连接池。临时表与单连接保存点用于验证特定写入及回滚行为，不代表多连接竞争或完整外键约束已通过；这些边界继续由临时数据库用例负责。未启用的测试会显示跳过，应与实际通过的测试分别报告。

关于 CI 工作流中自动化测试与数据库集成测试的划分，请参阅 [ADR-0009](../../docs/adr/ADR-0009-ci-never-spends-on-providers.md)。
