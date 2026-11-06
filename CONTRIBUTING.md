# 参与贡献

欢迎 Issue 与 Pull Request。开始前请先读 [README](README.zh-CN.md#快速开始) 与 [AGENTS.md](AGENTS.md)。

## 开发环境

```bash
cp backend/config.example.yaml config.yaml   # 填好模型段；Key 走环境变量
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
JOURNEYPILOT_DATABASE__PORT=55434 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

前端与后端的端口、日志、重启行为见 [本地启动排障](docs/local-development-troubleshooting.md)。

## 提交前检查

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"

uv run --project backend ruff check --config backend/pyproject.toml backend/travel_agent/ backend/tests/ backend/scripts/
uv run --project backend python backend/journeypilot.py config docs --check
uv run --project backend python backend/journeypilot.py config validate
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q

cd frontend && npm ci && npm run check
```

数据库测试需要 PostgreSQL（`JP_TESTS_REQUIRE_POSTGRES=1`）；浏览器测试按 [frontend/e2e/README.md](frontend/e2e/README.md) 运行。跳过不等于通过。

## 代码与文档约定

- 产品界面、文档、注释用中文；代码标识符、配置键、API 字段与命令输出用英文。
- 注释只描述当前行为，不写版本演进、兼容层、迁移史或事故复盘。
- 新增配置字段必须同时更新 `backend/config.example.yaml`（由维护者合并）并重新生成 `docs/configuration.md`、`docs/config.schema.json`；生成物不允许手改。
- 修复缺陷请补回归测试；行为变化同步更新 README 中英两版与相关文档。
- 不接受兼容旧数据/旧接口的分支；本项目只维护当前结构与当前合同。

## PR 要求

- 一次 PR 只做一件事，描述里写清动机、根因、改动清单、验证方式、风险与回滚。
- 新增依赖需要说明用途；安全相关问题请按 [SECURITY.md](SECURITY.md) 私下报告。
