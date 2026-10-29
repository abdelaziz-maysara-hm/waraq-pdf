"""Bundled fonts (SIL OFL 1.1, see assets/fonts/OFL-*.txt)."""
from pathlib import Path
import sys


def assets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    p = base / "waraq" / "assets" if (base / "waraq" / "assets").exists() else base / "assets"
    return p


def arabic_font_path() -> Path:
    return assets_dir() / "fonts" / "Amiri-Regular.ttf"


# family -> list of (ReportLab font name, file).  The first font that has a
# glyph for a character is used for it (Noto Sans Arabic has no Latin letters).
FAMILIES = {
    "naskh": [("WaraqAmiri", "Amiri-Regular.ttf")],
    "sans": [("WaraqNotoArabic", "NotoSansArabic-Regular.ttf"), ("WaraqNotoSans", "NotoSans-Regular.ttf")],
}

_registered = set()


def register_reportlab_font() -> str:
    """Register the bundled Amiri font with ReportLab and return its name."""
    return register_family("naskh")[0]


def register_family(family: str):
    """Register every font of ``family`` with ReportLab; return their names."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fam = FAMILIES.get(family) or FAMILIES["naskh"]
    names = []
    for name, fname in fam:
        if name not in _registered:
            pdfmetrics.registerFont(TTFont(name, str(assets_dir() / "fonts" / fname)))
            _registered.add(name)
        names.append(name)
    return names
