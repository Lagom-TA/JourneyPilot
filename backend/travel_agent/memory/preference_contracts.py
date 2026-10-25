"""Memory preference contracts."""

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
    """一组偏好的**全部合法取值**，以及它在界面上怎么被称呼。

    **这是那张选项表在全仓的唯一定义处。**

    定义处定在后端而不是那一屏，理由是**取值本身要进模型**：
    ``panels/constraint.py::_map_manual_profile`` 把这些字符串**原文**映成 Constraint Pack
    的 item，快慢两条路径读的都是它。模型侧看到的是后端这一份，所以界面必须从服务端拿这张表
    （与「地点必须整条来自服务端」同一条口径），不许自己抄。

    ``multi`` 与字段注解是同一件事的两面（``List[str]`` ↔ 多选、``str`` ↔ 单选），
    不许在这里写成第二种说法。
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
    """饮食那一组里表示「这个人有食物过敏」的**那一个**选项。

    **现算自上面那张表，不在这里再抄一个字面量。** 抄一份就是「一个角色两套值」：
    静默胜出的会是 ``_map_manual_profile`` 手上那一份，而界面画的是表里那一份，
    于是勾了过敏而约束里没有过敏。

    ``!= 1`` 直接抛而不是挑一个，因为这里守的是一条硬要求：
    **固定选项表达不了过敏原**。表里出现第二个带「过敏」的选项（比如有人图省事加一个
    ``花生过敏``）就意味着这条要求破了 —— 那种表会让「花生过敏的人」勾得出、
    「荞麦过敏的人」勾不出，而且 ``food_allergy`` 的过敏原从此有两个产地
    （选项字面量与 LLM 抽取）。起不来比悄悄跑着好。
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
    """一句给客户端看的话：这一组没有这个取值，可选的是哪些。

    句子里带上全部可选项，因为收到这句话的人（人或脚本）**下一步就要重新发一次**，
    而「不认识」本身给不出下一步。
    """

    return f"{group.label}没有「{value}」这一项，可选：{'、'.join(group.options)}"


class TravelPreference(BaseModel):
    """用户在「我的偏好」那一屏亲手声明的旅行偏好。

    **这里的每一个字段都必须有产品内的写入方。** 唯一的写入方是
    ``api/routes/user.py``：六组偏好走 ``PATCH /api/user/preferences``，
    出发地走 ``PUT /api/user/default-origin``。记忆抽取器
    （``memory/memory_extractor.py``）**不写任何偏好键** —— 它写记忆事实、
    知识图谱与 ``auto_portrait``，这是两套东西。

    界面上能编辑的那六组是唯一有写入方的合同，两条路径都只认它。

    **每一组的合法取值也在这个文件里**（``TRAVEL_PREFERENCE_GROUPS``），界面从
    ``GET /api/user/preference-options`` 拿它 —— 那一屏不许自己写一份选项表。

    这些字段抵达模型的通道**只有一条**：Constraint Pack 的
    ``panels/constraint.py::_map_manual_profile``，快慢两条路径共用。
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
        """六组取值必须出自 `TRAVEL_PREFERENCE_GROUPS`，一个不多。

        **这是那条规则唯一的执行点**，读写两侧共用：写入侧
        （`memory/user_profile.py::update_preferences` → 这里）拦住表外的值，
        读取侧（`_row_to_profile` → 这里）保证「库里存着的，界面一定画得出来」。
        只在路由上校验会让缺陷在全绿里活下来 —— 别的写入方（播种脚本、验收脚本、
        真库里的旧行）都不经过那道门。

        单选组的空串是「没选」，是合法值；**一串空白不是**（口径在
        `utils/user_text.py`，记忆与资料两处同一条）。
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
