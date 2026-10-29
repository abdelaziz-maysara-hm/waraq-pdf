"""Runs tests/gui_drive.py (the real GUI, every tool, AR+EN) under Xvfb when available."""
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("xvfb-run"), reason="needs xvfb-run")
def test_gui_drive(fx):
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable,
                        str(ROOT / "tests" / "gui_drive.py")], capture_output=True, text=True, timeout=900)
    print(r.stdout[-3000:])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]


def test_i18n_windows_vs_linux(monkeypatch):
    from waraq.gui import i18n
    i18n.set_lang("ar")
    monkeypatch.setenv("WARAQ_UI_SHAPING", "0")      # Windows path: logical text + RLM
    s = i18n.t("tool_merge")
    assert s == "\u200fدمج ملفات PDF"
    monkeypatch.setenv("WARAQ_UI_SHAPING", "1")      # Linux path: shaped visual text
    s = i18n.t("tool_merge")
    assert "دمج" not in s and any(0xFE70 <= ord(c) <= 0xFEFF for c in s)
    i18n.set_lang("en")
    assert i18n.t("tool_merge") == "Merge PDFs"
    assert set(k for k in i18n.S) and all(len(v) == 2 and v[0] and v[1] for v in i18n.S.values())


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("xvfb-run"), reason="needs xvfb-run")
def test_viewer_gui_drive(fx):
    """Viewer + editor + home screen, driven through the real widgets (tests/gui_viewer_drive.py)."""
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1366x860x24", sys.executable,
                        str(ROOT / "tests" / "gui_viewer_drive.py")], capture_output=True, text=True, timeout=900)
    print(r.stdout[-3000:])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
