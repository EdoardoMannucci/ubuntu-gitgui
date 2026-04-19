"""
MainWindow — the application's top-level window.

Layout (3-panel split):
    ┌──────────┬──────────────────────────┬────────────┐
    │          │                          │  Staging   │
    │ Sidebar  │    Commit Graph          │  Area      │
    │  (20 %)  │       (50 %)             │  (30 %)    │
    │          │                          ├────────────┤
    │          │                          │  Diff      │
    │          │                          │  Viewer    │
    └──────────┴──────────────────────────┴────────────┘

Phase 1: full layout skeleton with dark-mode stylesheet.
Phase 2: ProfileController wired up; identity dialog via menu + toolbar.
Phase 3: RepositoryController wired up; File menu (Open/Init/Clone) fully
         functional; SidebarWidget populated with live branches/tags;
         double-click checkout with visual active-branch highlight.
Phase 4: CommitGraphWidget (QTableView + custom delegate) shows commit history.
Phase 5: StagingController + StagingWidget replace the staging placeholder.
         Commit uses the active profile identity (git.Actor) directly.
"""

import git
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.controllers.profile_controller import ProfileController
from src.controllers.repository_controller import BranchState, RepositoryController
from src.controllers.staging_controller import StagingController
from src.controllers.toolbar_controller import ToolbarController
from src.models.profile import Profile
from src.models.recent_repos import RecentRepositoryManager
from src.utils.icons import icon as get_icon
from src.utils.update_checker import UpdateChecker
from src.views.about_dialog import AboutDialog, _VERSION
from src.views.commit_dialog import CommitDialog
from src.views.clone_dialog import CloneDialog
from src.views.commit_graph_widget import CommitGraphWidget
from src.views.commit_inspector_widget import CommitInspectorWidget
from src.views.create_tag_dialog import CreateTagDialog
from src.views.diff_viewer import DiffViewerWidget
from src.views.profile_dialog import ProfileDialog
from src.views.settings_dialog import SettingsDialog
from src.views.sidebar_widget import SidebarWidget
from src.views.staging_widget import StagingWidget


class MainWindow(QMainWindow):
    """Top-level application window with a 3-panel layout."""

    WINDOW_WIDTH: int = 1400
    WINDOW_HEIGHT: int = 800
    MIN_WIDTH: int = 900
    MIN_HEIGHT: int = 600

    # Number of commits fetched per page (fetch PAGE_SIZE+1 to detect more)
    _GRAPH_PAGE_SIZE: int = 100

    def __init__(self) -> None:
        super().__init__()

        # Recent-repository manager (Phase 12)
        self._recent_repos = RecentRepositoryManager()

        # Controllers — owned here, lifetime == application lifetime
        self._profile_ctrl = ProfileController(parent=self)
        self._profile_ctrl.active_changed.connect(self._on_active_profile_changed)

        self._repo_ctrl = RepositoryController(parent=self)
        self._repo_ctrl.repo_opened.connect(self._on_repo_opened)
        self._repo_ctrl.repo_closed.connect(self._on_repo_closed)
        self._repo_ctrl.branch_changed.connect(self._on_branch_changed)
        self._repo_ctrl.refs_updated.connect(self._on_refs_updated)
        self._repo_ctrl.state_changed.connect(self._on_repo_state_changed)
        self._repo_ctrl.clone_started.connect(self._on_clone_started)
        self._repo_ctrl.clone_finished.connect(self._on_clone_finished)
        self._repo_ctrl.clone_failed.connect(self._on_clone_failed)

        self._staging_ctrl = StagingController(parent=self)
        self._staging_ctrl.status_changed.connect(self._check_conflict_state)
        self._staging_ctrl.commit_made.connect(self._on_staging_commit_made)

        self._toolbar_ctrl = ToolbarController(parent=self)
        self._toolbar_ctrl.operation_started.connect(self._on_toolbar_started)
        self._toolbar_ctrl.operation_finished.connect(self._on_toolbar_finished)
        self._toolbar_ctrl.operation_failed.connect(self._on_toolbar_failed)
        self._toolbar_ctrl.refs_changed.connect(self._on_toolbar_refs_changed)
        self._toolbar_ctrl.working_tree_changed.connect(self._on_toolbar_working_tree_changed)

        self._clone_in_progress = False
        self._last_working_tree_signature: tuple[tuple[str, str, bool], ...] = ()
        self._working_tree_timer = QTimer(self)
        self._working_tree_timer.setInterval(1500)
        self._working_tree_timer.timeout.connect(self._poll_working_tree_status)

        self._setup_window()
        self._build_menu_bar()
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_bar()

        # Auto-open the most-recently-used repository on startup.
        # Deferred via QTimer so the window is fully shown before loading.
        QTimer.singleShot(0, self._auto_load_startup_repo)

        # Check for updates in the background after the window is ready.
        QTimer.singleShot(2000, self._start_update_check)

    # ── Window chrome ─────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("ubuntu-gitgui")
        self.resize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        # Set window icon — uses QApplication icon when already set; this
        # also covers cases where MainWindow is shown before app.setWindowIcon
        app_icon = QApplication.instance()
        if app_icon is not None:
            self.setWindowIcon(app_icon.windowIcon())

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Shut down the toolbar worker thread before the window closes."""
        self._toolbar_ctrl._thread.quit()
        self._toolbar_ctrl._thread.wait(3000)
        super().closeEvent(event)

    # ── Menu bar ──────────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        """Build the application menu bar."""
        menu_bar: QMenuBar = self.menuBar()

        # ── File ──────────────────────────────────────────────────
        file_menu: QMenu = menu_bar.addMenu(self.tr("&File"))

        self._open_action = QAction(get_icon("open"), self.tr("Open Repository…"), self)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._action_open_repo)
        file_menu.addAction(self._open_action)

        self._init_action = QAction(get_icon("init"), self.tr("Init Repository…"), self)
        self._init_action.triggered.connect(self._action_init_repo)
        file_menu.addAction(self._init_action)

        self._clone_action = QAction(get_icon("clone"), self.tr("Clone Repository…"), self)
        self._clone_action.setShortcut("Ctrl+Shift+C")
        self._clone_action.triggered.connect(self._action_clone_repo)
        file_menu.addAction(self._clone_action)

        file_menu.addSeparator()

        # ── Recent Repositories submenu (Phase 12) ─────────────
        self._recent_menu: QMenu = file_menu.addMenu(
            get_icon("open"), self.tr("Recent Repositories")
        )
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)

        clear_recent_action = QAction(
            get_icon("delete"), self.tr("Clear Recent Repositories"), self
        )
        clear_recent_action.triggered.connect(self._action_clear_recent)
        file_menu.addAction(clear_recent_action)

        file_menu.addSeparator()

        manage_profiles_action = QAction(
            get_icon("profiles"), self.tr("Manage Profiles…"), self
        )
        manage_profiles_action.setShortcut("Ctrl+Shift+P")
        manage_profiles_action.triggered.connect(self._open_profile_dialog)
        file_menu.addAction(manage_profiles_action)

        file_menu.addSeparator()

        quit_action = QAction(get_icon("quit"), self.tr("Quit"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # ── Settings ──────────────────────────────────────────────
        settings_menu: QMenu = menu_bar.addMenu(self.tr("&Settings"))
        settings_menu.setIcon(get_icon("settings"))

        prefs_action = QAction(get_icon("settings"), self.tr("Preferences…"), self)
        prefs_action.setShortcut("Ctrl+,")
        prefs_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(prefs_action)

        # ── Help ──────────────────────────────────────────────────
        help_menu: QMenu = menu_bar.addMenu(self.tr("&Help"))
        help_menu.setIcon(get_icon("help"))

        about_action = QAction(get_icon("about"), self.tr("About ubuntu-gitgui…"), self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

        check_update_action = QAction(get_icon("refresh"), self.tr("Check for Updates…"), self)
        check_update_action.triggered.connect(self._check_for_updates_manual)
        help_menu.addAction(check_update_action)

        help_menu.addSeparator()

        links_menu: QMenu = help_menu.addMenu(get_icon("links"), self.tr("Useful Links"))

        github_action = QAction(self.tr("Source Code on GitHub"), self)
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/edoardottt/ubuntu-gitgui")
            )
        )
        links_menu.addAction(github_action)

        issues_action = QAction(self.tr("Report a Bug / Request a Feature"), self)
        issues_action.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/edoardottt/ubuntu-gitgui/issues")
            )
        )
        links_menu.addAction(issues_action)

        gitpython_action = QAction("GitPython Documentation", self)
        gitpython_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://gitpython.readthedocs.io"))
        )
        links_menu.addAction(gitpython_action)

    # ── Toolbar ───────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        """Build the main toolbar with icons and connected actions."""
        from PyQt6.QtCore import QSize

        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(22, 22))

        # ── Recent-repositories combo (Phase 12) — leftmost widget ─
        self._repo_combo = QComboBox()
        self._repo_combo.setMinimumWidth(170)
        self._repo_combo.setMaximumWidth(260)
        self._repo_combo.setToolTip(self.tr("Switch recent repository"))
        self._repo_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        toolbar.addWidget(self._repo_combo)
        toolbar.addSeparator()

        # Populate after the widget is shown
        self._refresh_repo_combo()

        # Connect with activated (fires only on user interaction, not on
        # programmatic setCurrentIndex calls)
        self._repo_combo.activated.connect(self._on_combo_activated)

        # ── Network operations (async) ─────────────────────────────
        self._action_fetch = QAction(get_icon("fetch"), self.tr("Fetch"), self)
        self._action_fetch.setToolTip(self.tr("Fetch all remotes (git fetch --all --prune)"))
        self._action_fetch.triggered.connect(self._toolbar_ctrl.fetch)
        toolbar.addAction(self._action_fetch)

        self._action_pull = QAction(get_icon("pull"), self.tr("Pull"), self)
        self._action_pull.setToolTip(self.tr("Pull current branch (git pull --ff-only)"))
        self._action_pull.triggered.connect(self._action_pull_with_confirmation)
        toolbar.addAction(self._action_pull)

        self._action_commit = QAction(get_icon("commit"), self.tr("Commit"), self)
        self._action_commit.setToolTip(self.tr("Open the commit workspace"))
        self._action_commit.triggered.connect(self._open_commit_dialog)
        toolbar.addAction(self._action_commit)

        self._action_push = QAction(get_icon("push"), self.tr("Push"), self)
        self._action_push.setToolTip(self.tr("Push current branch to its upstream"))
        self._action_push.triggered.connect(self._action_push_with_confirmation)
        toolbar.addAction(self._action_push)

        toolbar.addSeparator()

        self._action_undo_nav = QAction(get_icon("undo"), self.tr("Undo"), self)
        self._action_undo_nav.setToolTip(self.tr("Go back to the previous checked out ref"))
        self._action_undo_nav.triggered.connect(self._action_undo_navigation)
        toolbar.addAction(self._action_undo_nav)

        self._action_redo_nav = QAction(get_icon("redo"), self.tr("Redo"), self)
        self._action_redo_nav.setToolTip(self.tr("Restore the most recently undone checkout"))
        self._action_redo_nav.triggered.connect(self._action_redo_navigation)
        toolbar.addAction(self._action_redo_nav)

        toolbar.addSeparator()

        # ── Local operations (sync) ────────────────────────────────
        self._action_branch = QAction(get_icon("branch"), self.tr("Branch"), self)
        self._action_branch.setToolTip(self.tr("Create a new branch at HEAD"))
        self._action_branch.triggered.connect(self._action_create_branch)
        toolbar.addAction(self._action_branch)

        self._action_stash = QAction(get_icon("stash"), self.tr("Stash"), self)
        self._action_stash.setToolTip(self.tr("Stash working-tree changes (git stash push)"))
        self._action_stash.triggered.connect(self._action_stash_changes)
        toolbar.addAction(self._action_stash)

        self._action_pop = QAction(get_icon("pop"), self.tr("Pop"), self)
        self._action_pop.setToolTip(self.tr("Apply most-recent stash (git stash pop)"))
        self._action_pop.triggered.connect(self._action_pop_stash)
        toolbar.addAction(self._action_pop)

        toolbar.addSeparator()

        # ── Identity ───────────────────────────────────────────────
        identity_action = QAction(get_icon("identity"), self.tr("Identity"), self)
        identity_action.setToolTip(self.tr("Manage Git identity profiles (Ctrl+Shift+P)"))
        identity_action.triggered.connect(self._open_profile_dialog)
        toolbar.addAction(identity_action)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._set_toolbar_action_style(toolbar, self._action_commit, "toolbar_primary_btn")
        self._set_toolbar_action_style(toolbar, self._action_push, "toolbar_secondary_btn")

        # All git actions start disabled until a repo is open
        self._git_actions: list[QAction] = [
            self._action_fetch,
            self._action_pull,
            self._action_commit,
            self._action_push,
            self._action_undo_nav,
            self._action_redo_nav,
            self._action_branch,
            self._action_stash,
            self._action_pop,
        ]
        self._set_toolbar_enabled(False)

    @staticmethod
    def _set_toolbar_action_style(toolbar: QToolBar, action: QAction, object_name: str) -> None:
        """Assign a stable object name to a toolbar action's backing button."""
        button = toolbar.widgetForAction(action)
        if button is not None:
            button.setObjectName(object_name)
            button.style().unpolish(button)
            button.style().polish(button)

    # ── Central widget ────────────────────────────────────────────────

    def _build_central_widget(self) -> None:
        """Assemble the QSplitter tree that defines the main layout."""
        outer_splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: sidebar
        self._sidebar = SidebarWidget()
        self._sidebar.checkout_requested.connect(self._on_checkout_requested)
        self._sidebar.checkout_remote_requested.connect(self._on_checkout_remote_requested)
        self._sidebar.checkout_tag_requested.connect(self._on_checkout_tag_requested)
        self._sidebar.merge_requested.connect(self._on_merge_requested)
        self._sidebar.delete_branch_requested.connect(self._on_delete_branch)
        self._sidebar.rename_branch_requested.connect(self._on_rename_branch)
        self._sidebar.delete_tag_requested.connect(self._on_delete_tag)
        self._sidebar.push_tag_requested.connect(self._on_push_tag)
        self._sidebar.create_branch_from_tag_requested.connect(
            self._on_create_branch_from_tag
        )
        outer_splitter.addWidget(self._sidebar)

        # Center: vertical splitter — commit graph (top) + inspector (bottom)
        center_splitter = QSplitter(Qt.Orientation.Vertical)

        self._graph_widget = CommitGraphWidget()
        self._graph_widget.load_more_requested.connect(self._on_load_more_commits)
        self._graph_widget.checkout_hash_requested.connect(self._on_checkout_hash)
        self._graph_widget.commit_selected.connect(self._on_commit_selected)
        self._graph_widget.create_tag_requested.connect(self._on_create_tag)
        self._graph_widget.create_branch_requested.connect(
            self._on_create_branch_from_commit
        )
        center_splitter.addWidget(self._graph_widget)

        self._commit_inspector = CommitInspectorWidget()
        self._commit_inspector.file_selected.connect(self._on_inspector_file_selected)
        center_splitter.addWidget(self._commit_inspector)

        center_splitter.setSizes([
            int(self.WINDOW_HEIGHT * 0.65),
            int(self.WINDOW_HEIGHT * 0.35),
        ])

        outer_splitter.addWidget(center_splitter)

        # Right: staging + diff panels (Phases 5 & 6)
        outer_splitter.addWidget(self._build_right_panel())

        total = self.WINDOW_WIDTH
        outer_splitter.setSizes([
            int(total * 0.20),
            int(total * 0.50),
            int(total * 0.30),
        ])

        self.setCentralWidget(outer_splitter)

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        outer_layout = QVBoxLayout(container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── Conflict banner (Phase 8) — hidden until a conflict occurs ─
        outer_layout.addWidget(self._build_conflict_banner())

        # ── Vertical splitter: staging (top) + diff (bottom) ──────
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        self._staging_widget = StagingWidget(
            staging_ctrl=self._staging_ctrl,
            profile_ctrl=self._profile_ctrl,
        )
        self._staging_widget.file_selected.connect(self._on_file_selected_for_diff)
        self._staging_widget.open_commit_dialog_requested.connect(
            self._open_commit_dialog
        )
        right_splitter.addWidget(self._staging_widget)

        self._diff_viewer = DiffViewerWidget(staging_ctrl=self._staging_ctrl)
        right_splitter.addWidget(self._diff_viewer)

        right_splitter.setSizes([
            int(self.WINDOW_HEIGHT * 0.55),
            int(self.WINDOW_HEIGHT * 0.45),
        ])
        outer_layout.addWidget(right_splitter, stretch=1)
        return container

    # ── Status bar ────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar(self)

        self._repo_status_label = QLabel("No repository open")
        status_bar.addWidget(self._repo_status_label)

        # Active-branch indicator (centre-left, hidden until a repo is open)
        self._branch_status_label = QLabel()
        self._branch_status_label.setObjectName("branch_status_label")
        self._branch_status_label.hide()
        status_bar.addWidget(self._branch_status_label)

        # Active profile indicator (pinned to the right)
        self._profile_status_label = QLabel()
        self._profile_status_label.setObjectName("profile_status_label")
        status_bar.addPermanentWidget(self._profile_status_label)
        self._refresh_profile_status()

        self.setStatusBar(status_bar)

    # ── File menu actions ─────────────────────────────────────────────

    def _action_open_repo(self) -> None:
        """File → Open Repository…"""
        path = QFileDialog.getExistingDirectory(
            self,
            "Open Git Repository",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return
        try:
            self._repo_ctrl.open_repo(path)
        except git.InvalidGitRepositoryError:
            QMessageBox.warning(
                self,
                "Not a Git Repository",
                f"The selected folder is not a Git repository:\n\n{path}\n\n"
                "Use File → Init Repository to create a new one.",
            )
        except git.NoSuchPathError:
            QMessageBox.critical(self, "Path Not Found", f"Path does not exist:\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error Opening Repository", str(exc))

    def _action_init_repo(self) -> None:
        """File → Init Repository…"""
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder to Initialise as Git Repository",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return
        try:
            self._repo_ctrl.init_repo(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error Initialising Repository", str(exc))

    def _action_clone_repo(self) -> None:
        """File → Clone Repository…"""
        from src.utils.credentials import AuthMethod, get_token

        # Resolve auth credentials from the active profile for display + use
        active_profile = self._profile_ctrl.active_profile
        ssh_key        = ""
        https_username = ""
        https_token    = ""

        if active_profile:
            if active_profile.auth_method == AuthMethod.HTTPS:
                https_username = active_profile.https_username
                https_token    = get_token(https_username)
            else:
                ssh_key = active_profile.ssh_key_path or ""

        dialog = CloneDialog(ssh_key_path=ssh_key, parent=self)
        if dialog.exec() != CloneDialog.DialogCode.Accepted:
            return

        url  = dialog.clone_url
        dest = dialog.clone_destination

        self._repo_ctrl.start_clone(
            url,
            dest,
            ssh_key_path=ssh_key,
            https_username=https_username,
            https_token=https_token,
        )

    # ── Repository signal handlers ────────────────────────────────────

    def _on_repo_opened(self, repo_path: str) -> None:
        """Triggered by RepositoryController.repo_opened."""
        # Persist to recent list and refresh the combo
        self._recent_repos.add(repo_path)
        self._refresh_repo_combo()

        self._populate_sidebar()
        self._update_window_title()
        self._update_repo_status_label()

        # Commit graph — first page of up to _GRAPH_PAGE_SIZE commits
        commits = self._repo_ctrl.load_commits(max_count=self._GRAPH_PAGE_SIZE + 1)
        has_more = len(commits) > self._GRAPH_PAGE_SIZE
        self._graph_widget.populate(
            commits[: self._GRAPH_PAGE_SIZE],
            has_more=has_more,
            tags_by_hash=self._repo_ctrl.tags_for_commit(),
        )

        # Hand the live Repo object to the staging + toolbar controllers + inspector
        self._staging_ctrl.set_repo(self._repo_ctrl.repo)
        self._toolbar_ctrl.set_repo(self._repo_ctrl.repo)
        self._commit_inspector.set_repo(self._repo_ctrl.repo)
        self._set_toolbar_enabled(True)

        # Apply active profile to the newly opened repo if one is set
        active = self._profile_ctrl.active_profile
        if active and self._repo_ctrl.repo:
            try:
                self._profile_ctrl.apply_to_repo(self._repo_ctrl.repo)
            except Exception:  # noqa: BLE001
                pass
        # Always sync profile (including auth credentials) to toolbar controller
        self._toolbar_ctrl.set_profile(active)
        self._last_working_tree_signature = ()
        self._working_tree_timer.start()
        self._refresh_sync_badges()
        self._sync_working_tree_now()
        self._refresh_action_states()

    def _on_repo_closed(self) -> None:
        """Triggered by RepositoryController.repo_closed."""
        self._working_tree_timer.stop()
        self._last_working_tree_signature = ()
        self._refresh_sync_badges()
        self._sidebar.clear_to_empty_state()
        self._graph_widget.clear()
        self._staging_ctrl.set_repo(None)
        self._toolbar_ctrl.set_repo(None)
        self._commit_inspector.set_repo(None)
        self._set_toolbar_enabled(False)
        self._diff_viewer.clear()
        self._update_window_title()
        self._repo_status_label.setText("No repository open")
        self._branch_status_label.hide()
        self._refresh_action_states()

    def _on_clone_started(self, url: str, destination: str) -> None:
        self._clone_in_progress = True
        self._set_toolbar_enabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(
            self.tr("Cloning {0} into {1}…").format(url, destination)
        )

    def _on_clone_finished(self, repo_path: str) -> None:
        self._clone_in_progress = False
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(repo_path)
        self._refresh_action_states()

    def _on_clone_failed(self, error: str) -> None:
        self._clone_in_progress = False
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            self._repo_ctrl.repo_path if self._repo_ctrl.is_open else self.tr("No repository open")
        )
        self._refresh_action_states()
        QMessageBox.critical(self, self.tr("Clone Failed"), error)

    def _on_repo_state_changed(self, _state) -> None:
        self._update_repo_status_label()
        self._refresh_action_states()

    def _on_branch_changed(self, branch_name: str) -> None:
        """Triggered after a successful checkout or merge."""
        self._sidebar.refresh_active_branch(branch_name)
        self._update_repo_status_label()
        # Reload graph and staging state after a branch switch / merge
        commits = self._repo_ctrl.load_commits(max_count=self._GRAPH_PAGE_SIZE + 1)
        has_more = len(commits) > self._GRAPH_PAGE_SIZE
        self._graph_widget.populate(
            commits[: self._GRAPH_PAGE_SIZE],
            has_more=has_more,
            tags_by_hash=self._repo_ctrl.tags_for_commit(),
        )
        self._refresh_sync_badges()
        self._sync_working_tree_now()

    def _on_file_selected_for_diff(self, path: str, is_staged: bool) -> None:
        """Forward a file-click from the staging widget to the diff viewer."""
        self._diff_viewer.show_diff(path, is_staged)

    def _open_commit_dialog(self) -> None:
        """Open the CommitDialog workspace when the user clicks 'Commit Changes…'."""
        dialog = CommitDialog(
            staging_ctrl=self._staging_ctrl,
            profile_ctrl=self._profile_ctrl,
            repo_name=self._repo_ctrl.repo_name,
            parent=self,
        )
        dialog.commit_and_push_requested.connect(self._commit_and_push_from_dialog)
        dialog.exec()
        # Graph reload is triggered automatically via _on_staging_commit_made
        # which is connected to staging_ctrl.commit_made.

    def _commit_and_push_from_dialog(self) -> None:
        """Start a push immediately after a successful commit dialog submission."""
        self._toolbar_ctrl.push()

    def _on_staging_commit_made(self, short_hash: str) -> None:
        """Reload the commit graph after a successful commit from CommitDialog."""
        self._reload_graph()
        self._refresh_sync_badges()
        self._sync_working_tree_now()

    def _auto_load_startup_repo(self) -> None:
        """Auto-open the most-recently-used repository when the app launches.

        Called via QTimer.singleShot(0, ...) in __init__ so the window is
        fully visible before any blocking I/O runs.
        """
        if self._repo_ctrl.is_open:
            return  # Already have a repo open (shouldn't happen at startup)
        data = self._repo_combo.currentData()
        if isinstance(data, str) and data and data not in ("", "__CLEAR__"):
            self._open_recent_repo(data)

    def _on_checkout_requested(self, branch_name: str) -> None:
        """Triggered by SidebarWidget.checkout_requested (user double-clicked)."""
        if self._repo_ctrl.current_branch_name == branch_name:
            return
        if not self._confirm_branch_switch(branch_name):
            return
        try:
            self._repo_ctrl.checkout_branch(branch_name)
        except git.GitCommandError as exc:
            # Common cause: uncommitted changes that would be overwritten
            QMessageBox.warning(
                self,
                "Checkout Failed",
                f"Could not switch to branch <b>{branch_name}</b>.<br><br>"
                f"<pre>{exc.stderr.strip()}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Checkout Error", str(exc))

    def _on_checkout_remote_requested(self, remote_ref: str) -> None:
        """Triggered by SidebarWidget.checkout_remote_requested (double-click / menu)."""
        parts = remote_ref.split("/", 1)
        local_name = parts[1] if len(parts) == 2 else remote_ref
        if self._repo_ctrl.current_branch_name == local_name:
            return

        reply = QMessageBox.question(
            self,
            "Checkout Remote Branch",
            f"Create local branch <b>{local_name}</b> tracking <b>{remote_ref}</b>"
            " and switch to it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_branch_switch(local_name):
            return

        try:
            self._repo_ctrl.checkout_remote_branch(remote_ref)
            self._populate_sidebar()
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Checkout Failed",
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Checkout Error", str(exc))

    # ── Profile signal handlers ───────────────────────────────────────

    def _open_profile_dialog(self) -> None:
        ProfileDialog(controller=self._profile_ctrl, parent=self).exec()

    def _on_active_profile_changed(self, profile: Profile | None) -> None:
        self._refresh_profile_status()
        # Apply the new profile's git identity to the open repo
        if profile and self._repo_ctrl.repo:
            try:
                self._profile_ctrl.apply_to_repo(self._repo_ctrl.repo)
            except Exception:  # noqa: BLE001
                pass
        # Sync auth credentials (SSH key or HTTPS token) to the toolbar controller
        self._toolbar_ctrl.set_profile(profile)

    # ── Commit inspector signal handlers ──────────────────────────────

    def _on_commit_selected(self, commit) -> None:
        """Triggered by CommitGraphWidget.commit_selected (row change)."""
        if commit is None:
            self._commit_inspector.clear()
        else:
            self._commit_inspector.show_commit(commit)

    def _on_inspector_file_selected(self, full_hash: str, path: str) -> None:
        """Triggered by CommitInspectorWidget.file_selected (user clicked a file)."""
        self._diff_viewer.show_commit_diff(path, full_hash[:7], full_hash)

    # ── Help menu handlers ────────────────────────────────────────────

    def _show_about_dialog(self) -> None:
        AboutDialog(parent=self).exec()

    # ── Update checker ────────────────────────────────────────────────

    def _start_update_check(self) -> None:
        self._update_checker = UpdateChecker(_VERSION, parent=self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _check_for_updates_manual(self) -> None:
        """Manual 'Check for Updates' — runs inline and always shows a result."""
        checker = UpdateChecker(_VERSION, parent=self)
        checker.update_available.connect(
            lambda ver, url: self._show_update_dialog(ver, url)
        )
        checker.finished.connect(
            lambda: self._maybe_show_up_to_date(checker)
        )
        checker._manual = True
        checker._update_found = False
        checker.update_available.connect(lambda *_: setattr(checker, "_update_found", True))
        checker.start()
        self._manual_checker = checker

    def _maybe_show_up_to_date(self, checker: UpdateChecker) -> None:
        if not getattr(checker, "_update_found", False):
            QMessageBox.information(
                self,
                self.tr("No Updates Found"),
                self.tr(
                    f"You are running the latest version ({_VERSION})."
                ),
            )

    def _on_update_available(self, latest: str, url: str) -> None:
        self._show_update_dialog(latest, url)

    def _show_update_dialog(self, latest: str, url: str) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle(self.tr("Update Available"))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            self.tr(
                f"<b>Version {latest}</b> is available.<br><br>"
                f"You are currently running <b>{_VERSION}</b>.<br>"
                f"Download the new <code>.deb</code> from GitHub Releases "
                f"and install it with:<br><br>"
                f"<code>sudo dpkg -i ubuntu-gitgui_{latest}_amd64.deb</code>"
            )
        )
        open_btn = msg.addButton(
            self.tr("Open Releases Page"), QMessageBox.ButtonRole.AcceptRole
        )
        msg.addButton(self.tr("Later"), QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(url))

    # ── Sidebar context-menu handlers ─────────────────────────────────

    def _on_delete_branch(self, branch_name: str) -> None:
        """Delete a local branch (non-destructive check: prevent deleting HEAD)."""
        if not self._repo_ctrl.is_open:
            return
        if branch_name == self._repo_ctrl.current_branch_name:
            QMessageBox.warning(
                self, "Cannot Delete",
                f"Cannot delete the currently checked-out branch <b>{branch_name}</b>.<br>"
                "Switch to another branch first.",
            )
            return
        try:
            self._repo_ctrl.repo.git.branch("-d", branch_name)
        except git.GitCommandError:
            # Branch not fully merged — ask user if they want to force-delete
            reply = QMessageBox.question(
                self, "Branch Not Merged",
                f"Branch <b>{branch_name}</b> has unmerged commits.<br><br>"
                "Force-delete it anyway? (commits will NOT be lost immediately, "
                "but the branch reference will be gone)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self._repo_ctrl.repo.git.branch("-D", branch_name)
                except git.GitCommandError as exc:
                    QMessageBox.critical(self, "Delete Failed",
                                         exc.stderr.strip() if exc.stderr else str(exc))
                    return
            else:
                return
        self._populate_sidebar()

    def _on_rename_branch(self, old_name: str, new_name: str) -> None:
        """Rename a local branch with `git branch -m`."""
        if not self._repo_ctrl.is_open:
            return
        try:
            self._repo_ctrl.repo.git.branch("-m", old_name, new_name)
        except git.GitCommandError as exc:
            QMessageBox.critical(self, "Rename Failed",
                                 exc.stderr.strip() if exc.stderr else str(exc))
            return
        self._populate_sidebar()
        # If we renamed the current branch, update the title + status bar
        if old_name == self._repo_ctrl.current_branch_name:
            self._update_window_title()
            self._update_repo_status_label()

    # ── Commit graph context-menu handlers ────────────────────────────

    def _on_checkout_hash(self, full_hash: str) -> None:
        """Checkout a specific commit hash (detached HEAD)."""
        reply = QMessageBox.question(
            self, "Checkout Commit",
            f"Checkout commit <b>{full_hash[:12]}</b>?<br><br>"
            "The repository will be in <i>detached HEAD</i> state.<br>"
            "Create a new branch to keep your changes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_branch_switch(full_hash[:12]):
            return
        try:
            self._repo_ctrl.checkout_commit(full_hash)
            self._populate_sidebar()
            self._update_window_title()
            self._update_repo_status_label()
            self._staging_ctrl.status_changed.emit()
        except git.GitCommandError as exc:
            QMessageBox.critical(self, "Checkout Failed",
                                 exc.stderr.strip() if exc.stderr else str(exc))

    # ── Tag management handlers (Phase 15) ────────────────────────────

    def _on_checkout_tag_requested(self, tag_name: str) -> None:
        """Sidebar double-click or context menu → Checkout tag (detached HEAD)."""
        reply = QMessageBox.warning(
            self,
            "Checkout Tag — Detached HEAD",
            f"Checking out tag <b>{tag_name}</b> will put the repository in "
            "<i>detached HEAD</i> state.<br><br>"
            "You can look around and make experimental commits, but any commits "
            "will not belong to a branch and may be lost unless you create a new "
            "branch: <tt>git switch -c &lt;new-branch&gt;</tt>.<br><br>"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_branch_switch(tag_name):
            return
        try:
            self._repo_ctrl.checkout_tag(tag_name)
            self._populate_sidebar()
            self._update_window_title()
            self._update_repo_status_label()
            self._staging_ctrl.status_changed.emit()
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Checkout Failed",
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Checkout Error", str(exc))

    def _on_create_tag(self, full_hash: str) -> None:
        """Commit-graph context menu → Create Tag Here…"""
        if not self._repo_ctrl.is_open:
            return
        dialog = CreateTagDialog(commit_short=full_hash[:12], parent=self)
        if dialog.exec() != CreateTagDialog.DialogCode.Accepted:
            return
        try:
            self._repo_ctrl.create_tag(
                name=dialog.tag_name,
                ref=full_hash,
                message=dialog.tag_message,
            )
            # refs_updated signal triggers sidebar + graph refresh automatically
        except git.GitCommandError as exc:
            msg = exc.stderr.strip() if exc.stderr else str(exc)
            if "already exists" in msg:
                QMessageBox.warning(
                    self, "Tag Already Exists",
                    f"A tag named <b>{dialog.tag_name}</b> already exists.<br>"
                    "Choose a different name.",
                )
            else:
                QMessageBox.critical(self, "Tag Creation Failed", f"<pre>{msg}</pre>")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Tag Creation Error", str(exc))

    def _on_delete_tag(self, tag_name: str) -> None:
        """Sidebar context menu → Delete Tag (confirmation already shown in sidebar)."""
        if not self._repo_ctrl.is_open:
            return
        try:
            self._repo_ctrl.delete_tag(tag_name)
            # refs_updated signal triggers sidebar + graph refresh automatically
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Delete Tag Failed",
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete Tag Error", str(exc))

    def _on_push_tag(self, tag_name: str) -> None:
        """Sidebar context menu → Push Tag to Remote."""
        if not self._repo_ctrl.is_open:
            return
        if not self._repo_ctrl.repo or not self._repo_ctrl.repo.remotes:
            QMessageBox.warning(
                self, "No Remote",
                "This repository has no configured remotes.<br>"
                "Add a remote with <tt>git remote add origin &lt;url&gt;</tt> first.",
            )
            return

        remote_name = self._repo_ctrl.repo.remotes[0].name
        reply = QMessageBox.question(
            self,
            "Push Tag",
            f"Push tag <b>{tag_name}</b> to remote <b>{remote_name}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.utils.credentials import AuthMethod, get_token

        ssh_key        = ""
        https_username = ""
        https_token    = ""
        active = self._profile_ctrl.active_profile
        if active:
            if active.auth_method == AuthMethod.HTTPS:
                https_username = active.https_username
                https_token    = get_token(https_username)
            elif active.ssh_key_path:
                ssh_key = active.ssh_key_path

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._repo_ctrl.push_tag(
                tag_name,
                ssh_key_path=ssh_key,
                https_username=https_username,
                https_token=https_token,
            )
            QMessageBox.information(
                self, "Push Tag",
                f"Tag <b>{tag_name}</b> pushed to <b>{remote_name}</b> successfully.",
            )
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Push Tag Failed",
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Push Tag Error", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    # ── Conflict banner ───────────────────────────────────────────────

    def _build_conflict_banner(self) -> QFrame:
        """Build the conflict-state banner (hidden by default)."""
        banner = QFrame()
        banner.setObjectName("conflict_banner")
        banner.hide()

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        icon = QLabel("⚠  MERGE CONFLICT — Resolve conflicts, stage files, then commit.")
        icon.setObjectName("conflict_banner_label")
        layout.addWidget(icon)
        layout.addStretch()

        abort_btn = QPushButton("Abort Merge")
        abort_btn.setObjectName("danger_btn")
        abort_btn.setFixedHeight(24)
        abort_btn.clicked.connect(self._on_abort_merge)
        layout.addWidget(abort_btn)

        self._conflict_banner = banner
        return banner

    def _check_conflict_state(self) -> None:
        """Show or hide the conflict banner based on the repo's merge state."""
        if hasattr(self, "_conflict_banner"):
            if self._staging_ctrl.is_merging:
                self._conflict_banner.show()
            else:
                self._conflict_banner.hide()

    def _on_abort_merge(self) -> None:
        """Abort the current merge and restore the pre-merge state."""
        try:
            self._staging_ctrl.abort_merge()
            self._conflict_banner.hide()
            self._populate_sidebar()
        except git.GitCommandError as exc:
            QMessageBox.critical(self, "Abort Failed",
                                 exc.stderr.strip() if exc.stderr else str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Abort Failed", str(exc))

    # ── Merge via drag & drop ─────────────────────────────────────────

    def _on_merge_requested(self, source_branch: str, target_branch: str) -> None:
        """Triggered by SidebarWidget.merge_requested (drag & drop)."""
        reply = QMessageBox.question(
            self,
            "Merge Branch",
            f"Merge <b>{source_branch}</b> into <b>{target_branch}</b>?"
            + (
                f"<br><br>This will first check out <b>{target_branch}</b>."
                if self._repo_ctrl.current_branch_name != target_branch
                else ""
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Checkout the target branch if we are not already on it
            if self._repo_ctrl.current_branch_name != target_branch:
                if not self._confirm_branch_switch(target_branch):
                    return
                self._repo_ctrl.checkout_branch(target_branch)

            # Perform the merge
            self._repo_ctrl.merge_branch(source_branch)

            # Success: sidebar + graph are refreshed by _on_branch_changed
            QMessageBox.information(
                self, "Merge Complete",
                f"Successfully merged <b>{source_branch}</b> into <b>{target_branch}</b>.",
            )

        except git.GitCommandError as exc:
            stderr = exc.stderr.strip() if exc.stderr else str(exc)
            if self._staging_ctrl.is_merging:
                # Merge failed with conflicts — refresh staging to show conflict files
                self._staging_ctrl.status_changed.emit()
                self._check_conflict_state()
                QMessageBox.warning(
                    self,
                    "Merge Conflict",
                    f"Conflicts detected while merging <b>{source_branch}</b> into "
                    f"<b>{target_branch}</b>.<br><br>"
                    "Resolve the highlighted conflicts, stage the files, then commit.<br>"
                    "Or click <b>Abort Merge</b> in the banner to cancel.",
                )
            else:
                QMessageBox.critical(self, "Merge Failed", f"<pre>{stderr}</pre>")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Merge Error", str(exc))

    # ── Commit graph pagination ───────────────────────────────────────

    def _on_load_more_commits(self, current_count: int) -> None:
        """Load the next page of commits and append them to the graph."""
        new_commits = self._repo_ctrl.load_commits(
            max_count=self._GRAPH_PAGE_SIZE + 1,
            skip=current_count,
        )
        has_more = len(new_commits) > self._GRAPH_PAGE_SIZE
        if new_commits:
            self._graph_widget.append_commits(
                new_commits[: self._GRAPH_PAGE_SIZE], has_more=has_more
            )

    # ── Toolbar action slots ──────────────────────────────────────────

    def _action_create_branch(self) -> None:
        """Branch toolbar button: prompt for a name and create a new branch."""
        name, ok = QInputDialog.getText(
            self, self.tr("New Branch"), self.tr("Branch name:"), text=""
        )
        if not ok or not name.strip():
            return
        try:
            self._toolbar_ctrl.create_branch(name.strip())
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Branch Error", str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Branch Failed",
                f"<pre>{exc.stderr.strip()}</pre>" if exc.stderr else str(exc),
            )

    def _action_undo_navigation(self) -> None:
        try:
            if not self._confirm_branch_switch(self.tr("the previous location")):
                return
            label = self._repo_ctrl.undo_navigation()
            self._populate_sidebar()
            self._reload_graph()
            self._staging_ctrl.status_changed.emit()
            self.statusBar().showMessage(
                self.tr("Checked out previous location: {0}").format(label)
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, self.tr("Undo"), str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self,
                self.tr("Undo Failed"),
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )

    def _action_redo_navigation(self) -> None:
        try:
            if not self._confirm_branch_switch(self.tr("the next location")):
                return
            label = self._repo_ctrl.redo_navigation()
            self._populate_sidebar()
            self._reload_graph()
            self._staging_ctrl.status_changed.emit()
            self.statusBar().showMessage(
                self.tr("Re-applied checkout: {0}").format(label)
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, self.tr("Redo"), str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self,
                self.tr("Redo Failed"),
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )

    def _action_stash_changes(self) -> None:
        """Stash toolbar button: push current changes onto the stash."""
        try:
            self._toolbar_ctrl.stash()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Stash Error", str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Stash Failed",
                f"<pre>{exc.stderr.strip()}</pre>" if exc.stderr else str(exc),
            )

    def _action_pop_stash(self) -> None:
        """Pop toolbar button: apply and drop the most-recent stash."""
        try:
            self._toolbar_ctrl.pop_stash()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Pop Error", str(exc))
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self, "Pop Failed",
                f"<pre>{exc.stderr.strip()}</pre>" if exc.stderr else str(exc),
            )

    # ── Toolbar controller signal handlers ────────────────────────────

    def _set_toolbar_enabled(self, enabled: bool) -> None:
        """Enable or disable all git toolbar actions."""
        if enabled:
            self._refresh_action_states()
            return
        for action in self._git_actions:
            action.setEnabled(False)

    def _on_toolbar_started(self, op_name: str) -> None:
        """Disable toolbar and show a wait cursor while a network op runs."""
        self._set_toolbar_enabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._repo_status_label.setText(f"{op_name}…")

    def _on_toolbar_finished(self, op_name: str, detail: str) -> None:
        """Re-enable toolbar and show a success message."""
        QApplication.restoreOverrideCursor()
        self._refresh_sync_badges()
        self._refresh_action_states()
        self._update_repo_status_label()
        QMessageBox.information(self, op_name, detail or f"{op_name} completed.")

    def _on_toolbar_failed(self, op_name: str, error: str) -> None:
        """Re-enable toolbar and show an error message."""
        QApplication.restoreOverrideCursor()
        self._refresh_sync_badges()
        self._refresh_action_states()
        self._update_repo_status_label()
        QMessageBox.critical(self, f"{op_name} Failed", error)

    def _on_toolbar_refs_changed(self) -> None:
        """Remote refs changed: reload sidebar and commit graph."""
        self._populate_sidebar()
        self._reload_graph()
        self._refresh_sync_badges()

    def _on_refs_updated(self) -> None:
        """Tags created/deleted: refresh sidebar + graph badges."""
        self._populate_sidebar()
        self._reload_graph()
        self._refresh_sync_badges()

    def _reload_graph(self) -> None:
        """Helper: reload the first page of commits with up-to-date tag badges."""
        commits = self._repo_ctrl.load_commits(max_count=self._GRAPH_PAGE_SIZE + 1)
        has_more = len(commits) > self._GRAPH_PAGE_SIZE
        self._graph_widget.populate(
            commits[: self._GRAPH_PAGE_SIZE],
            has_more=has_more,
            tags_by_hash=self._repo_ctrl.tags_for_commit(),
        )

    def _on_toolbar_working_tree_changed(self) -> None:
        """Working tree changed (pull / pop): refresh staging area."""
        self._sync_working_tree_now()
        self._refresh_sync_badges()

    def _poll_working_tree_status(self) -> None:
        """Refresh the right panel when the repo changes on disk outside the app."""
        if not self._repo_ctrl.is_open or self._toolbar_ctrl.is_busy:
            return
        signature = self._staging_ctrl.status_signature()
        if signature != self._last_working_tree_signature:
            self._last_working_tree_signature = signature
            self._staging_ctrl.status_changed.emit()

    def _sync_working_tree_now(self) -> None:
        """Force a right-panel refresh and store the latest status signature."""
        self._last_working_tree_signature = self._staging_ctrl.status_signature()
        self._staging_ctrl.status_changed.emit()

    def _refresh_sync_badges(self) -> None:
        """Update toolbar counters for incoming/outgoing commits."""
        outgoing = len(self._repo_ctrl.outgoing_commits()) if self._repo_ctrl.is_open else 0
        incoming = len(self._repo_ctrl.incoming_commits()) if self._repo_ctrl.is_open else 0

        push_text = self.tr("Push")
        pull_text = self.tr("Pull")
        if outgoing > 0:
            push_text = self.tr("Push ({0})").format(outgoing)
        if incoming > 0:
            pull_text = self.tr("Pull ({0})").format(incoming)

        self._action_push.setText(push_text)
        self._action_pull.setText(pull_text)
        self._action_push.setToolTip(
            self.tr("Push current branch to its upstream")
            + (self.tr(" — {0} local commit(s) waiting").format(outgoing) if outgoing else "")
        )
        self._action_pull.setToolTip(
            self.tr("Pull current branch (git pull --ff-only)")
            + (self.tr(" — {0} remote commit(s) available").format(incoming) if incoming else "")
        )

    def _format_commit_preview(self, commits: list) -> str:
        """Render a short commit list for confirmation dialogs."""
        preview = [f"• {commit.short_hash}  {commit.message}" for commit in commits[:12]]
        if len(commits) > 12:
            preview.append(self.tr("• …and {0} more").format(len(commits) - 12))
        return "\n".join(preview)

    def _action_push_with_confirmation(self) -> None:
        commits = self._repo_ctrl.outgoing_commits()
        if not commits:
            QMessageBox.information(
                self,
                self.tr("Push"),
                self.tr("There are no local commits waiting to be pushed."),
            )
            self._refresh_sync_badges()
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Push"),
            self.tr("Push {0} commit(s) to the upstream branch?\n\n{1}").format(
                len(commits),
                self._format_commit_preview(commits),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._toolbar_ctrl.push()

    def _action_pull_with_confirmation(self) -> None:
        commits = self._repo_ctrl.incoming_commits()
        if not commits:
            QMessageBox.information(
                self,
                self.tr("Pull"),
                self.tr("There are no remote commits to pull right now."),
            )
            self._refresh_sync_badges()
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Pull"),
            self.tr("Pull {0} commit(s) from the upstream branch?\n\n{1}").format(
                len(commits),
                self._format_commit_preview(commits),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._toolbar_ctrl.pull()

    # ── Recent repositories (Phase 12) ───────────────────────────────

    def _refresh_repo_combo(self) -> None:
        """Rebuild the recent-repos combo box from the persisted list."""
        self._repo_combo.blockSignals(True)
        self._repo_combo.clear()

        entries = self._recent_repos.get_all()
        current_path = self._repo_ctrl.repo_path  # "" when nothing is open

        if not entries and not current_path:
            self._repo_combo.addItem(self.tr("No recent repositories"), "")
            self._repo_combo.setEnabled(False)
        else:
            self._repo_combo.setEnabled(True)
            current_idx = 0

            # If the current repo is not in the list yet, show it first
            if current_path and not any(e["path"] == current_path for e in entries):
                from pathlib import Path
                self._repo_combo.addItem(Path(current_path).name, current_path)

            for entry in entries:
                self._repo_combo.addItem(entry["name"], entry["path"])
                if entry["path"] == current_path:
                    current_idx = self._repo_combo.count() - 1

            self._repo_combo.setCurrentIndex(current_idx)

            # Separator (disabled item)
            sep_idx = self._repo_combo.count()
            self._repo_combo.addItem("──────────────────", None)
            self._repo_combo.model().item(sep_idx).setEnabled(False)

            # Clear action
            self._repo_combo.addItem(
                self.tr("✕  Clear Recent Repositories"), "__CLEAR__"
            )

        self._repo_combo.blockSignals(False)

    def _on_combo_activated(self, index: int) -> None:
        """Handle user selection in the recent-repos combo."""
        data = self._repo_combo.itemData(index)
        if data is None or data == "":
            return
        if data == "__CLEAR__":
            self._action_clear_recent()
            return
        path: str = str(data)
        # No-op if it's the already-open repo
        if self._repo_ctrl.is_open and self._repo_ctrl.repo_path == path:
            return
        self._open_recent_repo(path)

    def _open_recent_repo(self, path: str) -> None:
        """Open *path* as a repository, handling common error cases."""
        try:
            self._repo_ctrl.open_repo(path)
        except git.InvalidGitRepositoryError:
            QMessageBox.warning(
                self, self.tr("Not a Git Repository"),
                self.tr("The path is no longer a valid Git repository:\n\n{0}").format(path),
            )
            self._recent_repos.get_all()   # prunes stale entry
            self._refresh_repo_combo()
        except git.NoSuchPathError:
            QMessageBox.warning(
                self, self.tr("Path Not Found"),
                self.tr("The repository path no longer exists:\n\n{0}").format(path),
            )
            self._recent_repos.get_all()
            self._refresh_repo_combo()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Error Opening Repository"), str(exc))

    def _action_clear_recent(self) -> None:
        """Ask for confirmation and clear the recent-repos list."""
        reply = QMessageBox.question(
            self,
            self.tr("Clear Recent Repositories"),
            self.tr("Remove all entries from the recent repositories list?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._recent_repos.clear()
            self._refresh_repo_combo()

    def _rebuild_recent_menu(self) -> None:
        """Populate the File → Recent Repositories submenu on demand."""
        self._recent_menu.clear()
        entries = self._recent_repos.get_all()
        if not entries:
            empty_action = QAction(self.tr("No recent repositories"), self)
            empty_action.setEnabled(False)
            self._recent_menu.addAction(empty_action)
            return
        for entry in entries:
            action = QAction(entry["name"], self)
            action.setToolTip(entry["path"])
            _path = entry["path"]
            action.triggered.connect(lambda _checked, p=_path: self._open_recent_repo(p))
            self._recent_menu.addAction(action)

    # ── Tag management (Phase 15) ─────────────────────────────────────

    def _on_checkout_tag_requested(self, tag_name: str) -> None:
        """Sidebar double-click or context menu → checkout a tag (detached HEAD)."""
        reply = QMessageBox.warning(
            self, self.tr("Checkout Tag"),
            f"Checking out tag <b>{tag_name}</b> will put the repository in "
            "<b>detached HEAD</b> state.<br><br>"
            "You will not be on any branch. Any commits you make will not belong "
            "to a branch and may be lost.<br><br>Proceed?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return
        try:
            self._repo_ctrl.checkout_tag(tag_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Checkout Failed"), str(exc))

    def _on_create_tag(self, full_hash: str) -> None:
        """CommitGraphWidget.create_tag_requested → show dialog and create tag."""
        name, ok = QInputDialog.getText(
            self, self.tr("Create Tag"), self.tr("Tag name (e.g. v1.0.0):")
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        message, ok2 = QInputDialog.getText(
            self,
            self.tr("Tag Message"),
            self.tr("Annotation message (leave empty for a lightweight tag):"),
        )
        message = message.strip() if ok2 else ""

        try:
            self._repo_ctrl.create_tag(name, ref=full_hash, message=message)
            self._populate_sidebar()
            self._reload_graph_with_tags()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Create Tag Failed"), str(exc))

    def _on_delete_tag(self, tag_name: str) -> None:
        """Sidebar delete_tag_requested → delete local tag."""
        try:
            self._repo_ctrl.delete_tag(tag_name)
            self._populate_sidebar()
            self._reload_graph_with_tags()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Delete Tag Failed"), str(exc))

    def _on_push_tag(self, tag_name: str) -> None:
        """Sidebar push_tag_requested → push tag to a selected remote."""
        if not self._repo_ctrl.is_open:
            return
        remote_names = self._repo_ctrl.remote_names()
        if not remote_names:
            QMessageBox.warning(self, self.tr("No Remote"), self.tr("This repository has no configured remotes."))
            return
        remote_name = remote_names[0]
        if len(remote_names) > 1:
            chosen, ok = QInputDialog.getItem(
                self,
                self.tr("Push Tag"),
                self.tr("Remote:"),
                remote_names,
                0,
                False,
            )
            if not ok:
                return
            remote_name = chosen
        active = self._profile_ctrl.active_profile
        from src.utils.credentials import AuthMethod, get_token

        ssh_key = ""
        https_username = ""
        https_token = ""
        if active:
            if active.auth_method == AuthMethod.HTTPS:
                https_username = active.https_username
                https_token = get_token(https_username)
            elif active.auth_method == AuthMethod.SSH:
                ssh_key = active.ssh_key_path or ""
        try:
            self._repo_ctrl.push_tag(
                tag_name,
                remote_name=remote_name,
                ssh_key_path=ssh_key,
                https_username=https_username,
                https_token=https_token,
            )
            QMessageBox.information(
                self,
                self.tr("Push Tag"),
                self.tr("Tag <b>{0}</b> successfully pushed to <b>{1}</b>.").format(
                    tag_name, remote_name
                ),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Push Tag Failed"), str(exc))

    def _on_create_branch_from_commit(self, full_hash: str) -> None:
        name, ok = QInputDialog.getText(
            self, self.tr("Create Branch"), self.tr("New branch name:"), text=""
        )
        if not ok or not name.strip():
            return
        try:
            self._repo_ctrl.create_branch_at_ref(name.strip(), full_hash)
            self._populate_sidebar()
            self._reload_graph()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Create Branch Failed"), str(exc))

    def _on_create_branch_from_tag(self, tag_name: str, branch_name: str) -> None:
        try:
            self._repo_ctrl.create_branch_at_ref(branch_name, tag_name)
            self._populate_sidebar()
            self._reload_graph()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Create Branch Failed"), str(exc))

    def _reload_graph_with_tags(self) -> None:
        """Reload the commit graph keeping tag badges up to date."""
        commits = self._repo_ctrl.load_commits(max_count=self._GRAPH_PAGE_SIZE + 1)
        has_more = len(commits) > self._GRAPH_PAGE_SIZE
        self._graph_widget.populate(
            commits[: self._GRAPH_PAGE_SIZE],
            has_more=has_more,
            tags_by_hash=self._repo_ctrl.tags_for_commit(),
        )

    # ── Settings (Phase 13) ───────────────────────────────────────────

    def _open_settings_dialog(self) -> None:
        """Open the Settings dialog (Ctrl+,)."""
        SettingsDialog(parent=self).exec()

    # ── UI helpers ────────────────────────────────────────────────────

    def _confirm_branch_switch(self, destination: str) -> bool:
        """Ask permission to discard local changes before a checkout-like action."""
        if not self._repo_ctrl.is_open or not self._repo_ctrl.has_pending_changes():
            return True

        unstaged = [entry.path for entry in self._staging_ctrl.get_unstaged()]
        staged = [entry.path for entry in self._staging_ctrl.get_staged()]
        pending_paths = sorted(set(unstaged + staged))
        preview = "\n".join(f"• {path}" for path in pending_paths[:10])
        if len(pending_paths) > 10:
            preview += "\n" + self.tr("• …and {0} more").format(len(pending_paths) - 10)

        reply = QMessageBox.warning(
            self,
            self.tr("Discard Local Changes?"),
            self.tr(
                "Switching to <b>{0}</b> requires discarding the local changes currently pending."
                "<br><br>These changes will be removed by the application before the branch switch."
                "<br><br>{1}<br><br>Continue?"
            ).format(destination, preview.replace("\n", "<br>")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        try:
            self._repo_ctrl.discard_all_changes()
            self._sync_working_tree_now()
            return True
        except git.GitCommandError as exc:
            QMessageBox.critical(
                self,
                self.tr("Discard Failed"),
                f"<pre>{exc.stderr.strip() if exc.stderr else str(exc)}</pre>",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Discard Failed"), str(exc))
        return False

    def _populate_sidebar(self) -> None:
        """Ask the sidebar to rebuild itself from the current repo state."""
        ctrl = self._repo_ctrl
        self._sidebar.populate(
            repo_name=ctrl.repo_name,
            local_branches=ctrl.local_branches(),
            remote_branches=ctrl.remote_branches(),
            tags=ctrl.tags(),
            submodules=ctrl.submodules(),
            active_branch=ctrl.current_branch_name,
        )

    def _update_window_title(self) -> None:
        if self._repo_ctrl.is_open:
            self.setWindowTitle(f"ubuntu-gitgui — {self._repo_ctrl.repo_name}")
        else:
            self.setWindowTitle("ubuntu-gitgui")

    def _update_repo_status_label(self) -> None:
        if self._repo_ctrl.is_open:
            state = self._repo_ctrl.state
            self._repo_status_label.setText(self._repo_ctrl.repo_path)
            suffix = ""
            if state.branch_state == BranchState.DETACHED:
                suffix = self.tr("detached HEAD")
            elif state.branch_state == BranchState.NO_REMOTE:
                suffix = self.tr("no remote")
            elif state.branch_state == BranchState.NO_UPSTREAM:
                suffix = self.tr("no upstream")
            elif state.upstream_name:
                suffix = state.upstream_name
                incoming = len(self._repo_ctrl.incoming_commits())
                outgoing = len(self._repo_ctrl.outgoing_commits())
                sync_parts: list[str] = []
                if outgoing:
                    sync_parts.append(self.tr("↑{0}").format(outgoing))
                if incoming:
                    sync_parts.append(self.tr("↓{0}").format(incoming))
                if sync_parts:
                    suffix = f"{suffix}  ·  {' '.join(sync_parts)}"
            label = state.display_name or self._repo_ctrl.current_branch_name
            self._branch_status_label.setText(f"   ⎇  {label}" + (f"  ·  {suffix}" if suffix else ""))
            self._branch_status_label.show()
        else:
            self._repo_status_label.setText(self.tr("No repository open"))
            self._branch_status_label.hide()

    def _refresh_profile_status(self) -> None:
        active = self._profile_ctrl.active_profile
        if active:
            self._profile_status_label.setText(
                f"  👤  {active.name}  ({active.git_email})"
            )
        else:
            self._profile_status_label.setText(self.tr("  👤  No active profile"))

    def _refresh_action_states(self) -> None:
        if self._clone_in_progress:
            for action in self._git_actions:
                action.setEnabled(False)
            return
        if not self._repo_ctrl.is_open:
            for action in self._git_actions:
                action.setEnabled(False)
            return

        state = self._repo_ctrl.state
        self._action_fetch.setEnabled(True)
        self._action_pull.setEnabled(state.can_pull and not self._toolbar_ctrl.is_busy)
        self._action_commit.setEnabled(not self._toolbar_ctrl.is_busy)
        self._action_push.setEnabled(state.can_push and not self._toolbar_ctrl.is_busy)
        self._action_branch.setEnabled(True)
        self._action_stash.setEnabled(not self._toolbar_ctrl.is_busy)
        self._action_pop.setEnabled(not self._toolbar_ctrl.is_busy)
        self._action_undo_nav.setEnabled(self._repo_ctrl.can_undo_navigation())
        self._action_redo_nav.setEnabled(self._repo_ctrl.can_redo_navigation())
