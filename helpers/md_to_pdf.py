"""Lightweight, pure-Python PDF building blocks for worksheets (fpdf2 + pypdf).

No browser, no HTML/CSS layout engine: markdown becomes a vector PDF through
fpdf2 using the bundled DejaVu Sans (Latin, Greek, Cyrillic; `helpers/fonts/`),
and the pair name is a small badge drawn onto every page of whatever worksheet
PDF it belongs to. Fonts are embedded as subsets, so output stays small.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import markdown
from fpdf import FPDF, FontFace

if TYPE_CHECKING:
    from pypdf import PageObject

logger = logging.getLogger(__name__)

__all__ = ["markdown_to_pdf_bytes", "note_page_bytes", "stamp_page"]

_A4 = (595.28, 841.89)
_MARGIN = 51.0  # ~18mm
_TOP_MARGIN = 66.0  # leaves the top strip free for the pair stamp on every page
_INK = (30, 27, 75)
_SKY = (2, 132, 199)
_SKY_TINT = (240, 249, 255)
_SKY_BORDER = (186, 230, 253)

_FONT = "dejavu"
_FONT_DIR = Path(__file__).parent / "fonts"
_REGULAR = str(_FONT_DIR / "DejaVuSans.ttf")
_BOLD = str(_FONT_DIR / "DejaVuSans-Bold.ttf")
# Names the stamp may carry in scripts DejaVu lacks (Ethiopic) or draws unjoined (Arabic).
_FALLBACKS = {
    "notoarabic": str(_FONT_DIR / "NotoSansArabic-Bold.ttf"),
    "notoethiopic": str(_FONT_DIR / "NotoSansEthiopic-Bold.ttf"),
}

_STAMP_MARGIN = 16.0
_STAMP_PAD_X = 11.0
_STAMP_PAD_Y = 6.0
_STAMP_FONT = 13.0

_TAG_STYLES = {
    "h1": FontFace(color=_INK, size_pt=20),
    "h2": FontFace(color=_INK, size_pt=15),
    "h3": FontFace(color=_INK, size_pt=13),
    "h4": FontFace(color=_INK, size_pt=11.5),
    "blockquote": FontFace(color=_SKY, emphasis="I"),
    "code": FontFace(color=_SKY),
    "pre": FontFace(color=_INK),
}


def _new_pdf(size: tuple[float, float] = _A4) -> FPDF:
    pdf = FPDF(orientation="portrait", unit="pt", format=size)
    pdf.add_font(_FONT, "", _REGULAR)
    pdf.add_font(_FONT, "B", _BOLD)
    # No italic file is bundled; italic text falls back to upright.
    pdf.add_font(_FONT, "I", _REGULAR)
    pdf.add_font(_FONT, "BI", _BOLD)
    pdf.set_margins(_MARGIN, _TOP_MARGIN, _MARGIN)
    pdf.set_auto_page_break(True, margin=_MARGIN)
    pdf.set_compression(True)
    return pdf


def markdown_to_pdf_bytes(md_text: str, title: str = "") -> bytes:
    """Renders markdown to an A4 PDF held in memory.

    Args:
        md_text (str): Markdown source (headings, lists, tables, quotes and
            code blocks are laid out; unsupported markup degrades to text).
        title (str): Document title metadata, and the fallback heading when
            `md_text` is empty.

    Returns:
        bytes: The PDF file contents (at least one page).
    """
    html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    pdf = _new_pdf()
    pdf.set_title(title)
    pdf.add_page()
    pdf.set_font(_FONT, size=11)
    pdf.set_text_color(*_INK)
    try:
        pdf.write_html(html or f"<h1>{title}</h1>", tag_styles=_TAG_STYLES)
    except Exception:
        logger.warning("worksheet markdown fell back to plain text", exc_info=True)
        pdf = _new_pdf()
        pdf.add_page()
        pdf.set_font(_FONT, size=11)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(0, 14, md_text, markdown=False)
    return bytes(pdf.output())


def note_page_bytes(heading: str, body: str, size: tuple[float, float] = _A4) -> bytes:
    """Renders a one-page note (used when a worksheet file can't be read).

    Args:
        heading (str): Large line at the top.
        body (str): Explanatory paragraph under it.
        size (tuple[float, float]): Page width and height in points.

    Returns:
        bytes: A one-page PDF.
    """
    pdf = _new_pdf(size)
    pdf.add_page()
    pdf.set_text_color(*_INK)
    pdf.set_font(_FONT, "B", 18)
    pdf.multi_cell(0, 24, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font(_FONT, size=11)
    pdf.multi_cell(0, 15, body)
    return bytes(pdf.output())


@lru_cache(maxsize=256)
def _stamp_overlay(label: str, width: float, height: float) -> bytes:
    """Draws the badge on an otherwise empty page of the given size (cached: a packet reuses a few)."""
    overlay = FPDF(orientation="portrait", unit="pt", format=(width, height))
    overlay.add_font(_FONT, "B", _BOLD)
    for family, path in _FALLBACKS.items():
        overlay.add_font(family, "B", path)
    # Shaping joins Arabic letters and orders right-to-left runs; fpdf2 then picks each glyph's
    # font from the fallbacks, so a pair of "Ada & ሰላም" draws both halves.
    overlay.set_text_shaping(True)
    overlay.set_fallback_fonts(list(_FALLBACKS), exact_match=False)
    overlay.set_auto_page_break(False)
    overlay.add_page()
    text = label
    font_size = _STAMP_FONT
    overlay.set_font(_FONT, "B", font_size)
    max_text = width - 2 * (_STAMP_MARGIN + _STAMP_PAD_X)
    while overlay.get_string_width(text) > max_text and font_size > 7:
        font_size -= 0.5
        overlay.set_font(_FONT, "B", font_size)
    while overlay.get_string_width(text) > max_text and len(text) > 1:
        text = text[:-2].rstrip() + "..."
    badge_w = overlay.get_string_width(text) + 2 * _STAMP_PAD_X
    badge_h = font_size + 2 * _STAMP_PAD_Y
    x = width - badge_w - _STAMP_MARGIN
    y = _STAMP_MARGIN
    overlay.set_fill_color(*_SKY_TINT)
    overlay.set_draw_color(*_SKY_BORDER)
    overlay.set_line_width(1.2)
    overlay.rect(x, y, badge_w, badge_h, style="DF", round_corners=True, corner_radius=5)
    overlay.set_text_color(*_INK)
    overlay.set_xy(x, y)
    overlay.cell(badge_w, badge_h, text, align="C")
    return bytes(overlay.output())


def stamp_page(page: PageObject, label: str) -> None:
    """Stamps a badge in the page's top-right corner, in place.

    Args:
        page (pypdf.PageObject): The page to stamp; must already be on a writer.
        label (str): Badge text, e.g. the pair's names.

    Returns:
        None
    """
    from pypdf import PdfReader, Transformation

    box = page.mediabox
    overlay = _stamp_overlay(label, round(float(box.width), 2), round(float(box.height), 2))
    stamp = PdfReader(BytesIO(overlay)).pages[0]
    # A source page's mediabox needn't start at (0, 0); line the overlay up with it.
    page.merge_transformed_page(stamp, Transformation().translate(tx=float(box.left), ty=float(box.bottom)))
