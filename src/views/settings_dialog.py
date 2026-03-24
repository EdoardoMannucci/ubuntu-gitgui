"""
SettingsDialog — global application preferences.

Two tabs:
    Git      : Read / write global user.name and user.email from ~/.gitconfig.
    General  : Language selector (English / Italiano / Français / Español / Deutsch).

Changes are applied when the user clicks OK:
  • Git fields   → written via ``git config --global``
  • Language     → stored in config.json; a restart is required to apply it.
"""

from __future__ import annotations

import subprocess

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.utils.app_settings import load_settings, save_settings

# ── Supported languages ───────────────────────────────────────────────────────

_LANGUAGES: list[tuple[str, str]] = [
    ("English",    "en"),
    ("Italiano",   "it"),
    ("Français",   "fr"),
    ("Español",    "es"),
    ("Deutsch",    "de"),
]


class SettingsDialog(QDialog):
    """Application preferences dialog (Git + General tabs)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.setMinimumWidth(440)
        self._cfg = load_settings()
        self._build_ui()
        self._populate()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 12, 16, 12)

        tabs = QTabWidget()

        # ── Git tab ───────────────────────────────────────────────
        git_tab = QWidget()
        git_form = QFormLayout(git_tab)
        git_form.setSpacing(10)
        git_form.setContentsMargins(12, 12, 12, 12)

        self._git_name = QLineEdit()
        self._git_name.setPlaceholderText(self.tr("Your Name"))
        git_form.addRow(QLabel(self.tr("Global user.name:")), self._git_name)

        self._git_email = QLineEdit()
        self._git_email.setPlaceholderText(self.tr("you@example.com"))
        git_form.addRow(QLabel(self.tr("Global user.email:")), self._git_email)

        note_git = QLabel(self.tr(
            "These values are written to your global <b>~/.gitconfig</b> "
            "and are used as a fallback when no Profile is active."
        ))
        note_git.setWordWrap(True)
        note_git.setStyleSheet("color: #a6adc8; font-size: 11px;")
        git_form.addRow(note_git)

        tabs.addTab(git_tab, self.tr("Git"))

        # ── General tab ───────────────────────────────────────────
        gen_tab = QWidget()
        gen_form = QFormLayout(gen_tab)
        gen_form.setSpacing(10)
        gen_form.setContentsMargins(12, 12, 12, 12)

        self._lang_combo = QComboBox()
        for label, code in _LANGUAGES:
            self._lang_combo.addItem(label, code)
        gen_form.addRow(QLabel(self.tr("Language:")), self._lang_combo)

        note_lang = QLabel(self.tr(
            "A restart is required for language changes to take effect."
        ))
        note_lang.setWordWrap(True)
        note_lang.setStyleSheet("color: #a6adc8; font-size: 11px;")
        gen_form.addRow(note_lang)

        tabs.addTab(gen_tab, self.tr("General"))

        root.addWidget(tabs)

        # ── Dialog buttons ────────────────────────────────────────
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._on_accept)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)

    def _populate(self) -> None:
        """Fill fields from the current git config and saved settings."""
        self._git_name.setText(self._git_global("user.name"))
        self._git_email.setText(self._git_global("user.email"))

        current_lang = self._cfg.get("language", "en")
        for i, (_, code) in enumerate(_LANGUAGES):
            if code == current_lang:
                self._lang_combo.setCurrentIndex(i)
                break

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        """Write git config values and persist the language preference."""
        name  = self._git_name.text().strip()
        email = self._git_email.text().strip()

        if name:
            self._set_git_global("user.name", name)
        if email:
            self._set_git_global("user.email", email)

        self._cfg["language"] = self._lang_combo.currentData()
        save_settings(self._cfg)
        self.accept()

    # ── Git config helpers ────────────────────────────────────────────

    @staticmethod
    def _git_global(key: str) -> str:
        """Read a value from the global git config. Returns "" on failure."""
        try:
            result = subprocess.run(
                ["git", "config", "--global", key],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    @staticmethod
    def _set_git_global(key: str, value: str) -> None:
        """Write a value to the global git config. Silently ignores errors."""
        try:
            subprocess.run(
                ["git", "config", "--global", key, value],
                capture_output=True, text=True, timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
