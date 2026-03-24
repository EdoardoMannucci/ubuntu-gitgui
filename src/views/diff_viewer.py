"""
Diff Viewer — bottom-right panel showing syntax-highlighted unified diffs.

Components
──────────
DiffHighlighter   QSyntaxHighlighter subclass
    Applied to the QTextEdit's QTextDocument.  Uses regex-based rules to colour
    every line according to its role in the unified diff format:

      Line prefix   Meaning            Colour (Catppuccin Mocha)
      ──────────    ─────────────────  ─────────────────────────
      +             Added line         green  #a6e3a1  + dark-green bg
      -             Removed line       red    #f38ba8  + dark-red bg
      @@            Hunk header        sky    #89dceb
      +++  ---      File name header   subtext #a6adc8 (bold)
      diff/index    Diff metadata      overlay #585b70
      (default)     Context line       default text colour

DiffViewerWidget  QWidget container
    Holds a header label (file name + staged/unstaged indicator) and the
    read-only QTextEdit.  Exposes one public method:

        show_diff(path, is_staged)   — fetch diff from StagingController and display
        show_placeholder(message)    — clear the view and show a hint text
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.controllers.staging_controller import StagingController


# ── Colour palette (Catppuccin Mocha) ────────────────────────────────────────

_COL_ADDED_FG    = QColor("#a6e3a1")   # green text
_COL_ADDED_BG    = QColor("#1a2e1a")   # very dark green background
_COL_REMOVED_FG  = QColor("#f38ba8")   # red text
_COL_REMOVED_BG  = QColor("#2e1a1a")   # very dark red background
_COL_HUNK        = QColor("#89dceb")   # sky / teal
_COL_FILE_HDR    = QColor("#b4befe")   # lavender (bold)
_COL_META        = QColor("#585b70")   # overlay (dim)
_COL_CONTEXT     = QColor("#a6adc8")   # subtext (unchanged lines)


# ── DiffHighlighter ───────────────────────────────────────────────────────────

# Pre-compiled patterns for each line category (in priority order)
_RULES: list[tuple[re.Pattern[str], QTextCharFormat]] = []


def _fmt(fg: QColor, bg: QColor | None = None, bold: bool = False) -> QTextCharFormat:
    """Helper: build a QTextCharFormat with optional background and bold."""
    f = QTextCharFormat()
    f.setForeground(fg)
    if bg is not None:
        f.setBackground(bg)
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    return f


# Build the rules list once at import time
_RULES = [
    # 1. File-name header lines (must come before generic + / - rules)
    (re.compile(r"^\+\+\+"),                   _fmt(_COL_FILE_HDR, bold=True)),
    (re.compile(r"^---"),                       _fmt(_COL_FILE_HDR, bold=True)),
    # 2. Added lines
    (re.compile(r"^\+"),                        _fmt(_COL_ADDED_FG,   _COL_ADDED_BG)),
    # 3. Removed lines
    (re.compile(r"^-"),                         _fmt(_COL_REMOVED_FG, _COL_REMOVED_BG)),
    # 4. Hunk headers  (@@ -a,b +c,d @@ optional-context)
    (re.compile(r"^@@"),                        _fmt(_COL_HUNK)),
    # 5. Diff metadata (diff --git, index, new file mode, deleted file mode, …)
    (re.compile(r"^(diff |index |new file|deleted file|rename|similarity|Binary)"),
                                                _fmt(_COL_META)),
    # 6. Context lines (lines starting with a space — unchanged)
    (re.compile(r"^ "),                         _fmt(_COL_CONTEXT)),
    # 7. Error / placeholder lines produced by the controller (#)
    (re.compile(r"^#"),                         _fmt(_COL_META)),
]


class DiffHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for unified diff format.

    Instantiate with the QTextDocument of the diff text edit:

        highlighter = DiffHighlighter(text_edit.document())
    """

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        """Apply colour formatting to a single line (*text*)."""
        for pattern, fmt in _RULES:
            if pattern.match(text):
                # Apply the format to the entire line
                self.setFormat(0, len(text), fmt)
                return
        # Unmatched lines (e.g. "No newline at end of file") — leave default


# ── DiffViewerWidget ──────────────────────────────────────────────────────────

class DiffViewerWidget(QWidget):
    """Read-only diff panel with syntax highlighting.

    Usage::

        viewer = DiffViewerWidget(staging_ctrl)
        viewer.show_diff("src/main.py", is_staged=False)
        viewer.show_placeholder()          # reset to hint text
    """

    # Monospace font preference list (Qt tries them in order)
    _MONO_FAMILIES = "JetBrains Mono, Fira Code, Cascadia Code, Ubuntu Mono, Courier New, monospace"

    def __init__(
        self,
        staging_ctrl: StagingController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._staging = staging_ctrl
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar: file path + staged/unstaged badge ──────────
        self._header = QLabel()
        self._header.setObjectName("diff_header")
        self._header.hide()
        layout.addWidget(self._header)

        # ── Diff text area ─────────────────────────────────────────
        self._edit = QTextEdit()
        self._edit.setObjectName("diff_edit")
        self._edit.setReadOnly(True)
        self._edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Monospace font
        font = QFont(self._MONO_FAMILIES)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self._edit.setFont(font)

        # Attach the syntax highlighter permanently to the document
        self._highlighter = DiffHighlighter(self._edit.document())

        layout.addWidget(self._edit)

        # Start with the placeholder state
        self.show_placeholder()

    # ── Public API ────────────────────────────────────────────────────

    def show_diff(self, path: str, is_staged: bool) -> None:
        """Fetch and display the diff for *path*.

        Args:
            path:      Repo-relative file path.
            is_staged: True  → diff of staged version (index vs HEAD).
                       False → diff of unstaged version (working tree vs index).
        """
        diff_text = self._staging.get_diff(path, is_staged)

        # Update header
        badge = "STAGED" if is_staged else "UNSTAGED"
        self._header.setText(f"  {badge}  ·  {path}")
        self._header.show()

        # Set the diff text — the highlighter fires on every block automatically
        self._edit.setPlainText(diff_text)

        # Scroll back to the top
        self._edit.moveCursor(self._edit.textCursor().MoveOperation.Start)

    def show_commit_diff(self, path: str, short_hash: str, full_hash: str) -> None:
        """Display the diff of *path* as it was changed in *full_hash*.

        Args:
            path:       Repo-relative file path.
            short_hash: 7-char hash displayed in the header badge.
            full_hash:  40-char hash passed to ``git show``.
        """
        diff_text = self._staging.get_commit_diff(full_hash, path)

        self._header.setText(f"  {short_hash}  ·  {path}")
        self._header.show()
        self._edit.setPlainText(diff_text)
        self._edit.moveCursor(self._edit.textCursor().MoveOperation.Start)

    def show_placeholder(self, message: str = "Select a file to see its diff.") -> None:
        """Clear the diff and show a hint message."""
        self._header.hide()
        self._edit.setPlaceholderText(message)
        self._edit.clear()

    def clear(self) -> None:
        """Alias for show_placeholder — called when the repo is closed."""
        self.show_placeholder()
