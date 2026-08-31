# 测试策略

测试保护可观察行为，而不是重复类型系统、源码形状、私有变量或常量表。优先从公共入口
构造一个能复现真实风险的场景；同一行为有代表性用例后，不再为每个字段、字符串和分支
排列组合。

- `tests/` 放不依赖 PostgreSQL 的业务规则、API 和生命周期行为。
- `tests/db/` 放只有真实 PostgreSQL 才能证明的事务、约束、租约、迁移、备份和恢复。
- 类型检查、lint、构建和生成物检查交给各自工具，不用 pytest 读取源码再实现一遍。
- 日志文本、prompt 全文、实现私有函数和兼容旧路径，除非本身是公开或持久化合同，否则
  不单独建测试。

CI 按路径分档：

```bash
uv run pytest tests/ --ignore=tests/db -q
JP_TESTS_REQUIRE_POSTGRES=1 uv run pytest tests/db -q
```

数据库不可用时的 skip 只说明环境缺失，不能作为数据库契约已通过的证据。
