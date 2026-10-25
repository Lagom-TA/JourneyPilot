"""Conversation information annotations."""

from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
import re
import logging

logger = logging.getLogger(__name__)


_TIME_SENSITIVE_RE = re.compile(
    r"(?:签证|visa|入境|出入境|immigration|许可证|permit|护照|申请表|"
    r"照片|银行流水|资产证明|在职证明|收入证明|办理材料|政策|"
    r"价格|票价|费用|汇率|班次|航班|飞行时长|飞行时间|交通时间|车程|时刻表|"
    r"营业时间|开放时间|预约|限额|有效期)",
    re.IGNORECASE,
)


_SEASONAL_REFERENCE_RE = re.compile(
    r"(?:天气|气温|温度|摄氏|°\s*[CF]|降雨|降雪|台风|雨季|旱季|花期|红叶|秋叶|银杏季|祭典|节庆)",
    re.IGNORECASE,
)


_SAFETY_REFERENCE_RE = re.compile(
    r"(?:过敏|过敏原|allergen|医疗|健康|安全|疫苗|防疫)",
    re.IGNORECASE,
)


_ANNOTATION_KINDS: Dict[str, Dict[str, str]] = {
    "time_sensitive": {
        "label": "时效信息",
        "detail": "政策、价格、班次或办理要求可能随时间和适用范围变化。",
    },
    "seasonal_reference": {
        "label": "季节参考",
        "detail": "这是季节性概况，不是具体出行日期的实时预报。",
    },
    "safety_reference": {
        "label": "安全参考",
        "detail": "涉及健康或安全，请结合个人情况与具体服务方信息核对。",
    },
}


def _annotate_information_blocks(text: str) -> tuple[str, List[Dict[str, Any]]]:
    """按 Markdown 段落添加稀疏局部状态；不判断或改写正文内容。"""
    blocks = re.split(r"(\n\s*\n)", text)
    annotations: List[Dict[str, Any]] = []
    rendered: List[str] = []
    emitted_kinds: set[str] = set()

    for block in blocks:
        if not block or re.fullmatch(r"\n\s*\n", block):
            rendered.append(block)
            continue
        if "<!--" in block:
            rendered.append(block)
            continue
        if _MACHINE_CITATION_RE.search(block):
            rendered.append(block)
            continue

        kind = ""
        if _TIME_SENSITIVE_RE.search(block):
            kind = "time_sensitive"
        elif _SEASONAL_REFERENCE_RE.search(block):
            kind = "seasonal_reference"
        elif _SAFETY_REFERENCE_RE.search(block):
            kind = "safety_reference"
        if not kind or kind in emitted_kinds:
            rendered.append(block)
            continue

        emitted_kinds.add(kind)
        annotation_id = f"annotation_{len(annotations) + 1}"
        annotation = {
            "annotation_id": annotation_id,
            "kind": kind,
            **_ANNOTATION_KINDS[kind],
        }
        annotations.append(annotation)

        lines = block.splitlines()
        target_index = next(
            (idx for idx, line in enumerate(lines) if line.strip()), None
        )
        if target_index is None:
            rendered.append(block)
            continue
        if lines[target_index].lstrip().startswith("|"):
            rendered.append(f"[[annotation:{annotation_id}]]\n\n{block}")
            continue
        lines[target_index] = f"{lines[target_index]} [[annotation:{annotation_id}]]"
        rendered.append("\n".join(lines))

    return "".join(rendered), annotations


def _best_effort_information_annotations(text: str) -> tuple[str, List[Dict[str, Any]]]:
    """标签是可失败的展示增强；任何异常都必须退化为未改动正文。"""
    try:
        return _annotate_information_blocks(text)
    except Exception:
        logger.exception(
            "OutputGuard information annotation failed; delivering plain answer"
        )
        return text, []


_MACHINE_CITATION_RE = re.compile(
    r"\[\[\s*cite\s*[:：]\s*([a-z0-9_-]+)\s*\]\]", re.IGNORECASE
)
