from __future__ import annotations


def planned_boarding_buffer_minutes(mode: object) -> int:
    """航班起飞前预留 90 分钟，其他长途交通预留 30 分钟。

    该默认值需要作为规划假设披露。运营方公布的截止时间或用户给出的更大
    余量优先；Provider 的实际出发时间不会被修改。
    """
    return 90 if str(getattr(mode, "value", mode)) == "flight" else 30


def planned_alighting_buffer_minutes(mode: object) -> int:
    """航班到达后预留 45 分钟，其他长途到达后预留 15 分钟。

    这段时间用于下机并离开场站，之后才计算单独的市内路线；它不是 Provider
    的保证。
    """
    return 45 if str(getattr(mode, "value", mode)) == "flight" else 15
