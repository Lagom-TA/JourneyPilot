from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT


def _settings() -> Any:
    from ..config.loader import get_settings

    return get_settings()


def _target(settings: Any, database: str | None = None) -> Any:
    from ..storage.maintenance.connection import DatabaseTarget

    return DatabaseTarget.from_settings(settings, database=database)


def _backup_root(settings: Any, override: str | None = None) -> Path:

    raw = override or settings.maintenance.backup_dir
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path)
