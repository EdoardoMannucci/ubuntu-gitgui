"""
CreateTagDialog — modal dialog for creating a new Git tag.

Supports both lightweight and annotated tags:
  - Name only  → lightweight tag
  - Name + Msg → annotated tag (stored as a git object with the message)

The dialog validates that the tag name is non-empty before enabling OK.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)


class CreateTagDialog(QDialog):
    """Prompt for a tag name and an optional annotation message.

    After ``exec()`` returns ``Accepted``, read:
        dialog.tag_name    — stripped tag name string
        dialog.tag_message — annotation message (empty → lightweight tag)
    """

    def __init__(self, commit_short: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Create Tag — {commit_short}")
        self.setMinimumWidth(400)

        self.tag_name: str = ""
        self.tag_message: str = ""

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 14, 16, 12)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. v1.2.0")
        self._name_edit.textChanged.connect(self._validate)
        form.addRow(QLabel("Tag name:"), self._name_edit)

        self._msg_edit = QTextEdit()
        self._msg_edit.setPlaceholderText(
            "Optional annotation message.\n"
            "Leave blank for a lightweight tag."
        )
        self._msg_edit.setFixedHeight(90)
        form.addRow(QLabel("Message:"), self._msg_edit)

        root.addLayout(form)

        note = QLabel(
            "A tag <i>with</i> a message creates an <b>annotated</b> tag "
            "(recommended for releases). Without a message it is a lightweight tag."
        )
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignLeft)
        note.setStyleSheet("color: #aba9be; font-size: 11px;")
        root.addWidget(note)

        self._bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        self._bbox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._bbox.accepted.connect(self._on_accept)
        self._bbox.rejected.connect(self.reject)
        root.addWidget(self._bbox)

    # ── Validation ────────────────────────────────────────────────────

    def _validate(self, text: str) -> None:
        ok = bool(text.strip())
        self._bbox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    # ── Accept ────────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        self.tag_name = self._name_edit.text().strip()
        self.tag_message = self._msg_edit.toPlainText().strip()
        self.accept()
