"""记忆偏好契约。"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.requirements.identity_contracts import PlaceIdentity
from travel_agent.utils.user_text import is_blank
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple


class PreferenceOptionGroup(BaseModel):
    """一组偏好的全部合法取值及其界面称呼。

    选项表只在此处定义。取值原文会经 Constraint Pack 进入模型，界面通过服务端
    接口读取该表，不自行复制。

    ``multi`` 与字段类型对应：``List[str]`` 为多选，``str`` 为单选。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str

    label: str

    multi: bool
    options: Tuple[str, ...]


TRAVEL_PREFERENCE_GROUPS: Tuple[PreferenceOptionGroup, ...] = (
    PreferenceOptionGroup(
        key="travel_styles",
        label="旅行风格",
        multi=True,
        options=(
            "文化探索",
            "自然风光",
            "美食之旅",
            "冒险运动",
            "休闲度假",
            "摄影采风",
        ),
    ),
    PreferenceOptionGroup(
        key="preferred_transport",
        label="交通偏好",
        multi=True,
        options=("飞机", "高铁", "自驾", "公共交通", "骑行", "步行"),
    ),
    PreferenceOptionGroup(
        key="dietary_restrictions",
        label="饮食偏好",
        multi=True,
        options=("本地特色", "中餐", "西餐", "日料", "素食", "清真", "有食物过敏"),
    ),
    PreferenceOptionGroup(
        key="typical_budget_level",
        label="预算档位",
        multi=False,
        options=("经济型", "舒适型", "品质型", "豪华型"),
    ),
    PreferenceOptionGroup(
        key="pace",
        label="旅行节奏",
        multi=False,
        options=("紧凑充实", "适中平衡", "轻松悠闲"),
    ),
    PreferenceOptionGroup(
        key="accommodation_type",
        label="住宿偏好",
        multi=False,
        options=("商务酒店", "民宿", "度假酒店", "青旅", "温泉旅馆"),
    ),
)


PREFERENCE_GROUPS_BY_KEY: Dict[str, PreferenceOptionGroup] = {
    group.key: group for group in TRAVEL_PREFERENCE_GROUPS
}


def _the_one_allergy_option() -> str:
    """返回饮食组中表示「有食物过敏」的选项。

    该值从 ``TRAVEL_PREFERENCE_GROUPS`` 计算，不重复写字面量。带「过敏」的选项
    必须恰好一个，否则抛出异常：固定选项只允许一个「有过敏、过敏原未知」入口，
    具体过敏原通过对话提取。
    """

    group = PREFERENCE_GROUPS_BY_KEY["dietary_restrictions"]
    matches = [option for option in group.options if "过敏" in option]
    if len(matches) != 1:
        raise RuntimeError(
            f"{group.label}里带「过敏」的选项有 {len(matches)} 个（{matches}）："
            "固定选项只许有一个「有过敏、过敏原未知」的入口，具体过敏原走对话那条路"
        )
    return matches[0]


DIETARY_ALLERGY_OPTION: str = _the_one_allergy_option()


def _out_of_table(group: PreferenceOptionGroup, value: str) -> str:
    """返回面向客户端的提示：该组不包含此取值，并列出全部可选项。

    收到提示的调用方需要重新发送合法取值，因此提示中包含完整选项列表。
    """

    return f"{group.label}没有「{value}」这一项，可选：{'、'.join(group.options)}"


class TravelPreference(BaseModel):
    """用户在偏好设置页声明的旅行偏好。

    每个字段都有产品内的写入方：``api/routes/user.py`` 的
    ``PATCH /api/user/preferences``（六组偏好）与 ``PUT /api/user/default-origin``
    （常用出发地）。记忆抽取器不写入任何偏好键，它只写记忆事实、知识图谱与
    ``auto_portrait``。

    合法取值定义在 ``TRAVEL_PREFERENCE_GROUPS``，界面通过
    ``GET /api/user/preference-options`` 读取。字段经 Constraint Pack 进入模型。
    """

    model_config = ConfigDict(extra="forbid")

    travel_styles: List[str] = Field(default_factory=list)
    preferred_transport: List[str] = Field(default_factory=list)
    accommodation_type: str = ""

    dietary_restrictions: List[str] = Field(default_factory=list)

    typical_budget_level: str = ""

    pace: str = ""

    default_origin: Optional[PlaceIdentity] = None

    @model_validator(mode="after")
    def _values_come_from_the_option_table(self) -> "TravelPreference":
        """校验六组取值均来自 `TRAVEL_PREFERENCE_GROUPS`。

        这是该规则的唯一执行点，读写两侧共用：写入侧（`update_preferences`）拦截
        表外取值，读取侧（`_row_to_profile`）保证库中数据可以被界面渲染。

        单选组的空串表示未选择，属于合法值；纯空白不是合法值（判定见
        `utils/user_text.py`）。
        """

        for group in TRAVEL_PREFERENCE_GROUPS:
            raw = getattr(self, group.key)
            if group.multi:
                for value in raw:
                    if is_blank(value):
                        raise ValueError(
                            f"{group.label}收到一个只有空白的取值：空白不是一个值"
                        )
                    if value not in group.options:
                        raise ValueError(_out_of_table(group, value))
                if len(set(raw)) != len(raw):
                    raise ValueError(f"{group.label}里同一项出现了两次")
            else:
                if raw == "":
                    continue
                if is_blank(raw):
                    raise ValueError(
                        f"{group.label}收到一串空白：不选就发空串，别发空白"
                    )
                if raw not in group.options:
                    raise ValueError(_out_of_table(group, raw))
        return self


class UserProfile(BaseModel):
    """用户完整画像"""

    model_config = ConfigDict(extra="forbid")

    user_id: str

    display_name: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    preferences: TravelPreference = Field(default_factory=TravelPreference)

    auto_portrait: str = ""

    revision: int = 0
