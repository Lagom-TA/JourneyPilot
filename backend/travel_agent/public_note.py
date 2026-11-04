"""面向用户的公开工作说明。

这里只处理模型在工具轮次中**主动写出的可见正文**（``content``）。供应商的
``reasoning_content`` / ``reasoning_details`` / ``assistant_replay`` 永远不会进入
本模块；它们由 ``llm.chat_client`` 保留给协议重放。

公开说明不是旅行事实，也不是内部思维链。它必须在服务端经过一次保守的整句
校验，再以完整句子为单位下发：

- 句子必须在终止标点处切开，绝不能把半个 token 发给客户端；因此密钥不会被
  跨片段拼接泄露。
- 任一待发句子命中 JSON/代码围栏、内部提示字段、工具载荷、凭据或 PII 形态时，
  本轮整条说明失败关闭（不再发后续句子），已经通过校验的完整句子不回滚。
- 自由文本无法被正则证明“绝对不含秘密”。这里的边界是可枚举的形态检查加上
  “整句校验 + 终止标点切分”，而不是对任意自然语言的安全证明；无法确认时丢弃，
  不发出可疑前缀。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

MAX_NOTE_SENTENCE_CHARS = 160
MAX_NOTE_SENTENCES_PER_ROUND = 2
MAX_NOTE_CHARS_PER_RUN = 600

WORK_EXPLANATION_KIND = "work_explanation"
WORK_EXPLANATION_SOURCE = "model_public"

# 只在真正的句末标点处切分；换行不是安全边界——密钥可能被拆在两行里。
_SENTENCE_END = re.compile(r"[。！？!?；;]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

# 逐句整段匹配：任一命中即视为不可公开。
_UNSAFE_PATTERNS = (
    # 代码围栏、显式推理标签或供应商 replay 字段。
    re.compile(r"```|<think|</think|reasoning[_\s-]?(?:content|details)|assistant_replay", re.I),
    # JSON、数组、代码围栏与内部 XML 契约标签。
    re.compile(
        r"[{}\[\]`]|<\s*/?\s*(?:role|rules|json_schema|research_runtime|packet|system|instruction)",
        re.I,
    ),
    # JSON 键值形态，例如 "query": 或 "contract_version":
    re.compile(r'"[A-Za-z0-9_\-]{2,}"\s*:'),
    # 内部字段名、租户/PII 字段名与系统提示措辞。
    re.compile(
        r"(?:contract_version|research_packet_id|packet_metadata|fact_data_revision|worker_kind"
        r"|tool_call_id|assistant_replay|system prompt|internal prompt|系统提示|内部提示|提示词)",
        re.I,
    ),
    # 工具原始载荷 / 调用协议字段。
    re.compile(r"(?:tool_calls?|function_call|arguments|call_id)\s*[:=]", re.I),
    # 凭据形态。
    re.compile(
        r"\bsk-[A-Za-z0-9_\-]{8,}|\bsk-or-v1-[A-Za-z0-9]+|\bBearer\s+\S+|\bAKIA[0-9A-Z]{16}"
        r"|\b(?:api[_-]?key|secret|password|passwd|access[_-]?token)\s*[:=]\s*\S+",
        re.I,
    ),
    # URL 内嵌凭据。
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.I),
    # 邮箱、手机号、长数字串（证件/卡号形态）。
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{15,}(?!\d)"),
    # 角色标签式提示注入残留、HTML/脚本与脚本协议。
    re.compile(r"(?:^|\n)\s*(?:system|assistant|user|developer)\s*:", re.I),
    re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>"),
    re.compile(r"javascript\s*:", re.I),
)

# 去掉所有空白后再检查一次：``sk-live-\nSECRET`` 这种跨行/跨片段拆分在
# 逐段正则里看不见，压缩空白后才恢复成完整的凭据形态。
_COMPACT_UNSAFE_PATTERNS = (
    re.compile(r"(?:^|[^A-Za-z0-9])(?:sk|rk)-[A-Za-z0-9_\-]{8,}", re.I),
    re.compile(r"Bearer[A-Za-z0-9._\-]{8,}", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{15,}(?!\d)"),
)


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _strip_wrapping(text: str) -> str:
    stripped = text.strip()
    for quote in ('"', "'", "“", "”", "「", "」"):
        if len(stripped) >= 2 and stripped.startswith(quote) and stripped.endswith(quote):
            stripped = stripped[1:-1].strip()
    return stripped


def sanitize_public_note(text: str, *, max_chars: int = MAX_NOTE_SENTENCE_CHARS) -> Optional[str]:
    """校验并规范化一条完整公开说明；不能确认安全时返回 ``None``。"""

    raw = str(text or "")
    if not raw.strip():
        return None
    if _CONTROL_CHARS.search(raw):
        return None
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(raw):
            return None
    compact = _WHITESPACE.sub("", raw)
    for pattern in _COMPACT_UNSAFE_PATTERNS:
        if pattern.search(compact):
            return None
    normalized = _strip_wrapping(_normalize(raw))
    if not normalized or len(normalized) > max_chars:
        return None
    # 至少要有可读文字；纯标点/纯数字不构成说明。
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", normalized):
        return None
    return normalized


class PublicNoteStream:
    """按完整句子增量发布一条公开说明。

    ``feed`` 在遇到终止标点时校验并返回 ``(seq, text)``；``flush`` 处理本轮最后
    一个没有终止标点的完整句子。任何一句未通过校验都会把本轮标记为 blocked，
    之后的 ``feed`` / ``flush`` 不再产生内容。
    """

    def __init__(
        self,
        *,
        max_chars: int = MAX_NOTE_CHARS_PER_RUN,
        max_sentences: int = MAX_NOTE_SENTENCES_PER_ROUND,
        sentence_chars: int = MAX_NOTE_SENTENCE_CHARS,
    ) -> None:
        self._buffer = ""
        self._max_chars = max(0, max_chars)
        self._max_sentences = max(0, max_sentences)
        self._sentence_chars = max(1, sentence_chars)
        self._emitted_chars = 0
        self._emitted_sentences = 0
        self._seq = 0
        self._blocked = False
        self._closed = False

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def emitted_chars(self) -> int:
        return self._emitted_chars

    def feed(self, delta: str) -> List[Tuple[int, str]]:
        if self._blocked or self._closed or not delta:
            return []
        self._buffer += delta
        # 没有终止标点却无限增长：无法按整句校验，失败关闭而不是冒险截断。
        if len(self._buffer) > self._sentence_chars * 2:
            self._block()
            return []
        items: List[Tuple[int, str]] = []
        while not self._blocked and not self._closed:
            match = _SENTENCE_END.search(self._buffer)
            if match is None:
                break
            sentence = self._buffer[: match.end()]
            self._buffer = self._buffer[match.end() :]
            emitted = self._accept(sentence)
            if emitted is not None:
                items.append(emitted)
        return items

    def flush(self) -> List[Tuple[int, str]]:
        if self._blocked or self._closed:
            return []
        sentence, self._buffer = self._buffer, ""
        emitted = self._accept(sentence)
        return [emitted] if emitted is not None else []

    def _block(self) -> None:
        self._blocked = True
        self._buffer = ""

    def _accept(self, sentence: str) -> Optional[Tuple[int, str]]:
        if not sentence.strip():
            return None
        clean = sanitize_public_note(sentence, max_chars=self._sentence_chars)
        if clean is None:
            # 无法确认这一段可以公开：本轮剩余内容全部丢弃。
            self._block()
            return None
        if self._emitted_sentences >= self._max_sentences:
            self._closed = True
            return None
        if self._emitted_chars + len(clean) > self._max_chars:
            self._closed = True
            return None
        seq = self._seq
        self._seq += 1
        self._emitted_sentences += 1
        self._emitted_chars += len(clean)
        return seq, clean


def work_explanation_step_id(
    *, run_id: str, node: str, round_number: int, call_id: str, seq: int
) -> str:
    """稳定的公开说明步骤 id；实时与恢复去重使用同一键。"""

    safe = ":".join(
        str(part or "").replace(":", "_")
        for part in (run_id, node, round_number, call_id, seq)
    )
    return f"work-note:{safe}"
