"""
Global QSS stylesheet loader for ubuntu-gitgui.

Loads src/styles/modern.qss — the "Neon Terminal Editorial" design system.
Falls back to a minimal embedded stylesheet if the file cannot be read
(e.g., inside a PyInstaller bundle with an unexpected path).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _qss_path() -> Path:
    """Resolve the path to modern.qss regardless of frozen/normal execution."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: _MEIPASS is the extraction directory
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent.parent  # project root
    return base / "src" / "styles" / "modern.qss"


def get_dark_stylesheet() -> str:
    """Return the application-wide QSS stylesheet string."""
    path = _qss_path()
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        # Minimal fallback so the app still launches
        return """
        QWidget { background-color: #0d0d1c; color: #e6e3fa; font-size: 13px; }
        """
