"""
StagingWidget — the top-right panel showing unstaged files, staged files,
and the commit form.

Layout (vertical, three sections):
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
    │ Commit message                         │
    │ ┌──────────────────────────────────┐   │
    │ │                                  │   │  ← QPlainTextEdit
    │ └──────────────────────────────────┘   │
    │                         [Commit ✓]     │
    └────────────────────────────────────────┘

The widget is purely presentational: all git operations are delegated to
StagingController.  A ProfileController reference is used only at commit time
to resolve the active author identity.

Signal emitted for Phase 6 integration:
    file_selected(path: str, is_staged: bool)
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
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
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
    """Full staging-area panel: unstaged list, staged list, commit form."""

    # Emitted when the user clicks a file (for the Phase 6 diff viewer)
    file_selected = pyqtSignal(str, bool)  # (repo-relative path, is_staged)

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
        self._staging.commit_made.connect(self._on_commit_made)

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
        list_splitter.setSizes([200, 160])  # unstaged slightly taller by default

        root.addWidget(list_splitter, stretch=1)

        # ── Commit area (fixed at bottom) ─────────────────────────
        root.addWidget(self._build_commit_section())

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

    def _build_commit_section(self) -> QWidget:
        """Commit message text area + Commit button."""
        container = QWidget()
        container.setObjectName("commit_area")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)

        msg_label = QLabel("COMMIT MESSAGE")
        msg_label.setObjectName("section_title")
        layout.addWidget(msg_label)

        self._commit_msg = QPlainTextEdit()
        self._commit_msg.setObjectName("commit_msg_edit")
        self._commit_msg.setPlaceholderText(
            "Summarize your changes (≤ 72 chars on first line)\n\n"
            "Optional: longer description after a blank line."
        )
        self._commit_msg.setFixedHeight(80)
        self._commit_msg.textChanged.connect(self._refresh_commit_button)
        layout.addWidget(self._commit_msg)

        # Bottom row: profile indicator + Commit button
        action_row = QHBoxLayout()

        self._author_label = QLabel()
        self._author_label.setObjectName("author_label")
        action_row.addWidget(self._author_label)
        action_row.addStretch()

        self._commit_btn = QPushButton("Commit")
        self._commit_btn.setIcon(get_icon("commit"))
        self._commit_btn.setObjectName("accent_btn")
        self._commit_btn.setEnabled(False)
        self._commit_btn.setFixedWidth(110)
        self._commit_btn.clicked.connect(self._on_commit)
        action_row.addWidget(self._commit_btn)

        layout.addLayout(action_row)
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
        self._refresh_author_label()

    # ── Private helpers ───────────────────────────────────────────────

    def _populate_list(
        self, list_widget: QListWidget, entries: list[FileEntry]
    ) -> None:
        """Rebuild *list_widget* from *entries*, preserving selection where possible."""
        # Preserve the paths that were selected so we can restore selection
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
        self._refresh_commit_button()

    def _refresh_commit_button(self) -> None:
        """Commit button is enabled only when there are staged files AND a message."""
        has_staged  = self._staged_list.count() > 0
        has_message = bool(self._commit_msg.toPlainText().strip())
        self._commit_btn.setEnabled(
            self._staging.has_repo and has_staged and has_message
        )

    def _refresh_author_label(self) -> None:
        """Show the active profile name/email that will be used for the next commit."""
        profile = self._profile.active_profile
        if profile:
            self._author_label.setText(
                f"✎  {profile.git_name} <{profile.git_email}>"
            )
        else:
            self._author_label.setText("⚠  No active profile — using git config")

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

    # ── Slots: commit ─────────────────────────────────────────────────

    def _on_commit(self) -> None:
        """Gather identity from the active profile and execute the commit."""
        message = self._commit_msg.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "Empty Message", "Please enter a commit message.")
            return

        # Resolve author identity: active profile → git config fallback
        profile = self._profile.active_profile
        if profile:
            git_name  = profile.git_name
            git_email = profile.git_email
        else:
            # Read from the repo's git config (local → global → system)
            try:
                repo = self._staging._repo  # type: ignore[attr-defined]
                with repo.config_reader() as cfg:
                    git_name  = cfg.get_value("user", "name",  "Unknown")
                    git_email = cfg.get_value("user", "email", "unknown@unknown")
            except Exception:
                git_name, git_email = "Unknown", "unknown@unknown"

        try:
            short_hash = self._staging.commit(message, git_name, git_email)
            self._commit_msg.clear()
            # Refresh will be triggered by staging_ctrl.status_changed signal
        except ValueError as exc:
            QMessageBox.warning(self, "Commit Cancelled", str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(self, "Commit Failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Commit Error", str(exc))

    def _on_commit_made(self, short_hash: str) -> None:
        """Show a brief success notification in the author label."""
        self._author_label.setText(f"✓  Committed {short_hash}")

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
