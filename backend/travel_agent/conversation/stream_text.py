"""
流式 token 过滤器：实时剔除 HTML 注释数据块、思考块和纯文本推理块。
从 LLM 输出中过滤掉不应出现在用户可见正文中的内容。
"""

from __future__ import annotations

import re


class StreamingStripper:
    """
    流式 token 过滤器：实时剔除以下三类块，防止其出现在用户可见的正文中：
    - <!-- DESTINATION_JSON ... -->   快速模式目的地 JSON
    - <think>...</think>              模型推理/思考内容（Qwen3、QwQ 等模型会输出）
    - "Thinking Process" 等开头的纯文本推理块（部分 Qwen3 API 不输出 <think> 标签）
    """

    _OPEN_COMMENTS = ("<!-- DESTINATION_JSON",)
    _CLOSE_COMMENT = "-->"
    _OPEN_THINK = "<think>"
    _CLOSE_THINK = "</think>"

    _THINKING_MARKERS = (
        "Thinking Process",
        "thinking process",
        "Let me analyze",
        "Let me think",
        "思考过程",
    )

    _INTERNAL_MARKER_PREFIXES = (
        "[[fact:",
        "[[fact：",
        "[来源:",
        "[来源：",
        "[source:",
        "[source：",
        "[数据来源:",
        "[数据来源：",
        "[ref:",
        "[ref：",
        "[引用:",
        "[引用：",
    )

    _THINKING_END_RE = re.compile(
        r"\n\n(?=[^\x00-\x7F#\-\*]|\s*#{1,3}\s|\s*[-*]\s|[A-Z])",
    )

    _TEXT_THINK_MAX_CHARS = 4000

    _HOLD = max(
        max(len(tag) for tag in _OPEN_COMMENTS),
        len("<think>"),
        len("Thinking Process"),
        max(len(tag) for tag in _INTERNAL_MARKER_PREFIXES),
    )

    def __init__(self) -> None:
        self._buf = ""
        self._in_comment_block = False
        self._in_think_block = False
        self._in_text_think_block = False
        self._comment_buf = ""
        self._think_buf = ""
        self._text_think_buf = ""
        self._in_internal_marker = False
        self._internal_marker_buf = ""
        self._internal_marker_close = "]"

    def feed(self, chunk: str) -> str:
        """返回可立即显示的文本（两类注释块、think 块、纯文本推理块均被过滤）。"""
        if self._in_internal_marker:
            self._internal_marker_buf += chunk
            close_pos = self._internal_marker_buf.find(self._internal_marker_close)
            if close_pos != -1:
                remainder = self._internal_marker_buf[
                    close_pos + len(self._internal_marker_close) :
                ]
                self._internal_marker_buf = ""
                self._in_internal_marker = False
                self._buf = ""
                return self._process(remainder)
            return ""
        if self._in_comment_block:
            self._comment_buf += chunk
            close_pos = self._comment_buf.find(self._CLOSE_COMMENT)
            if close_pos != -1:
                remainder = self._comment_buf[close_pos + len(self._CLOSE_COMMENT) :]
                self._comment_buf = ""
                self._in_comment_block = False
                self._buf = ""
                return self._process(remainder)
            return ""
        if self._in_think_block:
            self._think_buf += chunk
            close_pos = self._think_buf.find(self._CLOSE_THINK)
            if close_pos != -1:
                remainder = self._think_buf[close_pos + len(self._CLOSE_THINK) :]
                self._think_buf = ""
                self._in_think_block = False
                self._buf = ""
                return self._process(remainder)
            return ""
        if self._in_text_think_block:
            self._text_think_buf += chunk

            m = self._THINKING_END_RE.search(self._text_think_buf)
            if m:
                remainder = self._text_think_buf[m.start() :]
                self._text_think_buf = ""
                self._in_text_think_block = False
                self._buf = ""
                return self._process(remainder)

            if len(self._text_think_buf) >= self._TEXT_THINK_MAX_CHARS:
                overflow = self._text_think_buf[self._TEXT_THINK_MAX_CHARS :]

                split_at = self._text_think_buf.rfind("\n\n")
                if split_at != -1 and split_at > 0:
                    remainder = self._text_think_buf[split_at:]
                else:
                    remainder = overflow or self._text_think_buf[-200:]
                self._text_think_buf = ""
                self._in_text_think_block = False
                self._buf = ""
                return self._process(remainder)
            return ""
        return self._process(chunk)

    def _find_text_thinking_marker(self, buf: str):
        """在 buf 中查找最早出现的纯文本推理块标记，返回 (pos, marker) 或 (-1, '')。"""
        earliest_pos = -1
        earliest_marker = ""
        for marker in self._THINKING_MARKERS:
            pos = buf.find(marker)
            if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                prefix = buf[:pos]
                if not prefix or prefix[-1] in ("\n", "\r", " ", "\t") or pos == 0:
                    earliest_pos = pos
                    earliest_marker = marker
        return earliest_pos, earliest_marker

    def _find_comment_open(self, buf: str):
        """在 buf 中查找最早出现的注释块 open 标签，返回 (pos, tag) 或 (-1, '')。"""
        earliest_pos = -1
        earliest_tag = ""
        for tag in self._OPEN_COMMENTS:
            pos = buf.find(tag)
            if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                earliest_pos = pos
                earliest_tag = tag
        return earliest_pos, earliest_tag

    def _find_internal_marker(self, buf: str):
        """查找最早的机器引用或 legacy 来源标记，英文前缀忽略大小写。"""
        lower = buf.lower()
        earliest_pos = -1
        earliest_tag = ""
        for tag in self._INTERNAL_MARKER_PREFIXES:
            pos = lower.find(tag.lower())
            if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                earliest_pos = pos
                earliest_tag = tag
        return earliest_pos, earliest_tag

    def _process(self, text: str) -> str:
        self._buf += text

        comment_pos, comment_tag = self._find_comment_open(self._buf)
        think_pos = self._buf.find(self._OPEN_THINK)
        text_think_pos, text_think_marker = self._find_text_thinking_marker(self._buf)
        marker_pos, marker_tag = self._find_internal_marker(self._buf)

        earliest_pos: int = -1
        earliest_type: str = ""
        if comment_pos != -1:
            earliest_pos, earliest_type = comment_pos, "comment"
        if think_pos != -1 and (earliest_pos == -1 or think_pos < earliest_pos):
            earliest_pos, earliest_type = think_pos, "think"
        if text_think_pos != -1 and (
            earliest_pos == -1 or text_think_pos < earliest_pos
        ):
            earliest_pos, earliest_type = text_think_pos, "text_think"
        if marker_pos != -1 and (earliest_pos == -1 or marker_pos < earliest_pos):
            earliest_pos, earliest_type = marker_pos, "internal_marker"

        if earliest_type == "internal_marker":
            safe = self._buf[:earliest_pos]
            marker_start = self._buf[earliest_pos : earliest_pos + len(marker_tag)]
            self._internal_marker_close = "]]" if marker_start.startswith("[[") else "]"
            self._in_internal_marker = True
            self._internal_marker_buf = self._buf[earliest_pos + len(marker_tag) :]
            self._buf = ""
            close_pos = self._internal_marker_buf.find(self._internal_marker_close)
            if close_pos != -1:
                remainder = self._internal_marker_buf[
                    close_pos + len(self._internal_marker_close) :
                ]
                self._internal_marker_buf = ""
                self._in_internal_marker = False
                return safe + self._process(remainder)
            return safe

        if earliest_type == "think":
            safe = self._buf[:earliest_pos]
            self._in_think_block = True
            self._think_buf = self._buf[earliest_pos + len(self._OPEN_THINK) :]
            self._buf = ""
            close_pos = self._think_buf.find(self._CLOSE_THINK)
            if close_pos != -1:
                remainder = self._think_buf[close_pos + len(self._CLOSE_THINK) :]
                self._think_buf = ""
                self._in_think_block = False
                return safe + self._process(remainder)
            return safe

        if earliest_type == "comment":
            safe = self._buf[:earliest_pos]
            self._in_comment_block = True
            self._comment_buf = self._buf[earliest_pos + len(comment_tag) :]
            self._buf = ""
            close_pos = self._comment_buf.find(self._CLOSE_COMMENT)
            if close_pos != -1:
                remainder = self._comment_buf[close_pos + len(self._CLOSE_COMMENT) :]
                self._comment_buf = ""
                self._in_comment_block = False
                return safe + self._process(remainder)
            return safe

        if earliest_type == "text_think":
            safe = self._buf[:earliest_pos]
            self._in_text_think_block = True
            self._text_think_buf = self._buf[earliest_pos + len(text_think_marker) :]
            self._buf = ""

            m = self._THINKING_END_RE.search(self._text_think_buf)
            if m:
                remainder = self._text_think_buf[m.start() :]
                self._text_think_buf = ""
                self._in_text_think_block = False
                return safe + self._process(remainder)
            return safe

        all_patterns = (
            list(self._OPEN_COMMENTS)
            + [self._OPEN_THINK]
            + list(self._THINKING_MARKERS)
            + list(self._INTERNAL_MARKER_PREFIXES)
        )
        max_hold = min(self._HOLD, len(self._buf))
        best_hold = 0
        for pattern in all_patterns:
            for prefix_len in range(min(len(pattern), max_hold), 0, -1):
                if pattern.lower().startswith(self._buf[-prefix_len:].lower()):
                    best_hold = max(best_hold, prefix_len)
                    break
        if best_hold > 0:
            safe = self._buf[:-best_hold]
            self._buf = self._buf[-best_hold:]
            return safe
        safe = self._buf
        self._buf = ""
        return safe

    def flush(self) -> str:
        """流结束时调用，返回剩余可显示文本。"""
        if (
            self._in_comment_block
            or self._in_think_block
            or self._in_text_think_block
            or self._in_internal_marker
        ):
            return ""
        result = self._buf
        self._buf = ""
        return result


def strip_non_display_blocks(content: str) -> str:
    """Apply the streaming visibility contract to persisted/non-stream content."""

    stripper = StreamingStripper()
    return stripper.feed(content) + stripper.flush()


_THINKING_TEXT_PATTERN = re.compile(
    r"^(?:Thinking Process|thinking process|Let me analyze|Let me think|思考过程)"
    r"[\s\S]*?(?=\n\n(?=[^\x00-\x7F#\-\*]|\s*#{1,3}\s|\s*[-*]\s))",
    re.MULTILINE,
)


_LEADING_ENGLISH_THINKING_PATTERN = re.compile(
    r"^(?:Thinking Process|thinking process|Let me analyze|Let me think)[\s\S]+",
)


def strip_thinking_text(content: str) -> str:
    """
    移除 LLM 输出中的纯文本推理过程（Qwen3 等模型可能输出 "Thinking Process:" 等英文推理块）。
    作为最终兜底，在内容写入前端和数据库之前调用。
    """
    if not content:
        return content

    cleaned = _THINKING_TEXT_PATTERN.sub("", content).lstrip()
    if cleaned and cleaned != content:
        return cleaned

    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", content))
    has_markdown = bool(re.search(r"\n#{1,3}\s", content))
    if not has_cjk and not has_markdown:
        return content

    for marker in (
        "Thinking Process",
        "thinking process",
        "Let me analyze",
        "Let me think",
        "思考过程",
    ):
        if content.lstrip().startswith(marker):
            m = re.search(r"\n\n(?=[^\x00-\x7F]|\s*#{1,3}\s|\s*[-*]\s)", content)
            if m:
                candidate = content[m.start() :].lstrip()
                if candidate:
                    return candidate
            break

    return content
