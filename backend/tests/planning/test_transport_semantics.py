"""换乘只统计已证实的乘坐服务变化。"""

from travel_agent.planning.transport import TransportEndpoint, TransportSegment
from travel_agent.planning.transport_semantics import count_service_transfers


def _stop(name):
    return TransportEndpoint(name=name)


def _segment(index, mode, *, from_name, to_name, line_name=None, service_number=None):
    return TransportSegment(
        segment_id=f"segment_{index}",
        mode=mode,
        from_endpoint=_stop(from_name),
        to_endpoint=_stop(to_name),
        line_name=line_name,
        service_number=service_number,
    )


def test_walking_access_around_one_metro_line_is_not_a_transfer():
    segments = [
        _segment(1, "walk", from_name="饭店", to_name="地铁站"),
        _segment(2, "metro", from_name="地铁站", to_name="景区站", line_name="1号线"),
        _segment(3, "walk", from_name="景区站", to_name="景区"),
    ]

    assert count_service_transfers(segments) == 0


def test_the_same_metro_line_split_into_two_segments_is_not_a_transfer():
    segments = [
        _segment(1, "metro", from_name="甲站", to_name="乙站", line_name="1号线"),
        _segment(2, "metro", from_name="乙站", to_name="丙站", line_name="1号线"),
    ]

    assert count_service_transfers(segments) == 0


def test_two_different_metro_lines_count_as_one_transfer():
    segments = [
        _segment(1, "metro", from_name="甲站", to_name="乙站", line_name="1号线"),
        _segment(2, "metro", from_name="乙站", to_name="丙站", line_name="2号线"),
    ]

    assert count_service_transfers(segments) == 1
