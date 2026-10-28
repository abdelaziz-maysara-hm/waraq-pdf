from pathlib import Path
import sys

def assets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    p = base / "waraq" / "assets" if (base / "waraq" / "assets").exists() else base / "assets"
    return p


def arabic_font_path() -> Path:
    return assets_dir() / "fonts" / "Amiri-Regular.ttf"


_registered = False


def register_reportlab_font() -> str:
    """Register the bundled Amiri font with ReportLab and return its name."""
    global _registered
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if not _registered:
        pdfmetrics.registerFont(TTFont("WaraqAmiri", str(arabic_font_path())))
        _registered = True
    return "WaraqAmiri"
