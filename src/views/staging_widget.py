"""
StagingWidget — the top-right panel showing unstaged files and staged files.

Layout (vertical, two sections + footer button):
    ┌────────────────────────────────────────┐
    │ UNSTAGED (N)          [Stage All ↓]    │
    │ ┌──────────────────────────────────┐   │
    │ │ M  modified_file.py              │   │  ← QListWidget
    │ │ ?  untracked.txt                 │   │
    │ └──────────────────────────────────┘   │
    │              [↑ Stage Selected]         │
    ├────────────────────────────────────────┤
    │ STAGED (N)          [Unstage All ↑]    │
    │ ┌──────────────────────────────────┐   │
    │ │ A  new_feature.py                │   │  ← QListWidget
    │ └──────────────────────────────────┘   │
    │              [↓ Unstage Selected]       │
    ├────────────────────────────────────────┤
    │         [  Commit Changes…  ✓  ]       │
    └────────────────────────────────────────┘

The commit message inputs have been moved to CommitDialog (opened by the
footer button).  All git operations are still delegated to StagingController.

Signals:
    file_selected(path: str, is_staged: bool) — file clicked for diff view
    open_commit_dialog_requested()             — "Commit Changes…" button clicked
"""

from __future__ import annotations

import git
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.controllers.profile_controller import ProfileController
from src.controllers.staging_controller import FileEntry, FileStatus, StagingController
from src.utils.icons import icon as get_icon


# ── Status-type colour palette (Catppuccin Mocha) ────────────────────────────

_STATUS_COLORS: dict[FileStatus, str] = {
    FileStatus.MODIFIED:  "#f9e2af",   # yellow
    FileStatus.ADDED:     "#a6e3a1",   # green
    FileStatus.DELETED:   "#f38ba8",   # red
    FileStatus.RENAMED:   "#89b4fa",   # blue
    FileStatus.COPIED:    "#94e2d5",   # teal
    FileStatus.UNTRACKED: "#a6adc8",   # subtext (grey)
    FileStatus.CONFLICT:  "#f38ba8",   # red — merge conflict
    FileStatus.UNKNOWN:   "#585b70",   # overlay (dark grey)
}


# ── Custom list item ──────────────────────────────────────────────────────────

class _FileItem(QListWidgetItem):
    """QListWidgetItem that carries a FileEntry and renders coloured status."""

    def __init__(self, entry: FileEntry) -> None:
        super().__init__(entry.display)
        self.entry = entry
        color_hex = _STATUS_COLORS.get(entry.status, "#cdd6f4")
        self.setForeground(QColor(color_hex))


# ── StagingWidget ─────────────────────────────────────────────────────────────

class StagingWidget(QWidget):
    """Staging-area panel: unstaged list, staged list, and commit launcher."""

    # Emitted when the user clicks a file (for the diff viewer)
    file_selected = pyqtSignal(str, bool)  # (repo-relative path, is_staged)

    # Emitted when the user clicks "Commit Changes…"
    open_commit_dialog_requested = pyqtSignal()

    def __init__(
        self,
        staging_ctrl: StagingController,
        profile_ctrl: ProfileController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._staging = staging_ctrl
        self._profile = profile_ctrl

        # Connect controller signal → view refresh
        self._staging.status_changed.connect(self.refresh)

        self._build_ui()
        self.refresh()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Vertical splitter: unstaged | staged ──────────────────
        list_splitter = QSplitter(Qt.Orientation.Vertical)
        list_splitter.setChildrenCollapsible(False)

        list_splitter.addWidget(self._build_unstaged_section())
        list_splitter.addWidget(self._build_staged_section())
        list_splitter.setSizes([200, 160])

        root.addWidget(list_splitter, stretch=1)

        # ── Footer: prominent "Commit Changes…" launcher button ───
        footer = QWidget()
        footer.setObjectName("commit_footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 8, 8, 8)

        self._commit_changes_btn = QPushButton("  Commit Changes\u2026")
        self._commit_changes_btn.setIcon(get_icon("commit"))
        self._commit_changes_btn.setObjectName("accent_btn")
        self._commit_changes_btn.setMinimumHeight(36)
        self._commit_changes_btn.setEnabled(False)
        self._commit_changes_btn.clicked.connect(self.open_commit_dialog_requested)
        footer_layout.addWidget(self._commit_changes_btn)

        root.addWidget(footer)

    def _build_unstaged_section(self) -> QWidget:
        """Unstaged-files list with header and staging buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        # Header row: title + "Stage All" button
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

        # File list
        self._unstaged_list = QListWidget()
        self._unstaged_list.setObjectName("file_list")
        self._unstaged_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._unstaged_list.setSortingEnabled(False)
        self._unstaged_list.itemSelectionChanged.connect(self._on_unstaged_selection_changed)
        self._unstaged_list.itemClicked.connect(
            lambda item: self.file_selected.emit(item.entry.path, False)  # type: ignore[attr-defined]
        )
        layout.addWidget(self._unstaged_list, stretch=1)

        # "Stage Selected" button (right-aligned)
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
        """Staged-files list with header and unstaging buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # Header row: title + "Unstage All" button
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

        # File list
        self._staged_list = QListWidget()
        self._staged_list.setObjectName("file_list")
        self._staged_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._staged_list.setSortingEnabled(False)
        self._staged_list.itemSelectionChanged.connect(self._on_staged_selection_changed)
        self._staged_list.itemClicked.connect(
            lambda item: self.file_selected.emit(item.entry.path, True)  # type: ignore[attr-defined]
        )
        layout.addWidget(self._staged_list, stretch=1)

        # "Unstage Selected" button (right-aligned)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._unstage_sel_btn = QPushButton("Unstage Selected")
        self._unstage_sel_btn.setIcon(get_icon("unstage_sel"))
        self._unstage_sel_btn.setEnabled(False)
        self._unstage_sel_btn.clicked.connect(self._on_unstage_selected)
        btn_row.addWidget(self._unstage_sel_btn)
        layout.addLayout(btn_row)

        return container

    # ── Public API ────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload both file lists from the controller and update button states."""
        self._populate_list(
            self._unstaged_list,
            self._staging.get_unstaged(),
        )
        self._populate_list(
            self._staged_list,
            self._staging.get_staged(),
        )
        self._refresh_counts()
        self._refresh_buttons()

    # ── Private helpers ───────────────────────────────────────────────

    def _populate_list(
        self, list_widget: QListWidget, entries: list[FileEntry]
    ) -> None:
        """Rebuild *list_widget* from *entries*, preserving selection where possible."""
        previously_selected: set[str] = {
            item.entry.path  # type: ignore[attr-defined]
            for item in list_widget.selectedItems()
        }
        list_widget.clear()
        for entry in entries:
            item = _FileItem(entry)
            list_widget.addItem(item)
            if entry.path in previously_selected:
                item.setSelected(True)

    def _refresh_counts(self) -> None:
        """Update the section-header count labels."""
        self._unstaged_label.setText(
            f"UNSTAGED ({self._unstaged_list.count()})"
        )
        self._staged_label.setText(
            f"STAGED ({self._staged_list.count()})"
        )

    def _refresh_buttons(self) -> None:
        """Enable/disable action buttons based on list contents and selection."""
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
        # "Commit Changes…" is available as long as a repo is open
        self._commit_changes_btn.setEnabled(has_repo)

    # ── Slots: staging operations ─────────────────────────────────────

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

    # ── Selection change slots (update button enabled state) ──────────

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
