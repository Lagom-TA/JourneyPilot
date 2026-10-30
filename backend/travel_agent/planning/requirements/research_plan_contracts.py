"""研究计划草稿与候选引用的结构契约。

旧 checkpoint 可能包含同次归一化模型的文本计划；它们的格式校验并不能证明
来源或执行授权。新计划的候选 ID 须由已澄清的服务端合同和执行边界单独核验。
历史自由正文仅保留反序列化兼容，不参与计划或查询投影。
"""

from __future__ import annotations

from pydantic import Field
from pydantic import model_validator
from pydantic import field_validator
from pydantic import ValidationInfo
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.schema import StrictModel
from typing import Annotated
from typing import List
from typing import Optional
import re
import unicodedata


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalized_text(value: str) -> str:
    if _CONTROL_CHARS.search(value):
        raise ValueError("research plan text contains control characters")
    return " ".join(value.split())


def _approved_candidate_text(value: str) -> str:
    if not value or value != value.strip() or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise ValueError("approved candidate label is invalid")
    return value


class ResearchDomainPlanDraft(StrictModel):
    domain: ResearchDomain
    focus_candidate_ids: List[str] = Field(default_factory=list, max_length=6)
    search_candidate_ids: List[str] = Field(default_factory=list, max_length=3)
    # 该领域要研究的关注点：只能从本次合同事实中逐字选取，见 validation 模块。
    focus_atoms: List[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=6
    )
    search_terms: List[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=3
    )
    # 历史字段：旧 checkpoint 里的自由正文。保留以便反序列化，但**不参与**
    # 确认正文、检索参数或 dispatch；内容仍会被内部名称泄漏检查扫描。
    focus: Optional[str] = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def validate_candidate_references(self) -> "ResearchDomainPlanDraft":
        for ids, labels in (
            (self.focus_candidate_ids, self.focus_atoms),
            (self.search_candidate_ids, self.search_terms),
        ):
            if ids and (len(ids) != len(labels) or len(ids) != len(set(ids)) or any(not item.strip() for item in ids)):
                raise ValueError("candidate references must be unique and align with labels")
        return self

    @field_validator("focus")
    @classmethod
    def normalize_focus(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = _normalized_text(value)
        return normalized or None

    @field_validator("focus_atoms")
    @classmethod
    def validate_focus_atoms(cls, atoms: List[str], info: ValidationInfo) -> List[str]:
        normalize = _approved_candidate_text if info.data.get("focus_candidate_ids") else _normalized_text
        cleaned = [normalize(atom) for atom in atoms]
        if any(not atom for atom in cleaned):
            raise ValueError("research focus atoms must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("research focus atoms must be unique")
        return cleaned

    @field_validator("search_terms")
    @classmethod
    def validate_terms(cls, terms: List[str], info: ValidationInfo) -> List[str]:
        # 已批准候选必须逐字保留；旧计划则沿用原先的空白规范化。
        normalize = _approved_candidate_text if info.data.get("search_candidate_ids") else _normalized_text
        cleaned = [normalize(term) for term in terms]
        if any(not term for term in cleaned):
            raise ValueError("research search terms must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("research search terms must be unique")
        return cleaned


class ResearchPlanDraft(StrictModel):
    domains: List[ResearchDomainPlanDraft] = Field(min_length=1, max_length=5)
    # 历史字段，同上：仅为旧 checkpoint 兼容保留，不进入确认正文或执行。
    summary: Optional[str] = Field(default=None, max_length=500)

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = _normalized_text(value)
        return normalized or None

    @model_validator(mode="after")
    def validate_domains(self) -> "ResearchPlanDraft":
        domains = [item.domain for item in self.domains]
        if len(domains) != len(set(domains)):
            raise ValueError("research plan domains must be unique")
        return self
