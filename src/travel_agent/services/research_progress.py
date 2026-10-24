"""Traveller-facing research summaries. Model packets never belong on this channel."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit


def public_text(value: Any, limit: int = 300) -> str:
    """Fail closed for structured/partial payloads, including prose-prefixed JSON."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if re.search(r'\{\s*(?:["}\[]|$)|```|<think|"[\w_]+"\s*:|contract_version|research_packet_id', text):
        return ""
    if text.startswith(('[', '{')):
        return ""
    return text[:limit]


def result_preview(value: Any, depth: int = 0) -> list[dict[str, str]]:
    """Bounded allowlist of place/page/route facts; never serialize arbitrary data."""
    if depth > 10:
        return []
    if isinstance(value, str):
        try:
            return result_preview(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return []
    if isinstance(value, list):
        rows: list[dict[str, str]] = []
        for item in value[:12]:
            for row in result_preview(item, depth + 1):
                if row not in rows:
                    rows.append(row)
        return rows[:6]
    if not isinstance(value, dict):
        return []
    if 'sanitized_result' in value:
        return result_preview(value['sanitized_result'], depth + 1)
    title = public_text(value.get('name') or value.get('title'), 120)
    if not title:
        origin, destination = value.get('from_endpoint'), value.get('to_endpoint')
        if isinstance(origin, dict) and isinstance(destination, dict):
            a, b = public_text(origin.get('name'), 60), public_text(destination.get('name'), 60)
            if a and b:
                title = f'{a} → {b}'
    if title:
        row = {'title': title}
        detail = public_text(value.get('detail') or value.get('address') or value.get('description') or value.get('snippet'), 240)
        minutes = value.get('duration_minutes')
        if not detail and isinstance(minutes, (int, float)) and minutes > 0:
            detail = f'约 {minutes:g} 分钟'
        if detail and detail != title:
            row['detail'] = detail
        url = value.get('url')
        if isinstance(url, str):
            try:
                parsed = urlsplit(url)
                if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password:
                    row['url'] = url[:1000]
            except ValueError:
                pass
        return [row]
    rows = []
    for key in ('results', 'places', 'pois', 'web', 'routes', 'data', 'content', 'text'):
        if key in value:
            rows.extend(result_preview(value[key], depth + 1))
    return rows[:6]


def worker_result(node: str, update: dict[str, Any]) -> tuple[str, str, list[dict[str, str]]]:
    """Project typed worker results, without trusting the worker's message text."""
    statuses = update.get('agent_status', {})
    if isinstance(statuses, dict) and 'failed' in statuses.values():
        return 'failed', '本轮调研未完成，暂未形成可用结果', []
    packets = update.get('research_packets', {})
    candidates: list[Any] = []
    if isinstance(packets, dict):
        for packet in packets.values():
            if hasattr(packet, 'model_dump'):
                packet = packet.model_dump(mode='json')
            if not isinstance(packet, dict) or packet.get('worker_kind') != node:
                continue
            rows = packet.get('candidates')
            if isinstance(rows, list):
                candidates.extend(rows)
    if isinstance(packets, dict) and packets:
        noun = {'destination_researcher': '地点', 'accommodation_researcher': '住宿', 'transport_researcher': '交通'}.get(node, '调研')
        content = f'已整理 {len(candidates)} 个{noun}候选' if candidates else f'本轮暂未找到可用的{noun}候选'
        return 'completed', content, result_preview(candidates)
    return 'completed', '本轮资料整理已结束', []
