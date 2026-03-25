"""
CloneDialog — modal QDialog for cloning a remote repository.

Fields:
  - Repository URL  (text input)
  - Destination     (text input + "Browse…" button → QFileDialog for parent dir)

The dialog computes the final clone path as:
    <destination_dir> / <repo_name_from_url>

and exposes it via the ``clone_url`` and ``clone_destination`` properties
after the dialog is accepted.
"""

import re
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _repo_name_from_url(url: str) -> str:
    """Extract a repository directory name from a clone URL.

    Examples:
        https://github.com/user/myrepo.git  →  myrepo
        git@github.com:user/myrepo.git      →  myrepo
        /local/path/myrepo                  →  myrepo
    """
    # Strip trailing slashes and .git suffix
    name = re.sub(r"\.git$", "", url.rstrip("/"))
    # Take the last path segment (works for both / and : separators)
    name = re.split(r"[/:]", name)[-1]
    return name or "repository"


class CloneDialog(QDialog):
    """Ask the user for a remote URL and a local parent directory.

    Args:
        ssh_key_path: Absolute path of the SSH key that will be used for the
                      clone (from the active identity profile).  Shown
                      informatively in the dialog; empty string means the
                      system default will be used.
    """

    def __init__(
        self,
        ssh_key_path: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ssh_key_path = ssh_key_path
        self.setWindowTitle("Clone Repository")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # URL field
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://github.com/user/repo.git  or  git@…")
        self._url_input.textChanged.connect(self._update_preview)
        form.addRow("Repository URL:", self._url_input)

        # Destination directory row
        dest_row = QHBoxLayout()
        self._dest_input = QLineEdit()
        self._dest_input.setPlaceholderText(str(Path.home()))
        self._dest_input.textChanged.connect(self._update_preview)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_destination)
        dest_row.addWidget(self._dest_input)
        dest_row.addWidget(browse_btn)
        form.addRow("Clone into:", dest_row)

        root.addLayout(form)

        # SSH key info label — only shown when a profile key is active
        if self._ssh_key_path:
            key_label = QLabel(
                f"SSH key in use:  <code>{self._ssh_key_path}</code><br>"
                "(from active identity profile)"
            )
            key_label.setWordWrap(True)
            key_label.setStyleSheet("color: #aba9be; font-size: 11px;")
            root.addWidget(key_label)

        # Preview label: shows the full resulting path
        self._preview_label = QLabel()
        self._preview_label.setObjectName("clone_preview_label")
        self._preview_label.setWordWrap(True)
        root.addWidget(self._preview_label)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Clone")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_preview()

    # ── Slots ─────────────────────────────────────────────────────────

    def _browse_destination(self) -> None:
        """Open a folder picker to select the parent directory."""
        start = self._dest_input.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select Destination Folder", start)
        if chosen:
            self._dest_input.setText(chosen)

    def _update_preview(self) -> None:
        """Refresh the preview label with the computed destination path."""
        url = self._url_input.text().strip()
        dest_dir = self._dest_input.text().strip() or str(Path.home())

        if url:
            repo_name = _repo_name_from_url(url)
            full_path = str(Path(dest_dir) / repo_name)
            self._preview_label.setText(f"Will clone into:  <code>{full_path}</code>")
        else:
            self._preview_label.setText("")

    def _on_accept(self) -> None:
        """Validate before closing."""
        if not self._url_input.text().strip():
            QMessageBox.warning(self, "Validation", "Please enter a repository URL.")
            return
        dest = self._dest_input.text().strip() or str(Path.home())
        if not Path(dest).is_dir():
            QMessageBox.warning(
                self,
                "Validation",
                f"The destination directory does not exist:\n{dest}",
            )
            return
        self.accept()

    # ── Result accessors ──────────────────────────────────────────────

    @property
    def clone_url(self) -> str:
        """The URL entered by the user."""
        return self._url_input.text().strip()

    @property
    def clone_destination(self) -> str:
        """The full computed destination path (parent_dir/repo_name)."""
        dest_dir = self._dest_input.text().strip() or str(Path.home())
        repo_name = _repo_name_from_url(self.clone_url)
        return str(Path(dest_dir) / repo_name)
