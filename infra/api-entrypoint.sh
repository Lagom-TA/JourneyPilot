#!/bin/sh
# API 容器的启动编排器。与 run.sh 走同一个 Python 编排器。
#
# 顺序不可交换：API 进程不建表（迁移先行原则），所以迁移必须先跑完。
# 不用 `uv run`：/opt/journeypilot 已在 PATH 上，而它会去校验并可能改写 lockfile。
set -e

echo "[entrypoint] 校验配置…"
if ! python backend/journeypilot.py config validate; then
    echo "[entrypoint] 配置无效，不启动 API。" >&2
    exit 1
fi

echo "[entrypoint] 数据库迁移（API 之前）…"
if ! python backend/journeypilot.py migrate; then
    echo "[entrypoint] 迁移未通过，不启动 API。" >&2
    echo "[entrypoint] 诊断：docker compose -f infra/compose.yml run --rm api python backend/journeypilot.py doctor" >&2
    exit 1
fi

echo "[entrypoint] 启动 API…"
exec python backend/main.py
