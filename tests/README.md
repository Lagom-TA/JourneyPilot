# 测试怎么分档、文件怎么起名

这三条约定原本只写在 `test_run_command_contract.py` 的 docstring 里 —— 那个位置只有
已经打开那个文件的人看得到，而需要知道它的恰好是正要新建一个测试文件的人。

## 1. 规则本身用假 store，需要真库的那半进 `tests/db/`

同一件事经常有两半：**判断规则**和**存储保证**。它们分开放。

- **规则本身进 `tests/`**：一个假 store 就够。摘要口径怎么算、什么时候收口、
  协作边界怎么去重 —— 这些是纯逻辑，接一个真 PostgreSQL 只是让它慢，不会让它
  多验证任何东西。
- **需要真库的那半进 `tests/db/`**：验的东西在任何 mock 里都不存在。「重发落回
  同一行」靠的是一个唯一约束，「同一条命令不会被两个协程各消费一次」靠的是
  `FOR UPDATE SKIP LOCKED`，「结论不可改写」靠的是数据库自己。用 sqlite 或 mock
  跑出来的绿灯，恰好在这些不变量上没有意义。

`test_run_command_contract.py` 与 `db/test_run_commands.py` 是这条的样板：同一组
控制命令，规则那半在前者，存储保证那半在后者，两边 docstring 互相指路。

## 2. `*_contract.py` 表示「测的是跨文件的一条规则」，不是「测一个模块」

一个 `_contract` 文件的主语是**规则**，不是文件。它守的通常是「两个文件里各写了
一遍的同一件事」或者「一个声明和它的执行面」—— 这类东西没有单一 owner 模块可测，
漂了也不会有人报错，只会静默降级。

所以取名按守的那条规则取，不按被测的模块取。`test_tool_policy_contract.py` 的入口
函数在 `agents/utils.py` 里，但它守的规则跨三处：`_AGENT_TOOL_POLICY` 声明的 worker
名单、`node_names.WORKER_NODES` 里图上真有的 worker、以及配置里真的配了的 MCP
server。名字里不出现 `utils`，因为它测的不是那个模块。

## 3. 分档靠路径，不靠 marker

CI 就是按路径分的，没有第二套规则：

- `.github/workflows/pr.yml:47` — `uv run pytest tests/ --ignore=tests/db -q`
- `.github/workflows/pr.yml:99` — `uv run pytest tests/db -q`（`JP_TESTS_REQUIRE_POSTGRES=1`）

一个测试属于哪一档，取决于它放在哪个目录，不取决于它带什么 marker。想让某条走
数据库那一档，把文件移进 `tests/db/`；不要加 marker 然后指望有人去改 CI 的选择器。

（`tests/db/` 下几个文件确实挂了 `pytestmark = pytest.mark.postgres`，但那个 marker
不参与选择：CI 两档都没有 `-m`。它和 `conftest.py` 的 `postgres_available` 一起决定
连不上库时是跳过还是失败 —— 是**同一档内**的降级策略，不是分档手段。）
