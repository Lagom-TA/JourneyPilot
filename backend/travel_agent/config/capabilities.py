"""Config capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import List
import importlib.util


@dataclass(frozen=True)
class CapabilityGap:
    """一个被配置要求、但依赖不齐的能力。"""

    requested_by: str

    missing_modules: List[str]

    install_command: str

    consequence: str

    def message(self) -> str:
        return (
            f"{self.requested_by} 需要 {', '.join(self.missing_modules)}，但它们没有安装。"
            f"{self.consequence} 安装：{self.install_command}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested_by": self.requested_by,
            "missing_modules": self.missing_modules,
            "install_command": self.install_command,
            "consequence": self.consequence,
            "message": self.message(),
        }


def _missing(*modules: str) -> List[str]:
    absent: List[str] = []
    for name in modules:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            absent.append(name)
    return absent


def capability_gaps(settings: Any) -> List[CapabilityGap]:
    """按当前配置检查增强依赖，返回缺口（空 = 配置与安装一致）。"""

    gaps: List[CapabilityGap] = []
    if not settings.embedding.enabled:
        return gaps

    if settings.embedding.provider == "qwen3":
        missing = _missing("onnxruntime", "tokenizers", "huggingface_hub", "numpy")
        if missing:
            gaps.append(
                CapabilityGap(
                    requested_by="embedding.provider=qwen3",
                    missing_modules=missing,
                    install_command="uv sync --project backend --group local-embedding",
                    consequence=(
                        "本地 Embedding 推理不可用，知识库入库与检索会在第一次调用时失败。"
                        "或者把 embedding.provider 改成 openai（远程）。"
                    ),
                )
            )

    if settings.rerank.enabled and settings.rerank.provider == "cross_encoder":
        missing = _missing("sentence_transformers")
        if missing:
            gaps.append(
                CapabilityGap(
                    requested_by="rerank.provider=cross_encoder",
                    missing_modules=missing,
                    install_command="uv sync --project backend --group cross-encoder",
                    consequence=(
                        "二阶段精排不可用，检索会在精排那一步失败。"
                        "或者把 rerank.provider 改成 llm（默认，复用已配置的模型）。"
                    ),
                )
            )

    return gaps


def capability_report(settings: Any) -> Dict[str, Any]:
    """readiness 里 `optional_capabilities` 那一项。

    ``ready`` 为 false 时**拦门禁**：这不是「质量下降」而是「这个配置在这台机器上跑不
    起来」—— 与空语料那一类不同，它会在第一次真正调用时抛异常。
    """

    gaps = capability_gaps(settings)
    return {
        "ready": not gaps,
        "gaps": [gap.to_dict() for gap in gaps],
        "message": "ok" if not gaps else "；".join(gap.message() for gap in gaps),
    }
