"""
SidebarWidget — left-panel tree showing local branches, remote branches and tags.

Hierarchy rendered:
    REPOSITORY NAME
    ├── Local Branches
    │   ├── ✔ main          ← active branch (bold + check mark)
    │   └──   develop
    ├── Remote Branches
    │   ├── origin/main
    │   └── origin/develop
    └── Tags
        └── v1.0.0

Interactions:
  - Double-click a local branch  → request checkout via checkout_requested signal
  - Single-click any item        → no action (selection only)
  - Right-click (future phases)  → context menu

The widget is intentionally decoupled from the controller:
  - MainWindow provides data via `populate()` and connects the signal.
  - Checkout itself is done by RepositoryController after receiving the signal.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from src.utils.icons import icon as get_icon


# ── Internal constants ────────────────────────────────────────────────────────

_SECTION_LOCAL = "Local Branches"
_SECTION_REMOTE = "Remote Branches"
_SECTION_TAGS = "Tags"
_SECTION_SUBMODULES = "Submodules"

# Unicode check mark shown next to the active branch
_ACTIVE_MARKER = "✔ "
_INACTIVE_MARKER = "   "


class SidebarWidget(QTreeWidget):
    """QTreeWidget subclass that displays Git refs and emits checkout requests.

    Signals:
        checkout_requested(branch_name: str): emitted when the user double-clicks
            a local branch item.  The branch name is the raw Git branch name
            (no decoration).
    """

    checkout_requested         = pyqtSignal(str)
    checkout_remote_requested  = pyqtSignal(str)      # remote ref (e.g. "origin/feature")
    checkout_tag_requested     = pyqtSignal(str)      # tag name
    merge_requested            = pyqtSignal(str, str) # (source, target)
    delete_branch_requested    = pyqtSignal(str)
    rename_branch_requested    = pyqtSignal(str, str) # (old_name, new_name)
    delete_tag_requested       = pyqtSignal(str)      # tag name
    push_tag_requested         = pyqtSignal(str)      # tag name
    create_branch_from_tag_requested = pyqtSignal(str, str)  # (tag name, branch name)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar_tree")
        self.setHeaderLabel("NO REPOSITORY")
        self.setAnimated(True)
        self.setIndentation(14)
        self.setUniformRowHeights(True)

        # Only items (leaves) are selectable, not section headers
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)

        # Enable drag & drop: local branches can be dragged onto other local branches
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

        # Right-click context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # Double-click triggers checkout for local branches
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._active_branch: str = ""
        self._show_empty_state()

    # ── Public API ────────────────────────────────────────────────────

    def populate(
        self,
        repo_name: str,
        local_branches: list[str],
        remote_branches: list[str],
        tags: list[str],
        submodules: list[str],
        active_branch: str,
    ) -> None:
        """Rebuild the entire tree from the provided ref lists.

        Call this whenever the repository is opened or the ref list changes
        (e.g. after a fetch or checkout).

        Args:
            repo_name:       Display name shown in the header (usually the folder name).
            local_branches:  Sorted list of local branch names.
            remote_branches: Sorted list of remote-tracking ref names.
            tags:            Sorted list of tag names.
            active_branch:   The currently checked-out branch name.
        """
        self._active_branch = active_branch
        self.clear()
        self.setHeaderLabel(repo_name.upper())

        self._add_section(_SECTION_LOCAL, local_branches, is_local=True)
        self._add_section(_SECTION_REMOTE, remote_branches, is_local=False)
        self._add_section(_SECTION_TAGS, tags, is_local=False)
        self._add_section(_SECTION_SUBMODULES, submodules, is_local=False)

    def refresh_active_branch(self, new_branch: str) -> None:
        """Update the visual highlight after a checkout without a full repopulate.

        Iterates over the Local Branches section and updates text/font in-place,
        which avoids collapsing expanded sections.

        Args:
            new_branch: The name of the branch that is now active.
        """
        old_branch = self._active_branch
        self._active_branch = new_branch

        local_section = self._find_section(_SECTION_LOCAL)
        if local_section is None:
            return

        for i in range(local_section.childCount()):
            child = local_section.child(i)
            if child is None:
                continue
            raw_name = child.data(0, Qt.ItemDataRole.UserRole)
            if raw_name in (old_branch, new_branch):
                self._style_branch_item(child, raw_name)

    def clear_to_empty_state(self) -> None:
        """Reset the sidebar to its no-repository placeholder state."""
        self.clear()
        self.setHeaderLabel("NO REPOSITORY")
        self._show_empty_state()

    # ── Private helpers ───────────────────────────────────────────────

    def _show_empty_state(self) -> None:
        """Add a single disabled placeholder item when no repo is open."""
        placeholder = QTreeWidgetItem(self, ["Open a repository to get started"])
        placeholder.setDisabled(True)
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)

    def _add_section(
        self, title: str, items: list[str], *, is_local: bool
    ) -> QTreeWidgetItem:
        """Create a non-selectable section header and populate it with leaf items.

        Args:
            title:    Section label (e.g. "Local Branches").
            items:    List of ref names to add as children.
            is_local: True only for the local-branches section (enables checkout
                      double-click and active-branch highlighting).

        Returns:
            The section QTreeWidgetItem (always expanded).
        """
        section = QTreeWidgetItem(self, [title])
        section.setExpanded(True)
        section.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable

        # Style the section header
        header_font = QFont()
        header_font.setPointSize(10)
        header_font.setWeight(QFont.Weight.Medium)
        section.setFont(0, header_font)
        section.setForeground(0, __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#a6adc8"))

        if not items:
            empty = QTreeWidgetItem(section, ["  (none)"])
            empty.setDisabled(True)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            return section

        for name in items:
            child = QTreeWidgetItem(section)
            # Store the raw branch/tag name for later retrieval without parsing the label
            child.setData(0, Qt.ItemDataRole.UserRole, name)

            if is_local:
                self._style_branch_item(child, name)
                # Mark local branches so double-click and DnD handlers can identify them
                child.setData(0, Qt.ItemDataRole.UserRole + 1, "local")
                # Allow local branches to be dragged and to accept drops
                child.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
            elif title == _SECTION_REMOTE:
                child.setText(0, f"  {name}")
                # Mark remote branches so double-click handler can offer checkout
                child.setData(0, Qt.ItemDataRole.UserRole + 1, "remote")
            elif title == _SECTION_TAGS:
                child.setText(0, f"  {name}")
                child.setData(0, Qt.ItemDataRole.UserRole + 1, "tag")
            else:
                child.setText(0, f"  {name}")

        return section

    def _style_branch_item(self, item: QTreeWidgetItem, branch_name: str) -> None:
        """Apply the correct visual style to a local branch item.

        Active branch: bold font, check-mark prefix.
        Other branches: normal font, indented prefix.
        """
        is_active = (branch_name == self._active_branch)

        font = QFont()
        font.setBold(is_active)
        item.setFont(0, font)

        prefix = _ACTIVE_MARKER if is_active else _INACTIVE_MARKER
        item.setText(0, f"{prefix}{branch_name}")

        if is_active:
            item.setForeground(
                0, __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#89b4fa")
            )
        else:
            item.setForeground(
                0, __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#cdd6f4")
            )

    def _find_section(self, title: str) -> QTreeWidgetItem | None:
        """Find a top-level section item by its title text."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item and item.text(0) == title:
                return item
        return None

    # ── Event handlers ────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Emit checkout_requested (local) or checkout_remote_requested (remote)."""
        role = item.data(0, Qt.ItemDataRole.UserRole + 1)
        branch_name: str = item.data(0, Qt.ItemDataRole.UserRole) or ""

        if role == "local" and branch_name:
            self.checkout_requested.emit(branch_name)
        elif role == "remote" and branch_name:
            self.checkout_remote_requested.emit(branch_name)
        elif role == "tag" and branch_name:
            self.checkout_tag_requested.emit(branch_name)

    # ── Drag & drop ───────────────────────────────────────────────────

    def _is_local_branch_item(self, item: QTreeWidgetItem | None) -> bool:
        return (
            item is not None
            and item.data(0, Qt.ItemDataRole.UserRole + 1) == "local"
        )

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        source = self.currentItem()
        if self._is_local_branch_item(source):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if (
            self._is_local_branch_item(source)
            and self._is_local_branch_item(target)
            and target is not source
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Intercept drops between local branches and emit merge_requested.

        Never call super().dropEvent() — we never want to physically move items.
        """
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        event.ignore()  # always prevent Qt from rearranging the tree

        if not (
            self._is_local_branch_item(source)
            and self._is_local_branch_item(target)
            and target is not source
        ):
            return

        source_branch: str = source.data(0, Qt.ItemDataRole.UserRole)
        target_branch: str = target.data(0, Qt.ItemDataRole.UserRole)
        if source_branch and target_branch:
            self.merge_requested.emit(source_branch, target_branch)

    # ── Context menu ──────────────────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        """Show a context menu for the item at *pos* (viewport coordinates)."""
        item = self.itemAt(pos)
        if item is None:
            return

        role = item.data(0, Qt.ItemDataRole.UserRole + 1)
        branch_name: str = item.data(0, Qt.ItemDataRole.UserRole) or ""

        if role == "local" and branch_name:
            self._show_local_branch_menu(pos, branch_name)
        elif role == "remote" and branch_name:
            self._show_remote_branch_menu(pos, branch_name)
        elif role == "tag" and branch_name:
            self._show_tag_menu(pos, branch_name)

    def _show_local_branch_menu(self, pos, branch_name: str) -> None:
        menu = QMenu(self)

        checkout_act = menu.addAction(get_icon("checkout"), f"Checkout '{branch_name}'")
        menu.addSeparator()
        rename_act  = menu.addAction(get_icon("rename"),   "Rename Branch…")
        delete_act  = menu.addAction(get_icon("delete"),   "Delete Branch…")

        # Disable checkout if it's the active branch (already on it)
        if branch_name == self._active_branch:
            checkout_act.setEnabled(False)
            checkout_act.setText(f"✔ '{branch_name}' (active)")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))

        if chosen == checkout_act:
            self.checkout_requested.emit(branch_name)

        elif chosen == rename_act:
            new_name, ok = QInputDialog.getText(
                self, "Rename Branch",
                f"New name for branch <b>{branch_name}</b>:",
                text=branch_name,
            )
            if ok and new_name.strip() and new_name.strip() != branch_name:
                self.rename_branch_requested.emit(branch_name, new_name.strip())

        elif chosen == delete_act:
            reply = QMessageBox.warning(
                self, "Delete Branch",
                f"Permanently delete branch <b>{branch_name}</b>?<br>"
                "This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_branch_requested.emit(branch_name)

    def _show_remote_branch_menu(self, pos, remote_ref: str) -> None:
        """Context menu for a remote-tracking branch."""
        menu = QMenu(self)

        parts = remote_ref.split("/", 1)
        local_name = parts[1] if len(parts) == 2 else remote_ref

        checkout_act = menu.addAction(
            get_icon("checkout"), f"Checkout as '{local_name}' (local)"
        )

        chosen = menu.exec(self.viewport().mapToGlobal(pos))

        if chosen == checkout_act:
            self.checkout_remote_requested.emit(remote_ref)

    def _show_tag_menu(self, pos, tag_name: str) -> None:
        """Context menu for a tag item."""
        menu = QMenu(self)

        checkout_act = menu.addAction(
            get_icon("checkout"), f"Checkout '{tag_name}' (detached HEAD)"
        )
        menu.addSeparator()
        branch_act = menu.addAction(get_icon("branch"), f"Create Branch From '{tag_name}'…")
        menu.addSeparator()
        push_act = menu.addAction(get_icon("push"), f"Push Tag to Remote…")
        menu.addSeparator()
        delete_act = menu.addAction(get_icon("delete"), f"Delete Tag…")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))

        if chosen == checkout_act:
            self.checkout_tag_requested.emit(tag_name)

        elif chosen == branch_act:
            branch_name, ok = QInputDialog.getText(
                self,
                "Create Branch From Tag",
                f"New branch name for tag <b>{tag_name}</b>:",
                text=tag_name,
            )
            if ok and branch_name.strip():
                self.create_branch_from_tag_requested.emit(tag_name, branch_name.strip())

        elif chosen == push_act:
            self.push_tag_requested.emit(tag_name)

        elif chosen == delete_act:
            reply = QMessageBox.warning(
                self, "Delete Tag",
                f"Permanently delete tag <b>{tag_name}</b>?<br>"
                "This only removes the local tag.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_tag_requested.emit(tag_name)
