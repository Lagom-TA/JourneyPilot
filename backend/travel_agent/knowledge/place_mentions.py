"""知识库分块提到的地点，以及这些地点在一次 Run 中走到了哪一步。

知识库不能直接把地点写进行程：Candidate 的 ``place_id`` 必须来自 Provider 结果
（身份不由模型编写）。分块能做的是提名：写出一个地名，由 worker 通过
``global_place_search`` 解析，与用户直接点名走同一条路径。链路有四步::

    分块提到 X  ->  worker 查询 X  ->  X 进入 eligible_place_options
    ->  X 成为 Candidate

本模块只统计这条链路的数量：不做决策、不过滤、不阻断。

``propose_place_mentions`` 是分母，属于召回启发式：它会多报，包括并非地名的
字符串。它不表示「这段正文包含这些地点」，只表示「这些字符串值得向 Provider
查询」。字符串是否真实地点只能由 Provider 判断。

分子来自 Run 的实际行为：worker 发出的查询、Gateway 放行的选项、packet 携带的
Candidate，因此第 2-4 步是精确的。

名称比较只用于第一步（``mention_matches_name``：这个提名是否就是 worker 查询的
对象），两侧都使用语料自身的文字。查询之后一律按 ``place_id`` 连接
（:class:`PlaceLookup`）：它记录身份来自哪次调用、该调用是否由提名触发。名称
在查询之后不再比较：语料写 浅草寺、Provider 返回 淺草寺 或英文名时，名称比较
会丢失结果，而 Provider 生成的身份没有这个问题。

本模块所有函数都是纯函数：不使用时钟、provider、I/O 或全局状态。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

# 具体可访问地名常见的结尾词。这是召回词表，不是地名的定义：漏掉一个名字只
# 会让测量少算，误报一个名字只多一次返回空的 Provider 查询；两者都不会放行
# 任何内容，因此词表可以宽，也可以不完整。
#
# 地区词（市 / 省 / 区 / 县 / 州）刻意不在这里：即便出现，Provider 会把杭州
# 标注为 ``boundary;administrative;city``，``is_administrative_provider_type``
# 已能判断它是区域而非停靠点。
CONCRETE_PLACE_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        {
            # 宗教与古迹
            "寺", "庙", "观", "祠", "陵", "墓", "塔", "宫", "殿", "庵", "庄",
            # 自然与园林
            "园", "公园", "花园", "植物园", "动物园", "山庄", "湖", "山", "峰",
            "岭", "洞", "泉", "岛", "湾", "溪", "潭", "瀑布", "湿地", "濕地",
            "江", "河", "港", "温泉",
            # 建筑与文化设施
            "楼", "阁", "亭", "台", "桥", "堂", "馆", "博物馆", "纪念馆",
            "美术馆", "图书馆", "剧院", "剧场", "书院", "故居", "遗址", "印社",
            "碑林", "城墙", "城楼", "门", "府", "宅", "院", "寺塔",
            # 街区与商业
            "街", "巷", "弄", "坊", "路", "大道", "广场", "商城", "市场",
            "夜市", "美食街", "步行街", "古镇", "古村", "村", "老街",
            # 交通
            "站", "车站", "机场", "码头", "隧道",
            # 主题与度假
            "乐园", "游乐园", "度假区", "景区", "风景区", "水库", "农庄", "茶园",
            # 餐饮与住宿
            "酒店", "饭店", "宾馆", "餐厅", "茶楼", "菜馆", "食府", "客栈",
            "面馆", "酒家",
        },
        key=len,
        reverse=True,
    )
)

# 不能出现在地名内部、用来确定左边界的字符。刻意取窄：范围过宽会截断真实
# 名称——为了 中间 / 周边 / 介绍 / 以上 而收进 中 / 周 / 绍 / 上，会把
# 中国茶叶博物馆、周庄古镇、绍兴北站、上海虹桥站截在首字。宁可让动词留在
# 名字前，也不要截断名字。
#
# 因此这个集合刻意不完整：没有字符表能枚举所有可以出现在地名前的动词，
# 语料里的「该段落介绍苏州博物馆」会带着动词成为一个提名。
# ``mention_matches_name`` 仍能把它与 Provider 的「苏州博物馆」匹配上，
# 不需要生成去掉动词的变体（变体会让分母增加大量噪声）。
_NAME_BOUNDARY_CHARS = frozenset(
    "的和与及有是在为等或从把被让即将也都还很更最就才只再又如而但所因由此这那些"
    "位于拥有现有包括始建成其多余约共计据说达到超过并无"
    "一二三四五六七八九十百千万亿第年月日号处座条例比称作叫做"
)

# 任何不是 CJK 汉字、字母或数字的字符都结束一个片段：地名不会跨标点，语料
# 用 、 分隔列表。
_SEGMENT_SPLIT = re.compile(r"[^一-鿿㐀-䶿 A-Za-z0-9]+".replace(" ", ""))

# 短于该长度的提名无法标识任何地点（西湖是语料中最短的真实地名）；更长的是
# 句子而不是名字。
_MIN_MENTION_CHARS = 2
_MAX_MENTION_CHARS = 10


@dataclass(frozen=True)
class PlaceMention:
    """分块可能用来指代地点的字符串。

    ``left_edge_is_clean`` 记录左边界是由边界字符或片段开头确定，还是被
    ``_MAX_MENTION_CHARS`` 强制截断。强制截断的提名更可能是被截断的句子，
    因此只能负担少量 Provider 查询的调用方应优先使用 clean 的提名。
    """

    text: str
    left_edge_is_clean: bool


def propose_place_mentions(text: str) -> tuple[PlaceMention, ...]:
    """返回 ``text`` 中所有形似可访问地名的字符串。

    排序：左边界干净的在前，然后长者优先，因此截断列表时保留最像地名的提名。
    结果是确定性的：同一文本总是得到相同顺序的列表。
    """

    proposals: dict[str, bool] = {}
    # wiki 链接形如 "大明山 (浙江)|大明山"；竖线分隔的是同一个名称的两种写法，
    # 不是两个名称。
    for segment in _SEGMENT_SPLIT.split(str(text or "").replace("|", " ")):
        if not segment:
            continue
        for suffix in CONCRETE_PLACE_SUFFIXES:
            start = 0
            while (hit := segment.find(suffix, start)) >= 0:
                end = hit + len(suffix)
                left = hit
                while (
                    left > 0
                    and (end - left) < _MAX_MENTION_CHARS
                    and segment[left - 1] not in _NAME_BOUNDARY_CHARS
                ):
                    left -= 1
                mention = segment[left:end]
                clean = left == 0 or segment[left - 1] in _NAME_BOUNDARY_CHARS
                if _is_proposable(mention):
                    proposals[mention] = proposals.get(mention, False) or clean
                start = end
    return tuple(
        PlaceMention(text=mention, left_edge_is_clean=clean)
        for mention, clean in sorted(
            proposals.items(), key=lambda item: (not item[1], -len(item[0]), item[0])
        )
    )


def _is_proposable(mention: str) -> bool:
    return (
        _MIN_MENTION_CHARS <= len(mention) <= _MAX_MENTION_CHARS
        and not mention.isdigit()
        # A bare category word ("车站", "公园") names no particular place.
        and mention not in CONCRETE_PLACE_SUFFIXES
    )


def _normalize(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def mention_matches_name(mention: str, name: str) -> bool:
    """``name`` 是否是提名 ``mention`` 的另一种写法。

    双向包含：提名可能带查询没有的动词（「该段落介绍苏州博物馆」对
    「苏州博物馆」），也可能少一个字（「州工艺美术博物馆」对
    「杭州工艺美术博物馆」）。长度下限避免退化成「匹配任何内容」：否则一个
    名为 公路 的记录会确认所有包含 公路 的提名。

    这是同一侧写出的两个字符串之间的比较（分块与 worker 输入的查询，或分块
    与语料普查按原名查询的名称），不用于判断 Provider 的答案是否同一地点；
    该判断由 ``place_id`` 完成。
    """

    left, right = _normalize(mention), _normalize(name)
    if len(left) < _MIN_MENTION_CHARS or len(right) < _MIN_MENTION_CHARS:
        return False
    if not (left == right or left in right or right in left):
        return False
    return min(len(left), len(right)) * 2 >= max(len(left), len(right))


def query_carries_mention(query: str, mention: str) -> bool:
    """worker 是否把这个提名写进了 Provider 查询。

    查询是组合出来的，不是规范形式：worker 通常会写读到的名称加罗马字或城市，
    如 ``浅草寺 Sensoji``、``灵隐寺 杭州``。对整串比较时，长度下限会因名称
    占比过小而拒绝提名。因此按 ``_SEGMENT_SPLIT`` 分段比较，与提名器切分正文
    的方式一致；每个片段内部仍受长度下限约束，``公路`` 仍然不能确认
    ``杭金衢高速公路``。
    """

    if mention_matches_name(mention, query):
        return True
    return any(
        mention_matches_name(mention, segment)
        for segment in _SEGMENT_SPLIT.split(str(query or ""))
        if segment
    )


@dataclass(frozen=True)
class ProviderIdentity:
    """Provider 返回的一个地点：它生成的身份 id 与它使用的名称。

    ``place_id`` 是下游整条链路的键，也是 packet schema 用来固定 Candidate
    身份的同一个值。``name`` 仅用于日志，不参与任何判断。
    """

    place_id: str
    name: str


@dataclass(frozen=True)
class PlaceLookup:
    """一次地点 Provider 调用：查询内容与返回的身份。

    这个对象把漏斗从四次独立的字符串比较变成一条链：分块提名一个名称，worker
    查询它，该次调用返回的身份都属于这次提名。

    返回空的调用也保留在这里，``identities=()``：「查询了但没找到」与「从未
    查询」是测量最需要区分的两种状态，只有后者说明提示词失败。
    """

    query: str
    identities: tuple[ProviderIdentity, ...] = ()


@dataclass(frozen=True)
class PlaceFunnel:
    """一轮 worker 的分块到 Candidate 提名链，按地点计数。

    **各步按地点计数，而不是按提名字符串计数。** 同一句话里的「杭州西湖」
    「距离西湖」「西湖」「请见西湖」「中西湖」是五个提名，但只指一个地点；
    按提名计数会把一个地点报成五个。

    第 3-5 步保存 ``ProviderIdentity`` 而不是名称，因此 Provider 用同名表示的
    两个不同地点计为两个，语料与 Provider 拼写不同的同一个地点计为一个。
    ``queried`` 保持查询字符串：该步还没有身份，且查询后返回空的调用也必须
    可见。

    每一步都是前一步的子集，因此两个数字之间的下降一定是该步的真实损失。

    ``mentions`` 保留在提名侧，因为它是分母，也是这里唯一的启发式数字。
    """

    injected_chunks: int
    mentions: tuple[str, ...]
    queried: tuple[str, ...]
    resolved: tuple[ProviderIdentity, ...]
    eligible: tuple[ProviderIdentity, ...]
    admitted: tuple[ProviderIdentity, ...]

    def as_log_line(self) -> str:
        def names(identities: Sequence[ProviderIdentity]) -> list[str]:
            """Provider 名称，重复项折叠成 ``名字×N``。

            一次查询常返回多个不同地点而 Provider 用同一名称表示（西湖可以是
            湖、区和景区）。计数必须保持 3，但日志里打印三次西湖会像程序错误，
            而不是 Provider 的事实。
            """
            counted: dict[str, int] = {}
            for identity in identities:
                counted[identity.name] = counted.get(identity.name, 0) + 1
            return [
                name if count == 1 else f"{name}×{count}"
                for name, count in counted.items()
            ]

        return (
            f"chunks={self.injected_chunks} mentions={len(self.mentions)} "
            f"queried={len(self.queried)} resolved={len(self.resolved)} "
            f"eligible={len(self.eligible)} admitted={len(self.admitted)}"
            f" | queried={list(self.queried)} eligible={names(self.eligible)}"
            f" admitted={names(self.admitted)}"
        )


def measure_place_funnel(
    *,
    injected_chunk_texts: Sequence[str],
    lookups: Sequence[PlaceLookup],
    selectable_place_ids: Iterable[str],
    admitted_place_ids: Iterable[str],
) -> PlaceFunnel:
    """统计本轮分块提名了多少地点，以及每个地点走到了哪一步。

    除 ``injected_chunk_texts`` 外都是对 Run 实际行为的观察，因此第 2-5 步
    是精确的；只有分母是启发式的。

    唯一的判断是哪些查询由这些分块触发，按 worker 输入的查询字符串判断一次；
    之后整条链按 ``place_id`` 跟踪。
    """

    mentions = tuple(
        dict.fromkeys(
            mention.text
            for text in injected_chunk_texts
            for mention in propose_place_mentions(text)
        )
    )
    nominated = [
        lookup
        for lookup in lookups
        if any(query_carries_mention(lookup.query, mention) for mention in mentions)
    ]

    resolved: dict[str, ProviderIdentity] = {}
    for lookup in nominated:
        for identity in lookup.identities:
            resolved.setdefault(identity.place_id, identity)

    selectable = set(selectable_place_ids)
    eligible = {
        place_id: identity
        for place_id, identity in resolved.items()
        if place_id in selectable
    }
    admitted = set(admitted_place_ids)

    return PlaceFunnel(
        injected_chunks=len(injected_chunk_texts),
        mentions=mentions,
        queried=tuple(dict.fromkeys(lookup.query for lookup in nominated)),
        resolved=tuple(resolved.values()),
        eligible=tuple(eligible.values()),
        admitted=tuple(
            identity for place_id, identity in eligible.items() if place_id in admitted
        ),
    )


def chunk_texts_by_collection(
    injected_rag_sources: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[str, ...]]:
    """本轮写入 prompt 的完整分块正文，按集合分开。

    ``rag_chunk_source_records`` 已把完整分块存在 ``snapshot.content``，契约是
    「完整 RAG chunk，禁止裁剪成模型摘要」，因此这里直接读取，不再保存第二份。

    按集合分开是必要的：检索同时覆盖可选的本地出厂语料与用户上传的资料库。
    合并计数只能回答「知识库有没有贡献」，不能回答「用户上传的资料有没有被
    读到」；后者是用户可以看见、修改并判断对错的部分。

    到这里 ``snapshot.collection`` 已经是逻辑名；物理的按 owner 划分的地址在
    检索边界转换，不会进入 source record。
    """

    grouped: dict[str, list[str]] = {}
    for record in injected_rag_sources.values():
        snapshot = record.get("snapshot") if isinstance(record, Mapping) else None
        if not isinstance(snapshot, Mapping):
            continue
        content = snapshot.get("content")
        if not (isinstance(content, str) and content.strip()):
            continue
        collection = str(snapshot.get("collection") or "unknown")
        grouped.setdefault(collection, []).append(content)
    return {collection: tuple(texts) for collection, texts in grouped.items()}


__all__ = [
    "CONCRETE_PLACE_SUFFIXES",
    "PlaceFunnel",
    "PlaceLookup",
    "PlaceMention",
    "ProviderIdentity",
    "chunk_texts_by_collection",
    "measure_place_funnel",
    "mention_matches_name",
    "propose_place_mentions",
    "query_carries_mention",
]
