"""未接线的行程编辑入口不得回到 API：这条写路径只有删除，没有兼容层。"""

from __future__ import annotations

import pkgutil
from importlib import import_module

from fastapi import APIRouter
from fastapi.routing import APIRoute

from travel_agent.api import routes as routes_package

_EDIT_PATH_MARKERS = ("/workspace/mutations", "/workspace/undo")


def _all_route_paths() -> set[str]:
    paths: set[str] = set()
    for info in pkgutil.walk_packages(
        routes_package.__path__, routes_package.__name__ + "."
    ):
        module = import_module(info.name)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            paths.update(
                route.path
                for route in router.routes
                if isinstance(route, APIRoute)
            )
    return paths


def test_no_workspace_edit_endpoints_are_registered() -> None:
    offenders = [
        path
        for path in _all_route_paths()
        if any(marker in path for marker in _EDIT_PATH_MARKERS)
    ]
    assert offenders == []
