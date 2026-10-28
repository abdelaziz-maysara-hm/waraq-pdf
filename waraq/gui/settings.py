import json
import os
from pathlib import Path


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Waraq" / "settings.json"


DEFAULTS = {"lang": "ar", "theme": "dark", "shaping": None, "last_dir": ""}


def load() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return {**DEFAULTS, **data}
    except Exception:
        return dict(DEFAULTS)


def save(data: dict) -> None:
    p = settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
