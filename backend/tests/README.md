# 测试策略

测试保护可观察行为，而不是重复类型系统、源码形状、私有变量或常量表。优先从公共入口
构造一个能复现真实风险的场景；同一行为有代表性用例后，不再为每个字段、字符串和分支
排列组合。

- `api/`、`bootstrap/`、`cli/`：HTTP/SSE、应用生命周期和命令行行为。
- `planning/`、`conversation/`、`memory/`、`knowledge/`：各领域的实际输入、输出和状态变化。
- `runtime/`、`llm/`、`tools/`、`config/`：执行控制、模型适配、工具调用与配置行为。
- `fixtures/`：共享的业务数据构造和外部依赖替身；测试与实验脚本直接导入这些定义，不从其他测试模块取夹具。
- `db/`：真实 PostgreSQL 的事务、约束、租约、迁移、备份和恢复；`test_offline_sql.py` 只生成并检查 SQL，不连接数据库。
- 根 `conftest.py` 保留临时数据库隔离：仅使用随机命名的 `jp_test_*` 数据库，同步切换环境、配置和引擎，并在删库前关闭引擎。
- 类型检查、lint、构建和生成物检查交给各自工具，不用 pytest 读取源码再实现一遍。
- 日志文本、prompt 全文、实现私有函数和兼容旧路径，除非本身是公开或持久化合同，否则
  不单独建测试。

自动 CI 运行非数据库测试和 `db/test_offline_sql.py`。数据库迁移与集成测试可在 Actions 的 `PR` 工作流中手动触发，或在本地数据库就绪后执行：

```bash
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
uv run --project backend pytest -c backend/pyproject.toml backend/tests/db/test_offline_sql.py -q
JP_TESTS_REQUIRE_POSTGRES=1 uv run --project backend pytest -c backend/pyproject.toml backend/tests/db -q
```

数据库不可用时的 skip 只说明环境缺失，不能作为数据库契约已通过的证据。
