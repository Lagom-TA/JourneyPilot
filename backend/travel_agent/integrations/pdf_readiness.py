"""Integrations pdf readiness."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from threading import Lock
import os


class PdfFontUnavailable(RuntimeError):
    pass


_FONT_NAME = "JourneyPilotCJK"


_FONT_LOCK = Lock()


_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


def _register_pdf_font() -> str:
    with _FONT_LOCK:
        if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
            return _FONT_NAME
        configured = os.getenv("JOURNEYPILOT_PDF_FONT_PATH")
        candidates = ([configured] if configured else []) + list(_FONT_CANDIDATES)
        last_error: Exception | None = None
        for item in candidates:
            if not item or not Path(item).is_file():
                continue
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(item), subfontIndex=0))
                return _FONT_NAME
            except Exception as exc:
                last_error = exc
                continue
        detail = f"; last error: {last_error}" if last_error else ""
        raise PdfFontUnavailable(
            "no embeddable CJK PDF font is installed; set JOURNEYPILOT_PDF_FONT_PATH"
            + detail
        )


def probe_pdf_renderer() -> str:
    """Verify the server can render CJK PDF text without creating an artifact.

    The probe renders one tiny in-memory page rather than exporting a report:
    a formal report needs a Delivery Bundle, while this check must never create
    or read a product artifact.
    """

    font = _register_pdf_font()
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.setFont(font, 12)
    canvas.drawString(24 * mm, 270 * mm, "JourneyPilot PDF 预检")
    canvas.save()
    if not buffer.getvalue().startswith(b"%PDF"):
        raise RuntimeError("PDF renderer did not produce a PDF document")
    return font


@dataclass(frozen=True)
class PdfRendererProbe:
    """开机那一次渲染预检的结论。运行期结构不再变化，所以不复检。"""

    available: bool
    font: str | None = None
    problem: str | None = None


_last_probe: PdfRendererProbe | None = None


def record_pdf_probe(probe: PdfRendererProbe) -> None:
    global _last_probe
    _last_probe = probe


def last_pdf_probe() -> PdfRendererProbe | None:
    """readiness 读它。``None`` = 启动时没跑过预检。"""

    return _last_probe
