"""
Application settings — JSON persistence layer.

Settings file: ~/.config/ubuntu-gitgui/config.json

Keys
────
    language  : str  — UI language code ("en" | "it"). Default: "en".
    theme     : str  — UI colour theme ("dark" | "light"). Default: "dark".

Usage::

    from src.utils.app_settings import load_settings, save_settings

    cfg = load_settings()
    cfg["theme"] = "light"
    save_settings(cfg)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / ".config" / "ubuntu-gitgui"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, object] = {
    "language": "en",
    "theme":    "dark",
}


def load_settings() -> dict:
    """Load settings from disk.  Missing keys are filled from defaults."""
    result = dict(_DEFAULTS)
    if not _CONFIG_FILE.exists():
        return result
    try:
        with _CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data: dict = json.load(fh)
        result.update(data)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load config.json: %s", exc)
    return result


def save_settings(settings: dict) -> None:
    """Persist *settings* to disk (atomic write, mode 0o600)."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_FILE.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        tmp.replace(_CONFIG_FILE)
    except OSError as exc:
        logger.error("Could not save config.json: %s", exc)
