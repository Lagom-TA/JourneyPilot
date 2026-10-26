"""PDF 导出的字体与渲染预检。"""

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
import logging

logger = logging.getLogger(__name__)


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
    """确认服务端能渲染中文 PDF 文本，不生成任何产物。

    预检只在内存中渲染一页，不导出报告：正式报告需要 Delivery Bundle，而这项
    检查不应创建或读取产品产物。
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


async def probe_pdf_font() -> str | None:
    """开机确认这台机器能排出中文 PDF，返回问题（None = 没问题）。

    字体探测放在启动而不是首次导出：一台缺可嵌入 CJK 字体的机器上，用户是在按下
    「导出」并等完一次渲染之后才知道这件事的。探测本身也走渲染通道，因为它就是
    一次真实渲染（一页、内存里、不产出任何产物）。

    不阻塞启动：缺字体降级的是导出，不是规划与问答。它自己有一条 ERROR，并在
    readiness 的 `pdf_export` 里能看见。
    """

    from travel_agent.runtime.blocking_work import run_blocking

    try:
        font = await run_blocking("pdf_export", probe_pdf_renderer)
    except PdfFontUnavailable as exc:
        record_pdf_probe(PdfRendererProbe(available=False, problem=str(exc)))
        return str(exc)
    except Exception as exc:  # 渲染器本身坏了也是「导不出 PDF」
        problem = f"PDF 渲染预检失败（{exc}）"
        record_pdf_probe(PdfRendererProbe(available=False, problem=problem))
        return problem
    record_pdf_probe(PdfRendererProbe(available=True, font=font))
    logger.info("PDF 渲染预检通过 | 字体: %s", font)
    return None
