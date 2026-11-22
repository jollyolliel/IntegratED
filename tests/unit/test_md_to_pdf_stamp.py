"""The pair stamp must draw names in scripts DejaVu Sans lacks (Ethiopic) and shape joined ones (Arabic)."""

from io import BytesIO
from typing import Any

import pytest
from pypdf import PdfReader

from helpers.md_to_pdf import _stamp_overlay

pytestmark = pytest.mark.unit


def _embedded_fonts(label: str) -> set[str]:
    page: Any = PdfReader(BytesIO(_stamp_overlay(label, 595.28, 841.89))).pages[0]
    fonts = page["/Resources"]["/Font"]
    return {str(fonts[name].get_object()["/BaseFont"]) for name in fonts}


def test_an_amharic_name_is_drawn_with_an_ethiopic_font():
    assert any("NotoSansEthiopic" in name for name in _embedded_fonts("ሰላም አበበ"))


def test_an_arabic_name_is_shaped_so_its_letters_join(monkeypatch):
    """DejaVu has the Arabic glyphs, so only shaping (joining, right-to-left order) is needed."""
    from fpdf import FPDF

    calls = []
    original = FPDF.set_text_shaping
    monkeypatch.setattr(FPDF, "set_text_shaping", lambda self, *a, **k: (calls.append(a), original(self, *a, **k))[1])

    _stamp_overlay("أحمد محمد", 300.0, 100.0)

    assert calls == [(True,)]


def test_a_latin_name_needs_no_fallback_font():
    assert not any("Noto" in name for name in _embedded_fonts("Ada Lovelace"))


def test_a_mixed_pair_name_uses_each_font_it_needs():
    names = _embedded_fonts("Ada & ሰላም")
    assert any("NotoSansEthiopic" in name for name in names)


@pytest.mark.parametrize("label", ["أحمد", "ሰላም", "Ada"])
def test_the_stamp_is_a_single_page_pdf(label):
    assert len(PdfReader(BytesIO(_stamp_overlay(label, 595.28, 841.89))).pages) == 1
