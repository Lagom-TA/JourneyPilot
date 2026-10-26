# 测试策略

每个测试回答一个问题：**给定这组输入，关键输出或状态变化是什么。** 测试按行为命名，断言用户可见结果、持久化事实或公开合同，不断言实现细节。

- 优先少量端到端行为测试：从公共入口构造真实场景，一次覆盖解析、状态变化和输出。
- 不为覆盖率数字堆测试。同一行为有代表性用例后，不再为每个字段、字符串和分支排列组合。
- 不写门控断言、哈希、golden 或快照对照、事故复盘矩阵。
- 只对真正的外部边界做替身；不串联多层 mock 去模拟内部调用顺序。
- 日志文本、prompt 全文、私有函数和旧路径不单独建测试，除非它们本身是公开或持久化合同。
- 类型检查、lint、构建和生成物检查交给各自工具，不用 pytest 读取源码再实现一遍。

目录分工：

- `api/`、`bootstrap/`、`cli/`：HTTP/SSE、应用生命周期和命令行行为。
- `planning/`、`conversation/`、`memory/`、`knowledge/`：各领域的实际输入、输出和状态变化。
- `runtime/`、`llm/`、`tools/`、`config/`：执行控制、模型适配、工具调用与配置行为。
- `fixtures/`：共享的业务数据构造和外部依赖替身；测试与实验脚本直接导入这些定义，不从其他测试模块取夹具。
- `db/`：真实 PostgreSQL 的事务、约束、租约、迁移、备份和恢复；`db/test_offline_sql.py` 只生成并检查 SQL，不连接数据库。
- 根 `conftest.py` 保留临时数据库隔离：仅使用随机命名的 `jp_test_*` 数据库，同步切换环境、配置和引擎，并在删库前关闭引擎。

自动 CI 运行非数据库测试和 `db/test_offline_sql.py`。数据库迁移与集成测试可在 Actions 的 `PR` 工作流中手动触发，或在本地数据库就绪后执行：

```bash
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
uv run --project backend pytest -c backend/pyproject.toml backend/tests/db/test_offline_sql.py -q
JP_TESTS_REQUIRE_POSTGRES=1 uv run --project backend pytest -c backend/pyproject.toml backend/tests/db -q
```

数据库不可用时的 skip 只说明环境缺失，不能作为数据库契约已通过的证据。
