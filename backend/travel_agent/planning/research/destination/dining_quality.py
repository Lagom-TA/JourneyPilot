"""Planning research destination dining quality."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.nominatim import lookup_typed_addresses_bilingual

logger = logging.getLogger(__name__)


_SEARCH_RESULT_TITLE = re.compile(r"^\s*\d{1,2}\.\s+(.+?)\s*$")


_INLINE_SEARCH_RESULT = re.compile(
    r"(?:^|\s)\d{1,2}\.\s+(.{2,180}?)(?=\s+(?:链接|link)\s*:)",
    re.IGNORECASE,
)


# Some scripts compact to empty; callers must discard them before substring checks.
_QUALITY_COMPACT = re.compile(r"[^0-9a-z぀-ヿ㐀-鿿]")


_QUALITY_LOCALITY_TOKEN = re.compile(
    r"[぀-ヿ㐀-鿿]{2,}|[^\W\d_]{5,}",
    re.UNICODE,
)


_QUALITY_LOCALITY_SUB_CITY_KEYS = (
    "road",
    "pedestrian",
    "neighbourhood",
    "quarter",
    "hamlet",
    "suburb",
    "borough",
    "city_district",
)


_QUALITY_LOCALITY_BROAD_KEYS = (
    "city",
    "town",
    "village",
    "municipality",
    "county",
    "state",
    "province",
    "region",
    "country",
)


def _web_search_entries(value: Any) -> List[tuple[str, str]]:
    """Extract result titles/snippets from structured or MCP text search output."""
    entries: List[tuple[str, str]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            title = item.get("title")
            if isinstance(title, str):
                snippet = item.get("snippet") or item.get("body") or ""
                entries.append((title, snippet if isinstance(snippet, str) else ""))
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested)
            return
        if not isinstance(item, str):
            return
        lines = item.splitlines()
        for index, line in enumerate(lines):
            match = _SEARCH_RESULT_TITLE.match(line)
            if match is None:
                continue
            snippet = ""
            for following in lines[index + 1 : index + 4]:
                stripped = following.strip()
                if stripped.startswith("摘要:"):
                    snippet = stripped.removeprefix("摘要:").strip()
                    break
            entries.append((match.group(1), snippet))
        for match in _INLINE_SEARCH_RESULT.finditer(item):
            entries.append((match.group(1), ""))

    visit(value)
    return list(dict.fromkeys(entries))


def _compact_quality_text(value: Any) -> str:
    """Strip everything the two-sided name comparison must not depend on."""
    return _QUALITY_COMPACT.sub("", str(value).casefold())


def dining_quality_locality_tokens(
    typed_addresses: List[Dict[str, Any]],
    entity_names: List[str] | None = None,
) -> List[str]:
    """Pick branch-distinguishing locality tokens out of typed provider addresses."""
    compact_names = {
        compact
        for name in (entity_names or [])
        if (compact := _compact_quality_text(name))
    }
    broad: set[str] = set()
    for address in typed_addresses:
        if not isinstance(address, dict):
            continue
        for key in _QUALITY_LOCALITY_BROAD_KEYS:
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                broad.update(
                    token.casefold() for token in _QUALITY_LOCALITY_TOKEN.findall(value)
                )
    tokens: List[str] = []
    for address in typed_addresses:
        if not isinstance(address, dict):
            continue
        for key in _QUALITY_LOCALITY_SUB_CITY_KEYS:
            value = address.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            if _compact_quality_text(value) in compact_names:
                continue
            for raw_token in _QUALITY_LOCALITY_TOKEN.findall(value):
                token = raw_token.casefold()
                if not _compact_quality_text(token):
                    continue
                if token in broad or token in tokens:
                    continue
                tokens.append(token)

                without_admin_suffix = re.sub(
                    r"(?:都|道|府|県|市|区|町|村)$",
                    "",
                    token,
                )
                if (
                    len(without_admin_suffix) >= 2
                    and without_admin_suffix not in broad
                    and without_admin_suffix not in tokens
                ):
                    tokens.append(without_admin_suffix)
    return tokens[:8]


async def resolve_dining_locality_tokens(
    places: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Map each candidate place_id to its locality tokens, or to nothing."""
    place_ids = [
        place_id
        for place in places
        if isinstance(place, dict) and (place_id := str(place.get("place_id") or ""))
    ]
    if not place_ids:
        return {}
    try:
        typed_addresses = await lookup_typed_addresses_bilingual(place_ids)
    except NominatimPlaceSearchError as exc:
        logger.warning(
            "[destination_researcher] dining locality lookup unavailable for %d place(s): %s",
            len(place_ids),
            exc,
        )
        return {}
    tokens: Dict[str, List[str]] = {}
    for place in places:
        place_id = str(place.get("place_id") or "")
        if not place_id:
            continue
        names = [place.get("name"), *(place.get("aliases") or [])]
        tokens[place_id] = dining_quality_locality_tokens(
            typed_addresses.get(place_id) or [],
            [str(name) for name in names if isinstance(name, str)],
        )
    return tokens


def dining_quality_source_matches_place(
    place: Dict[str, Any],
    quality_result: Any,
    *,
    locality_tokens: List[str],
) -> bool:
    """Require one external result to match both entity identity and branch locality."""
    names = [place.get("name"), *(place.get("aliases") or [])]
    compact_names = {
        compact
        for name in names
        if isinstance(name, str)
        and name.strip()
        and (compact := _compact_quality_text(name))
    }
    if not compact_names or not locality_tokens:
        return False
    for title, snippet in _web_search_entries(quality_result):
        entry = f"{title} {snippet}".casefold()
        compact_entry = _compact_quality_text(entry)
        if not any(name in compact_entry for name in compact_names):
            continue
        if not any(locality in entry for locality in locality_tokens):
            continue
        if "permanently closed" in entry or title.strip().casefold().startswith(
            "[closed]"
        ):
            continue
        return True
    return False
