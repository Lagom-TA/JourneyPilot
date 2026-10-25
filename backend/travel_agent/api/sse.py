import json


def sse_event(data: dict) -> str:
    """格式化为 SSE 事件字符串"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
