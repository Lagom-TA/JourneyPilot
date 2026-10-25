"""Validated release seed for trip planning."""

from travel_agent.planning.requirements.product_contracts import (
    PlannerOption,
    TripPlannerConfiguration,
)

TRIP_PLANNER_SEED = TripPlannerConfiguration(
    primary_styles=[
        PlannerOption(id="balanced", label="经典均衡", is_default=True),
        PlannerOption(
            id="slow", label="轻松慢游", inference_keywords=["轻松", "不太累", "慢"]
        ),
        PlannerOption(id="food", label="当地美食", inference_keywords=["美食", "吃"]),
        PlannerOption(
            id="culture",
            label="人文体验",
            inference_keywords=["人文", "历史", "博物馆"],
        ),
        PlannerOption(
            id="outdoors", label="户外自然", inference_keywords=["户外", "自然", "徒步"]
        ),
        PlannerOption(
            id="family",
            label="亲子友好",
            inference_keywords=["亲子", "孩子", "小孩", "宝宝"],
        ),
    ],
    secondary_interests=[
        PlannerOption(id="hidden_gems", label="小众探索"),
        PlannerOption(id="shopping", label="购物"),
        PlannerOption(id="nightlife", label="夜生活"),
        PlannerOption(id="photography", label="摄影"),
        PlannerOption(id="stays", label="住宿体验"),
        PlannerOption(id="public_transport", label="公共交通"),
        PlannerOption(id="local_food", label="在地饮食"),
        PlannerOption(id="slow_pace", label="慢节奏"),
    ],
    default_adults=1,
    default_children=0,
    default_elderly_companions=False,
    default_accessibility_required=False,
    max_secondary_interests=2,
    inspiration_rotation_ms=6500,
    inspiration_prompts=[
        "秋天想带爸妈去一个不太累、吃得好的地方，大约 6 天",
        "想找一个适合第一次独自旅行的海边城市，预算 5000 元",
        "计划和孩子看动物、坐火车，行程不要太赶",
        "想用一周体验当地市场、博物馆和社区生活",
        "我们喜欢徒步和摄影，希望每天保留充足的日落时间",
    ],
)


def validated_trip_planner_seed() -> TripPlannerConfiguration:
    """Return the release seed after validating the current product contract."""
    return TripPlannerConfiguration.model_validate(
        TRIP_PLANNER_SEED.model_dump(mode="json")
    )
