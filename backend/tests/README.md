# 测试策略

每个测试回答一个问题：**给定这组输入，关键输出或状态变化是什么。** 测试按行为命名，断言用户可见结果、持久化事实或公开合同，不断言实现细节。

- 优先少量端到端行为测试：从公共入口构造真实场景，一次覆盖解析、状态变化和输出。
- 不为覆盖率数字堆测试。同一行为有代表性用例后，不再为每个字段、字符串和分支排列组合。
- 不写门控断言、哈希、golden 或快照对照、事故复盘矩阵。
- 只对真正的外部边界做替身；不串联多层 mock 去模拟内部调用顺序。
- 日志文本、prompt 全文、私有函数和旧路径不单独建测试，除非它们本身是公开或持久化合同。
- 类型检查、lint、构建和生成物检查交给各自工具，不用 pytest 读取源码再实现一遍。

## 目录分工

- `api/`、`bootstrap/`、`cli/`：HTTP/SSE、应用生命周期和命令行行为。
- `planning/`、`conversation/`、`memory/`、`knowledge/`：各领域的实际输入、输出和状态变化。
- `runtime/`、`llm/`、`tools/`、`config/`：执行控制、模型适配、工具调用与配置行为。
- `integrations/`：供应商适配与外部响应路径；不访问真实网络。
- `fixtures/`、`support/`：共享的业务数据构造、外部依赖替身与辅助函数；测试直接导入这些定义。
- `db/`：真实 PostgreSQL 的事务、约束、租约、迁移、备份和恢复；`db/test_offline_sql.py` 只生成并检查 SQL，不连接数据库。
- 根 `conftest.py` 保留临时数据库隔离：仅使用随机命名的 `jp_test_*` 数据库，同步切换环境、配置和引擎，并在删库前关闭引擎。

## 运行

在仓库根目录执行（`UV_PROJECT_ENVIRONMENT` 指向根目录 `.venv`）：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"

# 非数据库测试 + 离线迁移 SQL（CI 自动运行）
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
uv run --project backend pytest -c backend/pyproject.toml backend/tests/db/test_offline_sql.py -q

# 数据库集成测试（需要 PostgreSQL；CI 的 PR 工作流可手动触发）
JP_TESTS_REQUIRE_POSTGRES=1 uv run --project backend pytest -c backend/pyproject.toml backend/tests/db -q
```

数据库不可用时的 skip 只说明环境缺失，不能作为数据库契约已通过的证据。CI 自动运行的范围与手动触发的数据库 job 见 [ADR-0009](../../docs/adr/ADR-0009-ci-never-spends-on-providers.md)。
