"""
CommitDialog — full-featured "Commit Workspace" modal dialog.

Layout:
    ┌──────────────────────┬─────────────────────────────────────────────┐
    │  UNSTAGED (N)        │                                             │
    │  [file list]         │   DIFF VIEWER                               │
    │  [Stage Sel ↑]       │   (syntax highlighted)                      │
    ├──────────────────────┤                                             │
    │  STAGED (N)          │                                             │
    │  [file list]         │                                             │
    │  [Unstage Sel ↓]     │                                             │
    ├──────────────────────┴─────────────────────────────────────────────┤
    │  Summary: [___________________________________________________]    │
    │  Body:    [                                                   ]    │
    │  ✎ Author <email>                    [  Commit Changes  ✓  ]      │
    └────────────────────────────────────────────────────────────────────┘

When the commit succeeds the dialog closes (``accept()``) and emits
``commit_made(short_hash)`` so the caller can refresh the commit graph.
"""

from __future__ import annotations

import git
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.controllers.profile_controller import ProfileController
from src.controllers.staging_controller import FileEntry, FileStatus, StagingController
from src.utils.icons import icon as get_icon
from src.views.diff_viewer import DiffViewerWidget


# ── Status colour palette (Catppuccin Mocha) ─────────────────────────────────

_STATUS_COLORS: dict[FileStatus, str] = {
    FileStatus.MODIFIED:  "#f9e2af",
    FileStatus.ADDED:     "#a6e3a1",
    FileStatus.DELETED:   "#f38ba8",
    FileStatus.RENAMED:   "#89b4fa",
    FileStatus.COPIED:    "#94e2d5",
    FileStatus.UNTRACKED: "#a6adc8",
    FileStatus.CONFLICT:  "#f38ba8",
    FileStatus.UNKNOWN:   "#585b70",
}


class _FileItem(QListWidgetItem):
    """QListWidgetItem carrying a FileEntry with coloured status display."""

    def __init__(self, entry: FileEntry) -> None:
        super().__init__(entry.display)
        self.entry = entry
        self.setForeground(QColor(_STATUS_COLORS.get(entry.status, "#cdd6f4")))


# ── CommitDialog ──────────────────────────────────────────────────────────────

class CommitDialog(QDialog):
    """Modal commit workspace with integrated staging lists and diff viewer.

    After a successful commit the dialog auto-closes and emits ``commit_made``
    with the 7-character short hash.

    Args:
        staging_ctrl: The shared StagingController instance.
        profile_ctrl: The shared ProfileController instance.
        repo_name:    Repository display name shown in the title bar.
        parent:       Optional Qt parent widget.
    """

    commit_made = pyqtSignal(str)   # 7-char short hash of the new commit

    def __init__(
        self,
        staging_ctrl: StagingController,
        profile_ctrl: ProfileController,
        repo_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._staging = staging_ctrl
        self._profile = profile_ctrl

        title = f"Commit Workspace — {repo_name}" if repo_name else "Commit Workspace"
        self.setWindowTitle(title)
        self.setMinimumSize(900, 620)
        self.resize(1060, 700)

        # Live-refresh staging lists whenever the index changes
        self._staging.status_changed.connect(self._refresh_lists)

        self._build_ui()
        self._refresh_lists()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top area: staging panel (left) | diff viewer (right)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(self._build_staging_panel())
        top_splitter.addWidget(self._build_diff_panel())
        top_splitter.setSizes([340, 720])
        root.addWidget(top_splitter, stretch=1)

        # Bottom area: commit form
        root.addWidget(self._build_commit_form())

    def _build_staging_panel(self) -> QWidget:
        """Left panel: unstaged + staged file lists with stage/unstage buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        list_splitter = QSplitter(Qt.Orientation.Vertical)
        list_splitter.setChildrenCollapsible(False)
        list_splitter.addWidget(self._build_unstaged_section())
        list_splitter.addWidget(self._build_staged_section())
        list_splitter.setSizes([280, 220])

        layout.addWidget(list_splitter)
        return container

    def _build_unstaged_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._unstaged_label = QLabel("UNSTAGED (0)")
        self._unstaged_label.setObjectName("section_title")
        header.addWidget(self._unstaged_label)
        header.addStretch()
        self._stage_all_btn = QPushButton("Stage All")
        self._stage_all_btn.setIcon(get_icon("stage_all"))
        self._stage_all_btn.setObjectName("accent_btn")
        self._stage_all_btn.setFixedHeight(24)
        self._stage_all_btn.setEnabled(False)
        self._stage_all_btn.clicked.connect(self._on_stage_all)
        header.addWidget(self._stage_all_btn)
        layout.addLayout(header)

        self._unstaged_list = QListWidget()
        self._unstaged_list.setObjectName("file_list")
        self._unstaged_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._unstaged_list.setSortingEnabled(False)
        self._unstaged_list.itemSelectionChanged.connect(self._on_unstaged_selection_changed)
        self._unstaged_list.itemClicked.connect(
            lambda item: self._diff_viewer.show_diff(item.entry.path, False)  # type: ignore[attr-defined]
        )
        layout.addWidget(self._unstaged_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._stage_sel_btn = QPushButton("Stage Selected")
        self._stage_sel_btn.setIcon(get_icon("stage_sel"))
        self._stage_sel_btn.setEnabled(False)
        self._stage_sel_btn.clicked.connect(self._on_stage_selected)
        btn_row.addWidget(self._stage_sel_btn)
        layout.addLayout(btn_row)

        return container

    def _build_staged_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._staged_label = QLabel("STAGED (0)")
        self._staged_label.setObjectName("section_title")
        header.addWidget(self._staged_label)
        header.addStretch()
        self._unstage_all_btn = QPushButton("Unstage All")
        self._unstage_all_btn.setIcon(get_icon("unstage_all"))
        self._unstage_all_btn.setFixedHeight(24)
        self._unstage_all_btn.setEnabled(False)
        self._unstage_all_btn.clicked.connect(self._on_unstage_all)
        header.addWidget(self._unstage_all_btn)
        layout.addLayout(header)

        self._staged_list = QListWidget()
        self._staged_list.setObjectName("file_list")
        self._staged_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._staged_list.setSortingEnabled(False)
        self._staged_list.itemSelectionChanged.connect(self._on_staged_selection_changed)
        self._staged_list.itemClicked.connect(
            lambda item: self._diff_viewer.show_diff(item.entry.path, True)  # type: ignore[attr-defined]
        )
        layout.addWidget(self._staged_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._unstage_sel_btn = QPushButton("Unstage Selected")
        self._unstage_sel_btn.setIcon(get_icon("unstage_sel"))
        self._unstage_sel_btn.setEnabled(False)
        self._unstage_sel_btn.clicked.connect(self._on_unstage_selected)
        btn_row.addWidget(self._unstage_sel_btn)
        layout.addLayout(btn_row)

        return container

    def _build_diff_panel(self) -> QWidget:
        """Right panel: DiffViewerWidget (reuses the shared StagingController)."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._diff_viewer = DiffViewerWidget(staging_ctrl=self._staging)
        layout.addWidget(self._diff_viewer)
        return container

    def _build_commit_form(self) -> QWidget:
        """Bottom strip: commit title, optional body, author info, commit button."""
        container = QWidget()
        container.setObjectName("commit_form")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        # Summary (single-line title)
        summary_row = QHBoxLayout()
        lbl = QLabel("Summary:")
        lbl.setFixedWidth(64)
        summary_row.addWidget(lbl)
        self._summary_edit = QLineEdit()
        self._summary_edit.setPlaceholderText(
            "Short commit title  (≤ 72 characters)"
        )
        self._summary_edit.textChanged.connect(self._refresh_commit_button)
        summary_row.addWidget(self._summary_edit)
        layout.addLayout(summary_row)

        # Body (optional multi-line description)
        self._body_edit = QTextEdit()
        self._body_edit.setPlaceholderText(
            "Optional longer description…\n\n"
            "Leave blank for a single-line commit message."
        )
        self._body_edit.setFixedHeight(72)
        layout.addWidget(self._body_edit)

        # Author label + Commit button
        action_row = QHBoxLayout()

        self._author_label = QLabel()
        self._author_label.setObjectName("author_label")
        action_row.addWidget(self._author_label)
        action_row.addStretch()

        self._commit_btn = QPushButton("  Commit Changes")
        self._commit_btn.setIcon(get_icon("commit"))
        self._commit_btn.setObjectName("accent_btn")
        self._commit_btn.setEnabled(False)
        self._commit_btn.setMinimumWidth(160)
        self._commit_btn.setMinimumHeight(34)
        self._commit_btn.clicked.connect(self._on_commit)
        action_row.addWidget(self._commit_btn)

        layout.addLayout(action_row)
        return container

    # ── Refresh helpers ───────────────────────────────────────────────

    def _refresh_lists(self) -> None:
        """Reload staging lists from the controller and update UI state."""
        self._populate_list(self._unstaged_list, self._staging.get_unstaged())
        self._populate_list(self._staged_list,   self._staging.get_staged())
        self._unstaged_label.setText(f"UNSTAGED ({self._unstaged_list.count()})")
        self._staged_label.setText(f"STAGED ({self._staged_list.count()})")
        self._refresh_buttons()
        self._refresh_author_label()

    def _populate_list(
        self, list_widget: QListWidget, entries: list[FileEntry]
    ) -> None:
        """Rebuild *list_widget*, preserving previously selected paths."""
        selected_paths: set[str] = {
            item.entry.path  # type: ignore[attr-defined]
            for item in list_widget.selectedItems()
        }
        list_widget.clear()
        for entry in entries:
            item = _FileItem(entry)
            list_widget.addItem(item)
            if entry.path in selected_paths:
                item.setSelected(True)

    def _refresh_buttons(self) -> None:
        has_repo     = self._staging.has_repo
        has_unstaged = self._unstaged_list.count() > 0
        has_staged   = self._staged_list.count() > 0
        self._stage_all_btn.setEnabled(has_repo and has_unstaged)
        self._unstage_all_btn.setEnabled(has_repo and has_staged)
        self._stage_sel_btn.setEnabled(
            has_repo and len(self._unstaged_list.selectedItems()) > 0
        )
        self._unstage_sel_btn.setEnabled(
            has_repo and len(self._staged_list.selectedItems()) > 0
        )
        self._refresh_commit_button()

    def _refresh_commit_button(self) -> None:
        has_staged  = self._staged_list.count() > 0
        has_summary = bool(self._summary_edit.text().strip())
        self._commit_btn.setEnabled(
            self._staging.has_repo and has_staged and has_summary
        )

    def _refresh_author_label(self) -> None:
        profile = self._profile.active_profile
        if profile:
            self._author_label.setText(
                f"\u270e  {profile.git_name} <{profile.git_email}>"
            )
        else:
            self._author_label.setText(
                "\u26a0  No active profile \u2014 using git config"
            )

    # ── Staging operations ────────────────────────────────────────────

    def _on_stage_selected(self) -> None:
        paths = [
            item.entry.path  # type: ignore[attr-defined]
            for item in self._unstaged_list.selectedItems()
        ]
        if not paths:
            return
        try:
            self._staging.stage(paths)
        except git.GitCommandError as exc:
            QMessageBox.warning(self, "Stage Failed", str(exc))

    def _on_stage_all(self) -> None:
        try:
            self._staging.stage_all()
        except git.GitCommandError as exc:
            QMessageBox.warning(self, "Stage All Failed", str(exc))

    def _on_unstage_selected(self) -> None:
        paths = [
            item.entry.path  # type: ignore[attr-defined]
            for item in self._staged_list.selectedItems()
        ]
        if not paths:
            return
        try:
            self._staging.unstage(paths)
        except git.GitCommandError as exc:
            QMessageBox.warning(self, "Unstage Failed", str(exc))

    def _on_unstage_all(self) -> None:
        try:
            self._staging.unstage_all()
        except git.GitCommandError as exc:
            QMessageBox.warning(self, "Unstage All Failed", str(exc))

    def _on_unstaged_selection_changed(self) -> None:
        self._stage_sel_btn.setEnabled(
            self._staging.has_repo
            and len(self._unstaged_list.selectedItems()) > 0
        )

    def _on_staged_selection_changed(self) -> None:
        self._unstage_sel_btn.setEnabled(
            self._staging.has_repo
            and len(self._staged_list.selectedItems()) > 0
        )

    # ── Commit ────────────────────────────────────────────────────────

    def _on_commit(self) -> None:
        """Gather identity, build message, and execute the commit."""
        summary = self._summary_edit.text().strip()
        if not summary:
            QMessageBox.warning(self, "Empty Summary", "Please enter a commit summary.")
            return

        body = self._body_edit.toPlainText().strip()
        message = f"{summary}\n\n{body}" if body else summary

        # Resolve author identity: active profile → git config fallback
        profile = self._profile.active_profile
        if profile:
            git_name  = profile.git_name
            git_email = profile.git_email
        else:
            try:
                repo = self._staging._repo  # type: ignore[attr-defined]
                with repo.config_reader() as cfg:
                    git_name  = cfg.get_value("user", "name",  "Unknown")
                    git_email = cfg.get_value("user", "email", "unknown@unknown")
            except Exception:  # noqa: BLE001
                git_name, git_email = "Unknown", "unknown@unknown"

        try:
            short_hash = self._staging.commit(message, git_name, git_email)
            self.commit_made.emit(short_hash)
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Commit Cancelled", str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(self, "Commit Failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Commit Error", str(exc))

    # ── Cleanup ───────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Disconnect from StagingController to avoid dangling signal calls."""
        try:
            self._staging.status_changed.disconnect(self._refresh_lists)
        except RuntimeError:
            pass
        super().closeEvent(event)
