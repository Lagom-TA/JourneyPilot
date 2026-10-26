"""统计已索引语料中有多少文本块能提名一个可解析的具体地点。

判据：文本块中的某个候选名称经产品自身的提名与解析链路，能在 Provider 记录中找到同名、
且位于目的地 ``SCOPE_KM`` 范围内的具体地点。stop（非交通基础设施）与基础设施分开统计，
结果按集合和 manifest 批次分组；Provider 答案写入 ``--out``，可用 ``--report-only``
从已有结果重新出报告。

    python backend/scripts/corpus_place_census.py --limit 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from travel_agent.config.loader import get_settings  # noqa: E402
from travel_agent.paths import REPO_ROOT
from travel_agent.storage.database import get_session_factory  # noqa: E402
from travel_agent.knowledge.place_mentions import (  # noqa: E402
    mention_matches_name,
    propose_place_mentions,
)
from travel_agent.knowledge.collections import FACTORY_KNOWLEDGE_COLLECTIONS  # noqa: E402
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.normalization import is_concrete_dining_place, is_concrete_visit_place, normalize_nominatim_place
from travel_agent.integrations.places.nominatim import search_nominatim_raw

# 本地出厂语料，集合名取自唯一定义处。本次普查只统计本地出厂语料，不包含
# ``grounding_corpus`` 在检索时按用户加入的上传库：那部分随机器与用户变化，
# 计入后结果不可复现。
COLLECTIONS = FACTORY_KNOWLEDGE_COLLECTIONS

# OSM 中表示交通基础设施的顶层键。
INFRASTRUCTURE_KEYS = ("highway", "railway", "aeroway", "waterway")

SEED = 20260801
COURTESY_INTERVAL_SECONDS = 2.5
BACKOFF_SECONDS = (30.0, 120.0, 300.0)

# 语料涉及的目的地，以及 Provider 查询限定的国家。国家不参与判据，只用于缩小
# ``/search`` 范围；它必须与中心点一起传递，因为跨两国的语料不能用同一个固定过滤器评分。
DEFAULT_CENTRES = ("杭州市:cn", "苏州市:cn", "绍兴市:cn", "東京都:jp")


def _normalize(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def place_bears_name(mention: str, place: dict) -> bool:
    """Provider 记录的名称或别名必须与语料中的提及一致。"""
    for candidate in (place.get("name"), *(place.get("aliases") or ())):
        if mention_matches_name(mention, str(candidate or "")):
            return True
    return False


async def _search(query: str, country_code: str):
    last = ""
    for delay in (*BACKOFF_SECONDS, None):
        try:
            return await search_nominatim_raw(query, country_code=country_code, limit=5)
        except NominatimPlaceSearchError as exc:
            last = str(exc)
            if delay is None:
                break
            print(f"    provider refused ({query!r}); waiting {delay:.0f}s", flush=True)
            await asyncio.sleep(delay)
    raise NominatimPlaceSearchError(last, code="provider_unavailable")


def parse_centre(spec: str) -> tuple[str, str]:
    """``"東京都:jp"`` -> ``("東京都", "jp")``；只写名称时默认国家为中国。"""
    name, _, country = spec.partition(":")
    return name.strip(), (country.strip() or "cn").casefold()


async def load_centres(specs: tuple[str, ...]) -> dict[str, tuple[float, float, str]]:
    """目的地中心点，由 Provider 解析得到，不手工维护坐标。

    手写坐标表会成为第二份来源，并可能在无人察觉时过期。
    """
    centres: dict[str, tuple[float, float, str]] = {}
    for spec in specs:
        name, country = parse_centre(spec)
        observation = await _search(name, country)
        place = normalize_nominatim_place(observation.items[0])
        centres[name] = (place["latitude"], place["longitude"], country)
        print(
            f"centre {name} [{country}] -> {place['name']} "
            f"@ {place['latitude']},{place['longitude']}",
            flush=True,
        )
    return centres


async def resolve(mention: str, country: str, centres: dict, scope_km: float) -> dict:
    """一次提及在一个国家的 Provider 索引中的解析结果。

    范围判定只使用同一国家的中心点：外国的中心点不可能落在 ``scope_km`` 内，
    限定国家后报告的距离才有意义。
    """
    try:
        observation = await _search(mention, country)
    except NominatimPlaceSearchError as exc:
        return {"error": str(exc)}
    named = [
        place
        for item in observation.items
        if (place := normalize_nominatim_place(item)) is not None
        and place["provider_country_code"] == country
        and place_bears_name(mention, place)
    ]
    local_centres = {
        name: (lat, lon) for name, (lat, lon, cc) in centres.items() if cc == country
    }

    def project(places: list) -> list:
        rows = []
        for place in places:
            distance, city = min(
                (
                    (haversine_km(place["latitude"], place["longitude"], lat, lon), name)
                    for name, (lat, lon) in local_centres.items()
                ),
                default=(float("inf"), ""),
            )
            rows.append(
                {
                    "place_id": place["place_id"],
                    "name": place["name"],
                    "type": place["provider_place_type"],
                    "km": round(distance, 1),
                    "city": city,
                    "in_scope": distance <= scope_km,
                    "infrastructure": place["provider_place_type"].split(";")[0]
                    in INFRASTRUCTURE_KEYS,
                }
            )
        return rows

    return {
        "returned": len(observation.items),
        "named": len(named),
        "visit": project([p for p in named if is_concrete_visit_place(p)]),
        "dining": project([p for p in named if is_concrete_dining_place(p)]),
    }


def in_scope_hits(entry: dict) -> list:
    if not entry or "error" in entry:
        return []
    hits = list(entry.get("visit") or ()) + list(entry.get("dining") or ())
    return [hit for hit in hits if hit["in_scope"]]


def report(rows: list, resolutions: dict, total: int) -> None:
    n = len(rows)
    if not n:
        return
    stop = sum(1 for row in rows if row["hit_stop"])
    scoped = sum(1 for row in rows if row["hit_stop"] or row["hit_infrastructure"])
    anywhere = sum(1 for row in rows if row["hit_anywhere"])
    capped = sum(1 for row in rows if row["capped"])
    errors = sum(1 for entry in resolutions.values() if "error" in entry)
    margin = 1.96 * math.sqrt(max(stop / n * (1 - stop / n), 1e-9) / n)
    print(
        f"\n=== {n}/{total} chunks | lookups={len(resolutions)} errors={errors} capped={capped}\n"
        f"    names an in-scope STOP:          {stop}/{n} = {stop / n:.1%} (95% CI +/-{margin:.1%})\n"
        f"    names in-scope stop or infra:    {scoped}/{n} = {scoped / n:.1%}\n"
        f"    names any concrete place at all: {anywhere}/{n} = {anywhere / n:.1%}",
        flush=True,
    )
    # 按集合分组：两部分语料的分块方式不同（500 字符窗口与上下文字句切片），
    # 只看总体数字会把语料构成的变化误读成密度提升。
    _breakdown(rows, "collection", lambda row: row["collection"])
    # 按 manifest 批次分组，也就是按目的地分组。判据对日本一半依赖返回日文名称的
    # Provider，存在结构性盲区；总体数字会把可测的一半与不可测的一半平均掉。
    batches = load_batches()
    if batches:
        _breakdown(rows, "batch", lambda row: batches.get(row["source"], "(未登记批次)"))


def _breakdown(rows: list, label: str, key) -> None:
    buckets: dict[str, list] = {}
    for row in rows:
        buckets.setdefault(key(row), []).append(row)
    print(f"    -- 按{label}", flush=True)
    for name, group in sorted(buckets.items()):
        hits = sum(1 for row in group if row["hit_stop"])
        print(
            f"      {name:<26} {hits:>4}/{len(group):<4} = {hits / len(group):>6.1%}",
            flush=True,
        )


_REPO_ROOT = str(REPO_ROOT)


def load_batches(root: str = "") -> dict[str, str]:
    """``doc_source`` -> 登记它的 manifest 批次。

    映射直接来自 manifest，而不是在这里另写一张表，因此批次不会与它实际索引的标题脱节。
    """
    # 以仓库根目录为基准而不是调用者的 cwd：脚本可能在任意目录运行，
    # 批次分组不能因为路径失效而显示成「没有批次」。
    root = root or os.path.join(_REPO_ROOT, "data", "corpus")
    prefixes = {"wikipedia": "wiki", "wikivoyage": "voyage"}
    batches: dict[str, str] = {}
    if not os.path.isdir(root):
        return batches
    for name in sorted(os.listdir(root)):
        if not name.endswith(".txt"):
            continue
        project = next((p for p in prefixes if name.startswith(p)), None)
        if project is None:
            continue
        label = name[:-4]
        with open(os.path.join(root, name), encoding="utf-8") as handle:
            for line in handle:
                title = line.strip()
                if title and not title.startswith("#"):
                    batches[f"{prefixes[project]}-zh-{title}"] = label
    return batches


async def load_chunks() -> list[dict]:
    from sqlalchemy import text

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "select id, collection, source, content from knowledge_chunks "
                "where collection = any(:collections) order by id"
            ),
            {"collections": list(COLLECTIONS)},
        )
        return [
            {"id": str(row[0]), "collection": row[1], "source": row[2], "content": row[3]}
            for row in result.fetchall()
        ]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="tmp/corpus-place-census.json")
    parser.add_argument("--cap", type=int, default=12, help="max lookups per chunk")
    parser.add_argument("--scope-km", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=0, help="stop after N chunks (0 = all)")
    parser.add_argument(
        "--centre",
        action="append",
        default=None,
        help="destination the corpus is about, as NAME[:COUNTRY]; repeatable",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="re-report a finished census from --out without asking the Provider anything",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=COURTESY_INTERVAL_SECONDS,
        help=(
            "seconds between Provider calls. Pacing only — it changes how long the "
            "census takes, never what it reports."
        ),
    )
    args = parser.parse_args()

    if args.report_only:
        state = json.load(open(args.out, encoding="utf-8"))
        rows = state.get("chunks", [])
        # 使用本次普查运行时的语料总量，而不是当前表里的数量：
        # 语料增长后重出旧报告会得到一个当时并不适用的分母。
        report(rows, state.get("resolutions", {}), state.get("corpus_total", len(rows)))
        return

    get_settings().geocoding.min_interval_seconds = args.interval
    centres = await load_centres(tuple(args.centre or DEFAULT_CENTRES))
    # 固定顺序，使普查结果与 --centre 的输入顺序无关。
    countries = tuple(dict.fromkeys(cc for _, _, cc in centres.values()))

    chunks = await load_chunks()
    order = list(range(len(chunks)))
    random.Random(SEED).shuffle(order)

    state = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    resolutions: dict = state.get("resolutions", {})
    rows: list = state.get("chunks", [])
    visited = {row["id"] for row in rows}
    print(f"chunks={len(chunks)} resuming: visited={len(rows)} lookups={len(resolutions)}", flush=True)

    def flush() -> None:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "resolutions": resolutions,
                    "chunks": rows,
                    "corpus_total": len(chunks),
                },
                handle,
                ensure_ascii=False,
            )

    for index in order:
        chunk = chunks[index]
        if chunk["id"] in visited:
            continue
        if args.limit and len(rows) >= args.limit:
            break
        proposals = [m.text for m in propose_place_mentions(chunk["content"])]
        hit_stop = hit_infrastructure = None
        hit_anywhere = False
        for mention in proposals[: args.cap]:
            # 国家按固定顺序遍历，在第一个国家命中 stop 就跳过其余国家。这一短路
            # 不改变三个汇总数字：它只在 ``hit_stop`` 已置位后触发，而 stop 命中
            # 已经蕴含两个更弱的结论。
            for country in countries:
                key = f"{country}|{mention}"
                if key not in resolutions or "error" in resolutions[key]:
                    resolutions[key] = await resolve(
                        mention, country, centres, args.scope_km
                    )
                entry = resolutions[key]
                if not hit_anywhere and (entry.get("visit") or entry.get("dining")):
                    hit_anywhere = True
                scoped = in_scope_hits(entry)
                stops = [hit for hit in scoped if not hit["infrastructure"]]
                if stops:
                    hit_stop = mention
                    break
                if scoped and hit_infrastructure is None:
                    hit_infrastructure = mention
            if hit_stop:
                # 只有 stop 命中才结束该文本块：在基础设施命中处停止，会把
                # 「博物馆排在更后面」的文本块记成「只提到道路」。
                break
        rows.append(
            {
                "id": chunk["id"],
                "collection": chunk["collection"],
                "source": chunk["source"],
                "proposed": len(proposals),
                "capped": len(proposals) > args.cap,
                "hit_stop": hit_stop,
                "hit_infrastructure": hit_infrastructure,
                "hit_anywhere": hit_anywhere or bool(hit_stop or hit_infrastructure),
            }
        )
        if len(rows) % 10 == 0:
            flush()
            report(rows, resolutions, len(chunks))

    flush()
    report(rows, resolutions, len(chunks))


if __name__ == "__main__":
    asyncio.run(main())
