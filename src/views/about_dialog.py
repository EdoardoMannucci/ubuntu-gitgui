"""
AboutDialog — simple informational dialog shown via Help → About.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from src.utils.icons import icon as get_icon

_APP_NAME    = "ubuntu-gitgui"
_VERSION     = "0.4.0-alpha"
_DESCRIPTION = "A modern, open-source Git GUI for Linux."
_LICENSE     = "MIT License"
_REPO_URL    = "https://github.com/edoardottt/ubuntu-gitgui"


class AboutDialog(QDialog):
    """Simple About dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {_APP_NAME}")
        self.setWindowIcon(get_icon("about"))
        self.setFixedSize(380, 240)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 16)

        # App name
        name_lbl = QLabel(_APP_NAME)
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        name_lbl.setFont(font)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("color: #89b4fa;")
        layout.addWidget(name_lbl)

        # Version
        ver_lbl = QLabel(f"Version {_VERSION}")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(ver_lbl)

        # Description
        desc_lbl = QLabel(_DESCRIPTION)
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        layout.addWidget(desc_lbl)

        # License + repo
        info_lbl = QLabel(
            f'{_LICENSE} &nbsp;·&nbsp; <a href="{_REPO_URL}" '
            f'style="color:#89b4fa;">Source on GitHub</a>'
        )
        info_lbl.setOpenExternalLinks(True)
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(info_lbl)

        layout.addStretch()

        # OK button
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bbox.accepted.connect(self.accept)
        layout.addWidget(bbox)
