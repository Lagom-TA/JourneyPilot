"""历史模型计划的格式与文本范围检查。

本模块使用受控身份、分句、Intent 和约束构造词表，但其中的模型解释或历史文本
只代表当前已澄清合同内的文本。文字出现、片段匹配和禁词检查都不能证明用户当前意图或
饮食安全；此旧校验器不能充当执行授权。新候选 ID 也必须由独立的已确认合同校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import FrozenSet
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple
import re

from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.requirements.intent_contracts import IntentItem
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.research_plan_contracts import (
    ResearchDomainPlanDraft,
)
from travel_agent.planning.requirements.research_plan_contracts import ResearchPlanDraft
from travel_agent.planning.research.domains import ResearchDomain


_INTERNAL_PLAN_TOKENS = (
    "destination_researcher",
    "transport_researcher",
    "accommodation_researcher",
    "itinerary_planner",
    "search_web",
    "free_web_search",
    "global_route_search",
    "rail_12306_search",
    "nominatim_place_search",
    "maps_text_search",
    "query_",
)


# 只放领域内可安全用于检索的通用词；不在名单里的具体地点必须来自本次合同。
_SAFE_DOMAIN_TERMS = {
    ResearchDomain.VISIT: frozenset(
        {
            "景点",
            "地点",
            "体验",
            "文化",
            "建筑",
            "历史",
            "博物馆",
            "公园",
            "街区",
            "当地",
            "本地",
            "特色",
            "安静",
            "亲子",
            "无障碍",
            "季节",
            "天气",
            "艺术",
            "展览",
            "活动",
        }
    ),
    ResearchDomain.DINING: frozenset(
        {
            "餐厅",
            "餐饮",
            "美食",
            "咖啡",
            "早餐",
            "午餐",
            "晚餐",
            "当地",
            "本地",
            "特色",
            "安静",
            "亲子",
            "素食",
            "清真",
            "小吃",
            "茶馆",
        }
    ),
    ResearchDomain.LODGING: frozenset(
        {
            "住宿",
            "酒店",
            "民宿",
            "宾馆",
            "房间",
            "地铁",
            "公交",
            "安静",
            "电梯",
            "无障碍",
            "亲子",
            "早餐",
            "预算",
            "位置",
        }
    ),
    ResearchDomain.LOCAL_TRANSPORT: frozenset(
        {
            "交通",
            "地铁",
            "公交",
            "步行",
            "打车",
            "路线",
            "换乘",
            "无障碍",
            "电梯",
            "接驳",
            "车站",
        }
    ),
    ResearchDomain.LONG_DISTANCE_TRANSPORT: frozenset(
        {
            "交通",
            "高铁",
            "火车",
            "航班",
            "飞机",
            "车次",
            "往返",
            "去程",
            "返程",
            "接驳",
            "车站",
            "机场",
            "时间",
        }
    ),
}


# 这些类别描述的是「要避开什么」，因此只能产生禁止片段，不能产生检索词。
_NEGATIVE_CONSTRAINT_CATEGORIES = frozenset(
    {"food_allergy", "dietary_restriction", "health_condition", "elderly_mobility"}
)

_STAIRS_TERMS = ("台阶", "长楼梯", "楼梯", "阶梯")


# 否定/回避前缀，按长度从长到短匹配；只用于从「不吃牛肉」这类原文里取出被禁
# 对象本身，不据此放行任何内容。
_NEGATION_PREFIXES = (
    "不可以吃",
    "不能吃",
    "不要吃",
    "不许吃",
    "不允许",
    "不可以",
    "不想去",
    "不打算",
    "不计划",
    "不安排",
    "尽可能",
    "拒绝",
    "排除",
    "不要查",
    "要避开",
    "避开",
    "别去",
    "无需",
    "不去",
    "忌口",
    "禁食",
    "禁用",
    "避免",
    "不能",
    "不要",
    "别喝",
    "不喝",
    "不吃",
    "不含",
    "没有",
    "无",
    "忌",
    "禁",
    "别",
    "不",
)

_ALLERGY_SUFFIXES = ("过敏原", "不耐受", "过敏")

# 这些词本身不指向任何具体禁忌对象；把「食物」「过敏」当禁止片段会让每一条
# 餐饮检索都失败，也不增加任何安全性。
_RESTRICTION_STOPWORDS = frozenset(
    {"食物", "食品", "饮食", "过敏", "过敏原", "不耐受", "禁忌", "要求", "限制"}
)

_TOKEN_SPLIT = re.compile(r"[\s,，、;；/|·:：.。!！?？()（）\[\]【】]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

# 逐段回溯时单段的最大长度；更长的合同原文只能整段命中。
_MAX_PIECE_LENGTH = 12
_MIN_ATOM_LENGTH = 2


def normalize_public_text(value: Any) -> str:
    """压缩空白并拒绝控制字符；模型正文与检索词都走这一条规范化。"""

    text = str(value or "")
    if _CONTROL_CHARS.search(text):
        raise ValueError("research plan text contains control characters")
    return " ".join(text.split())


def _atom_key(value: Any) -> str:
    return normalize_public_text(value).casefold()


def contains_internal_plan_token(plan: ResearchPlanDraft) -> bool:
    public_text = plan_public_text(plan).casefold()
    return any(token.casefold() in public_text for token in _INTERNAL_PLAN_TOKENS)


def plan_public_text(plan: ResearchPlanDraft) -> str:
    """计划里所有会离开服务端的文本（含历史字段，泄漏检查要覆盖全部）。"""

    parts: List[str] = []
    if plan.summary:
        parts.append(plan.summary)
    for row in plan.domains:
        if row.focus:
            parts.append(row.focus)
        parts.extend(row.focus_atoms)
        parts.extend(row.search_terms)
    return " ".join(parts)


def _intent_strings(item: IntentItem) -> Iterable[str]:
    if item.source_text:
        yield item.source_text
    value = item.value.model_dump(mode="json")
    value_type = value.get("value_type")
    keys = {
        "scalar": ("value",),
        "category": ("categories",),
        "sequence": ("ordered_items",),
        "geographic": ("area",),
        "cadence": ("time_window", "required_attributes"),
        "time_window": ("window",),
        "output_requirement": ("required_field",),
        "alternative": ("distinction",),
    }.get(value_type, ())
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, str):
            yield raw
        elif isinstance(raw, list):
            yield from (str(entry) for entry in raw)


def _place_atoms(place: Any) -> Iterable[str]:
    for key in ("name", "display_name"):
        text = str(getattr(place, key, "") or "").strip()
        if text:
            yield text
    for entry in getattr(place, "admin_path", None) or []:
        text = str(entry or "").strip()
        if text:
            yield text


def _constraint_rows(constraint_pack: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for item in constraint_pack.get("constraints") or []:
        if not isinstance(item, Mapping) or item.get("status") not in (None, "active"):
            continue
        yield item


def _strip_restriction_markers(text: str) -> Set[str]:
    """从一条限制原文里取出「被禁止的对象」本身的几种写法。"""

    variants: Set[str] = {text}
    frontier = [text]
    for _ in range(3):
        next_frontier: List[str] = []
        for candidate in frontier:
            for prefix in _NEGATION_PREFIXES:
                if candidate.startswith(prefix):
                    remainder = candidate[len(prefix) :].strip()
                    if remainder and remainder not in variants:
                        variants.add(remainder)
                        next_frontier.append(remainder)
            for suffix in _ALLERGY_SUFFIXES:
                if candidate.endswith(suffix):
                    remainder = candidate[: -len(suffix)].strip()
                    if remainder and remainder not in variants:
                        variants.add(remainder)
                        next_frontier.append(remainder)
        if not next_frontier:
            break
        frontier = next_frontier
    return variants


def _restriction_fragments(text: str) -> Iterable[str]:
    base = normalize_public_text(text)
    if not base:
        return
    candidates: Set[str] = set()
    for variant in _strip_restriction_markers(base):
        candidates.add(variant)
        for piece in _TOKEN_SPLIT.split(variant):
            piece = piece.strip()
            if piece:
                candidates.add(piece)
    for candidate in candidates:
        compact = _WHITESPACE.sub("", candidate).casefold()
        if len(compact) < 2 or compact in _RESTRICTION_STOPWORDS:
            continue
        if compact.isdigit():
            continue
        yield compact


def _forbidden_fragments(
    identity: ControlledTripIdentity,
    active_items: Sequence[IntentItem],
    constraint_pack: Mapping[str, Any],
) -> FrozenSet[str]:
    """明确要避开的东西：硬排除、饮食禁忌/过敏、行动能力限制。"""

    fragments: Set[str] = set()
    for item in active_items:
        if item.kind is not IntentKind.MUST_EXCLUDE:
            continue
        for text in _intent_strings(item):
            fragments.update(_restriction_fragments(text))

    for item in _constraint_rows(constraint_pack):
        category = str(item.get("category") or "")
        if category not in _NEGATIVE_CONSTRAINT_CATEGORIES:
            continue
        fragments.update(_restriction_fragments(str(item.get("value") or "")))
        params = item.get("params")
        if isinstance(params, Mapping):
            for raw in params.get("allergens") or []:
                fragments.update(_restriction_fragments(str(raw)))
            for key in ("avoid", "avoid_list", "excluded_terms"):
                for raw in params.get(key) or []:
                    fragments.update(_restriction_fragments(str(raw)))
            if params.get("avoid_long_stairs"):
                fragments.update(term.casefold() for term in _STAIRS_TERMS)

    if identity.party.accessibility_required:
        fragments.update(term.casefold() for term in _STAIRS_TERMS)

    return frozenset(fragment for fragment in fragments if fragment)


@dataclass(frozen=True)
class ResearchPlanBinding:
    """一次合同内允许模型引用的结构化事实。"""

    focus_atoms: FrozenSet[str]
    search_atoms: FrozenSet[str]
    forbidden_fragments: Tuple[str, ...]

    def contradicts_restriction(self, text: str) -> Optional[str]:
        compact = _WHITESPACE.sub("", normalize_public_text(text).casefold())
        if not compact:
            return None
        for fragment in self.forbidden_fragments:
            if fragment and fragment in compact:
                return fragment
        return None


def build_research_plan_binding(
    *,
    identity: ControlledTripIdentity,
    active_items: Iterable[IntentItem],
    constraint_pack: Mapping[str, Any],
    clause_texts: Iterable[str] = (),
) -> ResearchPlanBinding:
    focus_atoms: Set[str] = set()
    search_atoms: Set[str] = set()

    def add_both(text: Any) -> None:
        key = _atom_key(text)
        if len(key) < _MIN_ATOM_LENGTH:
            return
        focus_atoms.add(key)
        search_atoms.add(key)

    for place in [identity.origin, *identity.destinations]:
        for text in _place_atoms(place):
            add_both(text)
    for text in [identity.style.primary, *identity.style.secondary_interests]:
        add_both(text)
    for text in clause_texts:
        add_both(text)

    active = list(active_items)
    for item in active:
        if item.kind is IntentKind.MUST_EXCLUDE:
            continue
        for text in _intent_strings(item):
            add_both(text)
    return ResearchPlanBinding(
        focus_atoms=frozenset(focus_atoms),
        search_atoms=frozenset(search_atoms),
        forbidden_fragments=tuple(
            sorted(_forbidden_fragments(identity, active, constraint_pack))
        ),
    )


def focus_atom_options(
    *,
    controlled_identity: Mapping[str, Any],
    clause_texts: Iterable[str] = (),
    limit: int = 40,
) -> List[str]:
    """给归一化提示词的关注点选项；必须是校验期允许集合的子集。"""

    options: List[str] = []

    def add(text: Any) -> None:
        raw = " ".join(str(text or "").split())
        if len(raw) < _MIN_ATOM_LENGTH or len(raw) > 120:
            return
        if raw in options:
            return
        options.append(raw)

    for place in [
        controlled_identity.get("origin") or {},
        *(controlled_identity.get("destinations") or []),
    ]:
        if not isinstance(place, Mapping):
            continue
        add(place.get("name"))
        add(place.get("display_name"))
        for entry in place.get("admin_path") or []:
            add(entry)
    style = controlled_identity.get("style") or {}
    if isinstance(style, Mapping):
        add(style.get("primary"))
        for entry in style.get("secondary_interests") or []:
            add(entry)
    for text in clause_texts:
        add(text)
    # 通用研究主题词（景点/餐饮/住宿/交通/安静/无障碍…）在所有领域都合法；
    # 它们是固定词表，不含地点、人数或日期。
    for terms in _SAFE_DOMAIN_TERMS.values():
        for term in sorted(terms):
            add(term)
    return options[:limit]


def _reaches_end(value: str, atoms: FrozenSet[str], safe: FrozenSet[str]) -> bool:
    if len(value) < _MIN_ATOM_LENGTH:
        return False
    if value in atoms or value in safe:
        return True
    length = len(value)
    reachable = [False] * (length + 1)
    reachable[0] = True
    for start in range(length):
        if not reachable[start]:
            continue
        max_end = min(length, start + _MAX_PIECE_LENGTH)
        for end in range(start + _MIN_ATOM_LENGTH, max_end + 1):
            piece = value[start:end]
            if piece in atoms or piece in safe:
                reachable[end] = True
    return reachable[length]


def _grounded(
    term: str, domain: ResearchDomain, binding: ResearchPlanBinding
) -> bool:
    normalized = _atom_key(term)
    if not normalized:
        return False
    safe = _SAFE_DOMAIN_TERMS[domain]
    if _reaches_end(normalized, binding.search_atoms, safe):
        return True
    tokens = [token for token in _TOKEN_SPLIT.split(normalized) if token]
    return bool(tokens) and all(
        _reaches_end(token, binding.search_atoms, safe) for token in tokens
    )


def grounded_research_atoms(
    *,
    identity: ControlledTripIdentity,
    active_items: Iterable[IntentItem],
    constraint_pack: Mapping[str, Any],
    clause_texts: Iterable[str],
    domain: ResearchDomain,
    limit: int = 12,
) -> Tuple[str, ...]:
    binding = build_research_plan_binding(
        identity=identity,
        active_items=active_items,
        constraint_pack=constraint_pack,
        clause_texts=clause_texts,
    )
    safe = _SAFE_DOMAIN_TERMS[domain]
    atoms = set(binding.focus_atoms) | set(binding.search_atoms) | set(safe)
    rows = []
    for atom in atoms:
        if not atom or len(atom) > 120 or binding.contradicts_restriction(atom):
            continue
        if atom not in safe and not _grounded(atom, domain, binding):
            continue
        rows.append(atom)
    return tuple(sorted(rows, key=lambda atom: (atom in safe, _atom_key(atom)))[:limit])


def validate_research_plan_for_contract(
    plan: Optional[ResearchPlanDraft],
    *,
    identity: ControlledTripIdentity,
    active_items: Iterable[IntentItem],
    constraint_pack: Mapping[str, Any],
    required_domains: Set[ResearchDomain],
    clause_texts: Iterable[str] = (),
    candidate_selection=None,
    confirmation_digest: str | None = None,
) -> tuple[Optional[Mapping[ResearchDomain, ResearchDomainPlanDraft]], str]:
    """返回可执行领域映射；任何一项无法证明在合同范围内就拒绝整份计划。"""

    if plan is None:
        return None, "research_plan_missing"
    rows = list(plan.domains)
    if any(row.focus_candidate_ids or row.search_candidate_ids for row in rows):
        if (
            candidate_selection is None
            or not confirmation_digest
            or candidate_selection.confirmation_digest != confirmation_digest
            or set(candidate_selection.required_domains) != required_domains
        ):
            return None, "research_plan_unverified_candidate_references"
        candidates = {item.candidate_id: item for item in candidate_selection.candidates}
        for row in rows:
            for ids, labels in (
                (row.focus_candidate_ids, row.focus_atoms),
                (row.search_candidate_ids, row.search_terms),
            ):
                if not ids or len(ids) != len(labels):
                    return None, "research_plan_unverified_candidate_references"
                for candidate_id, label in zip(ids, labels):
                    candidate = candidates.get(candidate_id)
                    if (
                        candidate is None
                        or candidate.domain is not row.domain
                        or candidate.label != label
                    ):
                        return None, "research_plan_unverified_candidate_references"
    by_domain = {row.domain: row for row in rows}
    if len(by_domain) != len(rows) or set(by_domain) != required_domains:
        return None, "research_plan_domain_coverage_mismatch"
    if contains_internal_plan_token(plan):
        return None, "research_plan_leaks_internal_names"

    active = list(active_items)
    binding = build_research_plan_binding(
        identity=identity,
        active_items=active,
        constraint_pack=constraint_pack,
        clause_texts=clause_texts,
    )

    for row in rows:
        safe = _SAFE_DOMAIN_TERMS[row.domain]
        for atom in row.focus_atoms:
            key = _atom_key(atom)
            if key not in binding.focus_atoms and key not in safe:
                return None, "research_plan_has_ungrounded_focus_atom"
            fragment = binding.contradicts_restriction(atom)
            if fragment:
                return None, "research_plan_contradicts_restriction"
        for term in row.search_terms:
            if not _grounded(term, row.domain, binding):
                return None, "research_plan_has_ungrounded_search_term"
            if binding.contradicts_restriction(term):
                return None, "research_plan_contradicts_restriction"

    # 硬要求必须在确定性 Brief 里保留；这里只确认模型没有把硬排除写成研究范围。
    for item in active:
        if item.strength is not IntentStrength.HARD:
            continue
        if item.kind is not IntentKind.MUST_EXCLUDE:
            continue
        label = _atom_key(item.public_summary)
        if not label:
            continue
        for row in rows:
            haystack = _atom_key(" ".join([*row.focus_atoms, *row.search_terms]))
            if label in haystack:
                return None, "research_plan_contradicts_hard_exclusion"
    return by_domain, ""
