"""
RepositoryController — business logic for repository lifecycle and navigation.

Responsibilities:
  - Open an existing local repository
  - Initialise a new empty repository
  - Clone a remote repository (blocking, with cursor feedback)
  - Provide read access to local branches, remote branches and tags
  - Perform git checkout on a local branch
  - Emit Qt signals so connected views stay in sync

Signals overview:
    repo_opened(path: str)       — a repository was successfully loaded
    repo_closed()                — the repository was unloaded
    branch_changed(name: str)    — HEAD moved to a different branch
    refs_updated()               — branches/tags lists changed (e.g. after fetch)

Usage (from MainWindow):
    self._repo_ctrl = RepositoryController(parent=self)
    self._repo_ctrl.repo_opened.connect(self._on_repo_opened)
    self._repo_ctrl.open_repo("/path/to/my/project")
"""

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import git
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from src.models.commit_graph import CommitData


class BranchState(str, Enum):
    """High-level repository HEAD state used by the UI."""

    NO_REPO = "no_repo"
    DETACHED = "detached"
    NO_REMOTE = "no_remote"
    NO_UPSTREAM = "no_upstream"
    READY = "ready"


@dataclass(frozen=True)
class RepositoryState:
    """Snapshot of the currently opened repository state for UI decisions."""

    branch_state: BranchState
    branch_name: str = ""
    display_name: str = ""
    remote_names: tuple[str, ...] = ()
    upstream_name: str = ""

    @property
    def can_pull(self) -> bool:
        return self.branch_state == BranchState.READY

    @property
    def can_push(self) -> bool:
        return self.branch_state == BranchState.READY

    @property
    def is_detached(self) -> bool:
        return self.branch_state == BranchState.DETACHED


class _CloneWorker(QObject):
    """Runs a clone operation on a dedicated thread."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    @pyqtSlot(str, str, str, str, str)
    def clone(
        self,
        url: str,
        destination: str,
        ssh_key_path: str,
        https_username: str,
        https_token: str,
    ) -> None:
        from src.utils.credentials import AskPassScript

        try:
            env: dict[str, str] = {}
            if ssh_key_path:
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {shlex.quote(ssh_key_path)} -o IdentitiesOnly=yes"
                )

            if https_username and https_token:
                askpass = AskPassScript(https_username, https_token)
                script_path = askpass.__enter__()
                try:
                    env["GIT_ASKPASS"] = script_path
                    env["GIT_TERMINAL_PROMPT"] = "0"
                    repo = git.Repo.clone_from(url, destination, env=env)
                finally:
                    askpass.__exit__(None, None, None)
            else:
                repo = git.Repo.clone_from(url, destination, env=env if env else None)
            self.finished.emit(repo)
        except git.GitCommandError as exc:
            self.failed.emit(exc.stderr.strip() if exc.stderr else str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class RepositoryController(QObject):
    """Manages a single open Git repository and exposes branch/tag data.

    Only one repository is active at a time. Re-opening replaces the current one.
    """

    # ── Qt signals ────────────────────────────────────────────────────
    repo_opened = pyqtSignal(str)   # payload: absolute repo path
    repo_closed = pyqtSignal()
    branch_changed = pyqtSignal(str)  # payload: new branch name (or commit hash if detached)
    refs_updated = pyqtSignal()       # branch list or tag list changed
    state_changed = pyqtSignal(object)  # payload: RepositoryState
    clone_started = pyqtSignal(str, str)  # (url, destination)
    clone_finished = pyqtSignal(str)  # repo path
    clone_failed = pyqtSignal(str)
    _request_clone = pyqtSignal(str, str, str, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repo: git.Repo | None = None
        self._clone_thread = QThread(self)
        self._clone_worker = _CloneWorker()
        self._clone_worker.moveToThread(self._clone_thread)
        self._request_clone.connect(self._clone_worker.clone)
        self._clone_worker.finished.connect(self._on_clone_finished)
        self._clone_worker.failed.connect(self._on_clone_failed)
        self._clone_thread.start()
        self.destroyed.connect(self._shutdown_thread)
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []

    def _shutdown_thread(self) -> None:
        self._clone_thread.quit()
        self._clone_thread.wait(3000)

    # ── Public properties ─────────────────────────────────────────────

    @property
    def repo(self) -> git.Repo | None:
        """The currently open GitPython Repo, or None."""
        return self._repo

    @property
    def is_open(self) -> bool:
        """True when a valid repository is loaded."""
        return self._repo is not None

    @property
    def repo_path(self) -> str:
        """Absolute path of the working tree, or empty string."""
        if self._repo is None:
            return ""
        return str(self._repo.working_tree_dir)

    @property
    def repo_name(self) -> str:
        """Display name (last path component of the working tree)."""
        path = self.repo_path
        return Path(path).name if path else ""

    @property
    def current_branch_name(self) -> str:
        """Name of the currently checked-out branch, or the short commit hash
        if the repo is in detached-HEAD state."""
        if self._repo is None:
            return ""
        try:
            return self._repo.active_branch.name
        except TypeError:
            # Detached HEAD — return the short SHA instead
            return self._repo.head.commit.hexsha[:7]

    @property
    def state(self) -> RepositoryState:
        """Return a high-level repository state snapshot for the UI."""
        if self._repo is None:
            return RepositoryState(branch_state=BranchState.NO_REPO)

        remote_names = tuple(remote.name for remote in self._repo.remotes)
        try:
            branch = self._repo.active_branch
            upstream = branch.tracking_branch()
            upstream_name = upstream.name if upstream is not None else ""
            branch_state = (
                BranchState.NO_REMOTE
                if not remote_names
                else BranchState.NO_UPSTREAM
                if upstream is None
                else BranchState.READY
            )
            return RepositoryState(
                branch_state=branch_state,
                branch_name=branch.name,
                display_name=branch.name,
                remote_names=remote_names,
                upstream_name=upstream_name,
            )
        except TypeError:
            short_hash = self._repo.head.commit.hexsha[:7]
            return RepositoryState(
                branch_state=BranchState.DETACHED,
                branch_name=short_hash,
                display_name=f"HEAD ({short_hash})",
                remote_names=remote_names,
            )

    def remote_names(self) -> list[str]:
        if self._repo is None:
            return []
        return [remote.name for remote in self._repo.remotes]

    def submodules(self) -> list[str]:
        if self._repo is None:
            return []
        try:
            return sorted(submodule.name for submodule in self._repo.submodules)
        except Exception:  # noqa: BLE001
            return []

    def can_undo_navigation(self) -> bool:
        return bool(self._undo_stack)

    def can_redo_navigation(self) -> bool:
        return bool(self._redo_stack)

    # ── Repository lifecycle ──────────────────────────────────────────

    def open_repo(self, path: str) -> None:
        """Open an existing repository at *path*.

        Raises:
            git.InvalidGitRepositoryError: if *path* is not a Git repository.
            git.NoSuchPathError: if *path* does not exist.
        """
        self._repo = git.Repo(path, search_parent_directories=True)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.repo_opened.emit(str(self._repo.working_tree_dir))
        self.state_changed.emit(self.state)

    def init_repo(self, path: str) -> None:
        """Initialise a brand-new repository at *path* and open it.

        Creates the directory if it does not yet exist.
        """
        Path(path).mkdir(parents=True, exist_ok=True)
        self._repo = git.Repo.init(path)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.repo_opened.emit(str(self._repo.working_tree_dir))
        self.state_changed.emit(self.state)

    def start_clone(
        self,
        url: str,
        destination: str,
        ssh_key_path: str = "",
        https_username: str = "",
        https_token: str = "",
    ) -> None:
        """Clone *url* into *destination* asynchronously."""
        self.clone_started.emit(url, destination)
        self._request_clone.emit(
            url, destination, ssh_key_path, https_username, https_token
        )

    def close_repo(self) -> None:
        """Unload the current repository."""
        if self._repo is not None:
            self._repo.close()
            self._repo = None
            self._undo_stack.clear()
            self._redo_stack.clear()
            self.repo_closed.emit()
            self.state_changed.emit(self.state)

    @pyqtSlot(object)
    def _on_clone_finished(self, repo: git.Repo) -> None:
        self._repo = repo
        self._undo_stack.clear()
        self._redo_stack.clear()
        repo_path = str(self._repo.working_tree_dir)
        self.repo_opened.emit(repo_path)
        self.state_changed.emit(self.state)
        self.clone_finished.emit(repo_path)

    @pyqtSlot(str)
    def _on_clone_failed(self, message: str) -> None:
        self.clone_failed.emit(message)

    # ── Branch and tag data ───────────────────────────────────────────

    def local_branches(self) -> list[str]:
        """Return a sorted list of local branch names."""
        if self._repo is None:
            return []
        return sorted(b.name for b in self._repo.branches)  # type: ignore[attr-defined]

    def remote_branches(self) -> list[str]:
        """Return a sorted list of remote-tracking branch names (e.g. origin/main)."""
        if self._repo is None:
            return []
        from git.refs.remote import RemoteReference
        return sorted(
            ref.name for ref in self._repo.refs
            if isinstance(ref, RemoteReference)
        )

    def tags(self) -> list[str]:
        """Return a sorted list of tag names."""
        if self._repo is None:
            return []
        return sorted(t.name for t in self._repo.tags)

    def has_pending_changes(self) -> bool:
        """Return True when the working tree or index contains local changes."""
        if self._repo is None:
            return False
        return self._repo.is_dirty(untracked_files=True)

    def discard_all_changes(self) -> None:
        """Discard all tracked and untracked local changes in the current repo."""
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._repo.git.reset("--hard")
        self._repo.git.clean("-fd")

    def outgoing_commits(self) -> list[CommitData]:
        """Return commits reachable locally but not yet present on the upstream."""
        if self._repo is None:
            return []
        try:
            branch = self._repo.active_branch
        except TypeError:
            return []
        upstream = branch.tracking_branch()
        if upstream is None:
            return []
        return self._load_commit_range(f"{upstream.name}..{branch.name}")

    def incoming_commits(self) -> list[CommitData]:
        """Return commits present on the upstream but not yet merged locally."""
        if self._repo is None:
            return []
        try:
            branch = self._repo.active_branch
        except TypeError:
            return []
        upstream = branch.tracking_branch()
        if upstream is None:
            return []
        return self._load_commit_range(f"{branch.name}..{upstream.name}")

    # ── Commit history ───────────────────────────────────────────────

    def load_commits(self, max_count: int = 100, skip: int = 0) -> list[CommitData]:
        """Return up to *max_count* commits from all refs, newest first.

        Uses ``--topo-order`` so that the layout algorithm sees children
        before their parents, which is required for correct lane assignment.

        Returns an empty list if the repository has no commits yet or if
        any error occurs during enumeration.

        Args:
            max_count: Maximum number of commits to load (default 100).
            skip:      Number of commits to skip from the start (for pagination).
        """
        if self._repo is None:
            return []

        result: list[CommitData] = []
        try:
            for commit in self._repo.iter_commits(
                "--all", topo_order=True, max_count=max_count, skip=skip
            ):
                result.append(
                    CommitData(
                        full_hash=commit.hexsha,
                        short_hash=commit.hexsha[:7],
                        message=commit.message.split("\n")[0].strip(),
                        author=commit.author.name,
                        date=commit.committed_datetime.strftime("%Y-%m-%d %H:%M"),
                        parent_hashes=tuple(p.hexsha for p in commit.parents),
                    )
                )
        except git.GitCommandError:
            # Raised on repos with no commits (empty repo after git init)
            pass

        return result

    def _load_commit_range(self, revspec: str, max_count: int = 50) -> list[CommitData]:
        """Return commit metadata for *revspec* using the same shape as the graph."""
        if self._repo is None:
            return []

        result: list[CommitData] = []
        try:
            for commit in self._repo.iter_commits(revspec, max_count=max_count):
                result.append(
                    CommitData(
                        full_hash=commit.hexsha,
                        short_hash=commit.hexsha[:7],
                        message=commit.message.split("\n")[0].strip(),
                        author=commit.author.name,
                        date=commit.committed_datetime.strftime("%Y-%m-%d %H:%M"),
                        parent_hashes=tuple(p.hexsha for p in commit.parents),
                    )
                )
        except git.GitCommandError:
            return []
        return result

    # ── Merge ─────────────────────────────────────────────────────────

    def merge_branch(self, source_branch: str) -> None:
        """Merge *source_branch* into the currently checked-out branch.

        The caller is responsible for checking out the target branch first.

        Args:
            source_branch: Name of the local branch to merge in.

        Raises:
            RuntimeError:          if no repo is open.
            git.GitCommandError:   on merge failure (including conflicts).
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._repo.git.merge(source_branch)
        self.branch_changed.emit(self.current_branch_name)
        self.state_changed.emit(self.state)

    # ── Checkout ─────────────────────────────────────────────────────

    def checkout_branch(self, branch_name: str) -> None:
        """Checkout the given local branch.

        Args:
            branch_name: Name of the local branch to check out (e.g. "main").

        Raises:
            git.GitCommandError: if the checkout fails (e.g. unstaged changes
                that would be overwritten, or the branch does not exist).
            RuntimeError: if no repository is currently open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")

        # Avoid a no-op checkout (already on the requested branch)
        if self.current_branch_name == branch_name:
            return

        self._remember_navigation_origin()
        self._repo.git.checkout(branch_name)
        self.branch_changed.emit(branch_name)
        self.state_changed.emit(self.state)

    def checkout_tag(self, tag_name: str) -> None:
        """Checkout a tag, entering detached HEAD state.

        Args:
            tag_name: Name of the tag to check out.

        Raises:
            git.GitCommandError: if the checkout fails.
            RuntimeError: if no repository is currently open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._remember_navigation_origin()
        self._repo.git.checkout(tag_name)
        short_hash = self._repo.head.commit.hexsha[:7]
        self.branch_changed.emit(f"HEAD ({short_hash})")
        self.state_changed.emit(self.state)

    def checkout_commit(self, full_hash: str) -> None:
        """Checkout a commit in detached HEAD state."""
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._remember_navigation_origin()
        self._repo.git.checkout(full_hash)
        self.branch_changed.emit(f"HEAD ({full_hash[:7]})")
        self.state_changed.emit(self.state)

    def checkout_remote_branch(self, remote_ref: str) -> str:
        """Create a local tracking branch from *remote_ref* and check it out.

        For example, ``remote_ref = "origin/feature"`` creates a local branch
        ``feature`` tracking ``origin/feature`` and switches to it.

        If a local branch with the derived name already exists, the method
        simply checks it out (no new branch is created).

        Args:
            remote_ref: Full remote-tracking ref, e.g. ``"origin/feature"``.

        Returns:
            The local branch name that was checked out.

        Raises:
            git.GitCommandError: if git reports any error.
            RuntimeError: if no repository is currently open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")

        # Derive local name from "remote/branch" (first slash is the delimiter)
        parts = remote_ref.split("/", 1)
        local_name = parts[1] if len(parts) == 2 else remote_ref

        existing_names = [b.name for b in self._repo.branches]  # type: ignore[attr-defined]
        if local_name in existing_names:
            # Local branch already exists — just switch to it
            if self.current_branch_name != local_name:
                self._remember_navigation_origin()
                self._repo.git.checkout(local_name)
        else:
            # Create a new local branch tracking the remote ref
            self._remember_navigation_origin()
            self._repo.git.checkout("-b", local_name, "--track", remote_ref)

        self.branch_changed.emit(local_name)
        self.state_changed.emit(self.state)
        return local_name

    def create_branch_at_ref(self, name: str, ref: str) -> None:
        """Create and checkout a new branch at the given ref."""
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._remember_navigation_origin()
        self._repo.git.checkout("-b", name.strip(), ref)
        self.refs_updated.emit()
        self.branch_changed.emit(name.strip())
        self.state_changed.emit(self.state)

    def undo_navigation(self) -> str:
        """Checkout the previous navigation target recorded in this session."""
        if self._repo is None:
            raise RuntimeError("No repository open.")
        if not self._undo_stack:
            raise RuntimeError("Nothing to undo.")
        current = self._current_ref()
        target = self._undo_stack.pop()
        if current:
            self._redo_stack.append(current)
        self._repo.git.checkout(target)
        self.branch_changed.emit(self.state.display_name)
        self.state_changed.emit(self.state)
        return self.state.display_name

    def redo_navigation(self) -> str:
        """Re-apply the most recently undone navigation target."""
        if self._repo is None:
            raise RuntimeError("No repository open.")
        if not self._redo_stack:
            raise RuntimeError("Nothing to redo.")
        current = self._current_ref()
        target = self._redo_stack.pop()
        if current:
            self._undo_stack.append(current)
        self._repo.git.checkout(target)
        self.branch_changed.emit(self.state.display_name)
        self.state_changed.emit(self.state)
        return self.state.display_name

    # ── Tag management ────────────────────────────────────────────────

    def tags_for_commit(self) -> dict[str, list[str]]:
        """Return a mapping {full_commit_hash: [tag_name, ...]} for all tags.

        Annotated tags are resolved to their target commit automatically.
        """
        if self._repo is None:
            return {}
        result: dict[str, list[str]] = {}
        for tag in self._repo.tags:
            try:
                h = tag.commit.hexsha
                result.setdefault(h, []).append(tag.name)
            except Exception:  # noqa: BLE001
                pass
        return result

    def create_tag(self, name: str, ref: str, message: str = "") -> None:
        """Create a tag at *ref*.

        Creates an annotated tag when *message* is non-empty, otherwise a
        lightweight tag.

        Args:
            name:    Tag name (e.g. ``"v1.0.0"``).
            ref:     Commit hash or ref to tag.
            message: Optional annotation message (annotated tag).

        Raises:
            git.GitCommandError: if a tag with that name already exists or git
                reports any other error.
            RuntimeError: if no repository is currently open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        if message:
            self._repo.create_tag(name, ref=ref, message=message)
        else:
            self._repo.create_tag(name, ref=ref)
        self.refs_updated.emit()

    def delete_tag(self, name: str) -> None:
        """Delete a local tag by name.

        Args:
            name: Tag name to delete.

        Raises:
            git.GitCommandError: if the tag does not exist.
            RuntimeError: if no repository is currently open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._repo.delete_tag(name)
        self.refs_updated.emit()

    def push_tag(
        self,
        name: str,
        remote_name: str = "",
        ssh_key_path: str = "",
        https_username: str = "",
        https_token: str = "",
    ) -> None:
        """Push a single tag to the first configured remote.

        Supports both SSH and HTTPS auth using the same injection approach as
        the other network methods:
          - SSH:   GIT_SSH_COMMAND env var.
          - HTTPS: temporary GIT_ASKPASS script (deleted after push).

        Args:
            name:           Tag name to push (e.g. ``"v1.0.0"``).
            ssh_key_path:   SSH private key path (SSH auth).
            https_username: HTTPS username (HTTPS auth).
            https_token:    PAT / password (HTTPS auth).

        Raises:
            git.GitCommandError: on push failure.
            RuntimeError: if no repository is open or no remotes configured.
        """
        from src.utils.credentials import AskPassScript

        if self._repo is None:
            raise RuntimeError("No repository open.")
        if not self._repo.remotes:
            raise RuntimeError("No remote configured.")

        remote = remote_name or self._repo.remotes[0].name

        if https_username and https_token:
            askpass = AskPassScript(https_username, https_token)
            script_path = askpass.__enter__()
            try:
                with self._repo.git.custom_environment(
                    GIT_ASKPASS=script_path,
                    GIT_TERMINAL_PROMPT="0",
                ):
                    self._repo.git.push(remote, f"refs/tags/{name}")
            finally:
                askpass.__exit__(None, None, None)
        else:
            ssh_cmd = (
                f"ssh -i {shlex.quote(ssh_key_path)} -o IdentitiesOnly=yes"
                if ssh_key_path
                else ""
            )
            env_override = {"GIT_SSH_COMMAND": ssh_cmd} if ssh_cmd else {}
            with self._repo.git.custom_environment(**env_override):
                self._repo.git.push(remote, f"refs/tags/{name}")

    def _current_ref(self) -> str:
        if self._repo is None:
            return ""
        try:
            return self._repo.active_branch.name
        except TypeError:
            return self._repo.head.commit.hexsha

    def _remember_navigation_origin(self) -> None:
        current = self._current_ref()
        if current:
            if not self._undo_stack or self._undo_stack[-1] != current:
                self._undo_stack.append(current)
            self._redo_stack.clear()
