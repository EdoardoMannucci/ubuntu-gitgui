"""
Global QSS stylesheet loader for ubuntu-gitgui.

Provides two themes:
  - "dark"  — "Neon Terminal Editorial" design system (src/styles/modern.qss)
  - "light" — GitHub Light-inspired palette (src/styles/light.qss)

Falls back to a minimal embedded stylesheet if the file cannot be read
(e.g., inside a PyInstaller bundle with an unexpected path).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _styles_dir() -> Path:
    """Resolve the src/styles directory regardless of frozen/normal execution."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: _MEIPASS is the extraction directory
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent.parent  # project root
    return base / "src" / "styles"


def get_dark_stylesheet() -> str:
    """Return the dark (Neon Terminal Editorial) QSS stylesheet string."""
    path = _styles_dir() / "modern.qss"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        # Minimal fallback so the app still launches
        return "QWidget { background-color: #0d0d1c; color: #e6e3fa; font-size: 13px; }"


def get_light_stylesheet() -> str:
    """Return the light (GitHub Light) QSS stylesheet string."""
    path = _styles_dir() / "light.qss"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "QWidget { background-color: #ffffff; color: #1f2328; font-size: 13px; }"


def get_stylesheet(theme: str) -> str:
    """Return the QSS for the given theme name ('dark' or 'light')."""
    if theme == "light":
        return get_light_stylesheet()
    return get_dark_stylesheet()
