"""JourneyPilot 维护命令入口。

    uv run --project backend python backend/journeypilot.py doctor
    uv run --project backend python backend/journeypilot.py migrate
    uv run --project backend python backend/journeypilot.py backup --label before-upgrade
    uv run --project backend python backend/journeypilot.py restore backups/backup-… --yes

两个入口与 `travel_agent` 包并列，直接执行时不需要额外的导入路径引导。
"""

from travel_agent.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
