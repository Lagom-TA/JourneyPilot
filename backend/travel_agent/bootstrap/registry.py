"""进程内应用组件注册表。"""

from typing import Optional

from travel_agent.bootstrap.components import AppComponents

_components: Optional[AppComponents] = None


def get_components() -> AppComponents:
    """取得已初始化的组件；未初始化时抛错。"""
    if _components is None:
        raise RuntimeError(
            "AppComponents 尚未初始化，请确保在 FastAPI 启动事件中调用 build_components()"
        )
    return _components


def set_components(components: AppComponents) -> None:
    """发布构建好的组件供运行时读取。"""
    global _components
    _components = components


def registered_components() -> Optional[AppComponents]:
    """读取当前注册表；关闭阶段允许尚未初始化。"""
    return _components
