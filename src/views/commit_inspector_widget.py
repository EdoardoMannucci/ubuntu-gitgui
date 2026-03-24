"""
CommitInspectorWidget — details panel for the selected commit.

Shown below the commit graph as the bottom half of the central vertical
splitter.  When the user selects a commit row (click or keyboard arrows),
this widget populates with:

    • Commit metadata: hash, author, date
    • Full commit message (may be multi-line)
    • List of files changed in that commit

Clicking a file in the list emits ``file_selected`` so that the Diff Viewer
(right panel) can display the ``git show`` diff for that file.

Signals:
    file_selected(full_hash: str, path: str) — user clicked a file in the list.
"""

from __future__ import annotations

import git
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.commit_graph import CommitData


class CommitInspectorWidget(QWidget):
    """Panel that shows metadata and changed files of the selected commit."""

    file_selected = pyqtSignal(str, str)   # (full_hash, repo-relative path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_commit: CommitData | None = None
        self._repo: git.Repo | None = None
        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────

    def set_repo(self, repo: git.Repo | None) -> None:
        """Attach or detach the live Repo instance used for fetching details."""
        self._repo = repo
        if repo is None:
            self.clear()

    def show_commit(self, commit: CommitData) -> None:
        """Populate the panel with data for *commit*."""
        self._current_commit = commit

        # Metadata row
        self._hash_label.setText(f"<b>Hash:</b> {commit.full_hash}")
        self._author_label.setText(
            f"<b>Author:</b> {commit.author}   <b>Date:</b> {commit.date}"
        )

        # Full message (fetched directly from GitPython)
        self._message_edit.setPlainText(self._fetch_full_message(commit.full_hash))

        # Changed files
        self._file_list.clear()
        for path in self._fetch_changed_files(commit.full_hash):
            self._file_list.addItem(QListWidgetItem(path))

    def clear(self) -> None:
        """Reset to the empty/placeholder state."""
        self._current_commit = None
        self._hash_label.setText("")
        self._author_label.setText("")
        self._message_edit.clear()
        self._file_list.clear()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)

        # Section title
        title = QLabel("COMMIT INSPECTOR")
        title.setObjectName("section_title")
        root.addWidget(title)

        # Horizontal splitter: left = metadata + message | right = file list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left: metadata labels + full message ──────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(3)

        self._hash_label = QLabel()
        self._hash_label.setObjectName("commit_details_label")
        self._hash_label.setTextFormat(Qt.TextFormat.RichText)
        self._hash_label.setWordWrap(True)
        left_layout.addWidget(self._hash_label)

        self._author_label = QLabel()
        self._author_label.setObjectName("commit_details_label")
        self._author_label.setTextFormat(Qt.TextFormat.RichText)
        self._author_label.setWordWrap(True)
        left_layout.addWidget(self._author_label)

        self._message_edit = QTextEdit()
        self._message_edit.setObjectName("commit_msg_edit")
        self._message_edit.setReadOnly(True)
        self._message_edit.setPlaceholderText("Select a commit to see its message.")
        left_layout.addWidget(self._message_edit, stretch=1)

        splitter.addWidget(left)

        # ── Right: changed-files list ─────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(3)

        files_title = QLabel("CHANGED FILES")
        files_title.setObjectName("section_title")
        right_layout.addWidget(files_title)

        self._file_list = QListWidget()
        self._file_list.setObjectName("file_list")
        self._file_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._file_list.itemClicked.connect(self._on_file_clicked)
        right_layout.addWidget(self._file_list, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([600, 280])

        root.addWidget(splitter, stretch=1)

    # ── Private helpers ───────────────────────────────────────────────

    def _fetch_full_message(self, full_hash: str) -> str:
        """Return the full (multi-line) message of *full_hash*."""
        if self._repo is None:
            return ""
        try:
            return self._repo.commit(full_hash).message.strip()
        except Exception:  # noqa: BLE001
            return ""

    def _fetch_changed_files(self, full_hash: str) -> list[str]:
        """Return repo-relative paths of files touched by *full_hash*."""
        if self._repo is None:
            return []
        try:
            commit = self._repo.commit(full_hash)
            return sorted(commit.stats.files.keys())
        except Exception:  # noqa: BLE001
            return []

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_file_clicked(self, item: QListWidgetItem) -> None:
        """Forward the selected file to the Diff Viewer via file_selected."""
        if self._current_commit is None:
            return
        self.file_selected.emit(self._current_commit.full_hash, item.text())
