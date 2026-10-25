"""The single process-local application component registry."""

from typing import Optional

from travel_agent.bootstrap.components import AppComponents

_components: Optional[AppComponents] = None


def get_components() -> AppComponents:
    """Require an initialized application registry."""
    if _components is None:
        raise RuntimeError(
            "AppComponents 尚未初始化，请确保在 FastAPI 启动事件中调用 build_components()"
        )
    return _components


def set_components(components: AppComponents) -> None:
    """Publish the constructed components to runtime consumers."""
    global _components
    _components = components


def registered_components() -> Optional[AppComponents]:
    """Read the current registry without requiring initialization during shutdown."""
    return _components
