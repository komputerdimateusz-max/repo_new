"""Helpers for configuring Unicode-capable fonts in ReportLab PDFs."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FALLBACK_WARNING_EMITTED = False


def find_unicode_ttf() -> str | None:
    """Return first available system Unicode font path for PDF generation."""
    candidates = [
        # Windows
        r"C:\\Windows\\Fonts\\arial.ttf",
        r"C:\\Windows\\Fonts\\calibri.ttf",
        r"C:\\Windows\\Fonts\\segoeui.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]

    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def register_pdf_font() -> str:
    """Register a Unicode font for ReportLab and return chosen font name."""
    global _FALLBACK_WARNING_EMITTED

    font_path = find_unicode_ttf()
    if font_path:
        font_name = "AppUnicode"
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        registered_fonts = set(pdfmetrics.getRegisteredFontNames())
        if font_name not in registered_fonts:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        return font_name

    if not _FALLBACK_WARNING_EMITTED:
        logger.warning("No Unicode TTF font found; Polish characters may render incorrectly.")
        _FALLBACK_WARNING_EMITTED = True
    return "Helvetica"
