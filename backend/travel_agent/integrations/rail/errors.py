"""12306 查询的异常类型。"""

from __future__ import annotations


class Rail12306Error(RuntimeError):
    """不能报告成「没有车次」的任何失败。"""


class StationNotFoundError(Rail12306Error):
    """站名或电报码不在已提交的站表快照中。"""


class QueryRefusedError(Rail12306Error):
    """12306 拒绝了请求：重定向、过期路径或不可用的响应体。"""
