"""
Centralized icon factory for ubuntu-gitgui.

All icons are rendered with qtawesome using the "Neon Terminal Editorial"
palette so that colours stay in sync with modern.qss.

Usage::

    from src.utils.icons import icon
    action.setIcon(icon("fetch"))
    button.setIcon(icon("commit"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import qtawesome as qta

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon

# ── Neon Terminal palette (must match modern.qss) ─────────────────────────────
_TEXT    = "#e6e3fa"   # on_surface — primary text
_PRIMARY = "#9cefff"   # neon cyan — main accent
_PURPLE  = "#d1abfd"   # secondary — electric purple
_PINK    = "#ffd3f2"   # tertiary  — soft pink
_GREEN   = "#9cefff"   # use cyan for success (no pure green)
_RED     = "#ff716c"   # error
_MUTED   = "#aba9be"   # on_surface_variant — metadata
_DIM     = "#474658"   # outline_variant — disabled

# ── Icon map: logical name → (fa_id, colour) ─────────────────────────────────
_MAP: dict[str, tuple[str, str]] = {
    # ── Toolbar / network ops ─────────────────────────────────────────
    "fetch":      ("fa6s.rotate",                  _PRIMARY),
    "pull":       ("fa6s.arrow-down",              _PRIMARY),
    "push":       ("fa6s.arrow-up",                _PRIMARY),
    "undo":       ("fa6s.rotate-left",             _MUTED),
    "redo":       ("fa6s.rotate-right",            _MUTED),
    "branch":     ("fa6s.code-branch",             _TEXT),
    "stash":      ("fa6s.layer-group",             _MUTED),
    "pop":        ("fa6s.box-open",                _MUTED),
    "identity":   ("fa6s.user-gear",               _MUTED),
    # ── File menu ─────────────────────────────────────────────────────
    "open":       ("fa6s.folder-open",             _PRIMARY),
    "init":       ("fa6s.plus",                    _GREEN),
    "clone":      ("fa6s.clone",                   _MUTED),
    "profiles":   ("fa6s.users-gear",              _MUTED),
    "quit":       ("fa6s.right-from-bracket",      _RED),
    # ── Staging widget ────────────────────────────────────────────────
    "stage_sel":  ("fa6s.arrow-up",                _GREEN),
    "stage_all":  ("fa6s.angles-up",               _GREEN),
    "unstage_sel":("fa6s.arrow-down",              _PURPLE),
    "unstage_all":("fa6s.angles-down",             _PURPLE),
    "commit":     ("fa6s.check",                   _GREEN),
    # ── Context menu — branch ─────────────────────────────────────────
    "checkout":   ("fa6s.circle-check",            _GREEN),
    "delete":     ("fa6s.trash",                   _RED),
    "rename":     ("fa6s.pencil",                  _PURPLE),
    "merge_into": ("fa6s.code-branch",             _PRIMARY),
    # ── Context menu — commit graph ───────────────────────────────────
    "copy_hash":  ("fa6s.copy",                    _MUTED),
    "checkout_detached": ("fa6s.clock-rotate-left", _PRIMARY),
    # ── Menu bar ─────────────────────────────────────────────────────
    "settings":   ("fa6s.gear",                    _MUTED),
    "help":       ("fa6s.circle-question",         _MUTED),
    "about":      ("fa6s.circle-info",             _PRIMARY),
    "links":      ("fa6s.arrow-up-right-from-square", _PRIMARY),
    # ── Misc ─────────────────────────────────────────────────────────
    "abort":      ("fa6s.circle-xmark",            _RED),
    "tag":        ("fa6s.tag",                     _PINK),
}


def icon(name: str, *, color: str | None = None) -> "QIcon":
    """Return a QIcon for *name*.

    Args:
        name:   A logical icon name from the map above.
        color:  Override the default colour (hex string, e.g. ``"#ff0000"``).

    Returns a fallback question-mark icon if *name* is not found.
    """
    if name not in _MAP:
        return qta.icon("fa6s.circle-question", color=_DIM)
    fa_id, default_color = _MAP[name]
    return qta.icon(fa_id, color=color or default_color)
