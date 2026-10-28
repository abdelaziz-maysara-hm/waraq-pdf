import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "_fixtures"
DATA = ROOT / "tests" / "data"


@pytest.fixture(scope="session")
def fx():
    if not (FIX / "photos_large.pdf").exists():
        subprocess.check_call([sys.executable, str(ROOT / "tests" / "make_fixtures.py")])
    return FIX


def has_fixture(name):
    return (FIX / name).exists()


def source_lines(name="arabic_lines.txt"):
    return [l for l in (DATA / name).read_text(encoding="utf-8").splitlines() if l.strip()]
