# 本地开发

本文件给在本仓库工作的开发者与自动化 agent：启动方式、常用命令、语言与注释规范、提交前检查。

## 启动

在仓库根目录启动（依赖与首次配置见 [README](README.zh-CN.md#快速开始)）：

```bash
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

- 前端：http://localhost:8080；API 文档：http://localhost:8001/docs。
- 管理：`./run.sh status`、`./run.sh restart`、`./run.sh stop`、`./run.sh logs [backend|frontend]`、`./run.sh help`。
- `restart` 不会保存环境变量：它等价于 `stop` + 重新执行 `start`。端口或数据库/Redis 覆盖要么每次带上，要么写进 `config.yaml`。
- 前端支持热更新；`run.sh` 启动的后端固定关闭自动重载，修改 Python 代码后需要 `./run.sh restart`。
- 本地开发、调试和测试统一使用当前配置的数据库，不另建数据库或切换到其他库，除非用户明确要求。删除、清空、重建数据库或其他可能批量破坏现有数据的操作，须先确认影响并取得用户明确授权。
- 启动失败、端口冲突或服务异常时，按需查阅 [本地启动排障](docs/local-development-troubleshooting.md)。

## 语言与注释

- 产品界面用简体中文；代码标识符、配置键、API 字段与命令输出用英文。
- 注释、docstring 与项目文档用中文，只描述**当前**行为：不写版本演进、兼容层、迁移史或事故复盘。
- 不新增 `TODO`/`FIXME`/被注释掉的代码；解释为什么和边界，不复述代码在做什么。
- 不改生成物：`docs/configuration.md`、`docs/config.schema.json` 由 `journeypilot config docs` 生成；`backend/config.example.yaml` 由维护者维护。

## 文档

- 文档索引入口：[docs/README.md](docs/README.md)；行为变化同步更新 README 中英两版与相关 docs。
- 运行时约定（代码必须保持的约束）：[docs/invariants.md](docs/invariants.md)；架构决策：[docs/adr/README.md](docs/adr/README.md)。

## 提交前检查

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
uv run --project backend ruff check --config backend/pyproject.toml backend/travel_agent/ backend/tests/ backend/scripts/
uv run --project backend python backend/journeypilot.py config docs --check
uv run --project backend python backend/journeypilot.py config validate
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
cd frontend && npm ci && npm run check
```

需要浏览器回归时按 [frontend/e2e/README.md](frontend/e2e/README.md) 启动真实服务后运行 Playwright；它不在默认 CI 中。
