"""
ToolbarController — business logic for toolbar actions (Fetch, Pull, Push,
Branch, Stash, Pop).

Async strategy
──────────────
Network operations (Fetch, Pull, Push) run in a dedicated QThread to avoid
blocking the UI.  A lightweight _GitWorker QObject is moved onto the thread;
ToolbarController dispatches jobs by emitting a Qt signal that the worker
receives via a QueuedConnection (the normal cross-thread mechanism in PyQt6).

Sync operations (Branch, Stash, Pop) execute directly in the main thread
because they work only on the local repository and are fast.

Authentication
──────────────
The controller supports two auth methods, resolved from the active profile:

  SSH  — injects GIT_SSH_COMMAND into the worker's environment for the
         duration of each call, then restores the previous value.

  HTTPS — creates a temporary GIT_ASKPASS shell script (mode 700, owner-only)
          that echoes the username / token, sets GIT_ASKPASS and
          GIT_TERMINAL_PROMPT=0, then deletes the script in the finally block.
          The token is retrieved from the OS keyring just before dispatch and
          is passed as a dict to the worker (never logged).

The main thread's environment is never permanently mutated.

Signals (always delivered on the main thread via queued connections):
    operation_started(op_name)           — a git operation has begun
    operation_finished(op_name, detail)  — completed successfully
    operation_failed(op_name, detail)    — completed with an error
    refs_changed()                       — remote refs updated (fetch / pull)
    working_tree_changed()               — working tree changed (pull / pop)
"""

from __future__ import annotations

import shlex
from enum import Enum, auto
from typing import TYPE_CHECKING

import git
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from src.utils.credentials import AskPassScript, AuthMethod, get_token

if TYPE_CHECKING:
    from src.models.profile import Profile


# ── Op type enum ─────────────────────────────────────────────────────────────

class _Op(Enum):
    FETCH = auto()
    PULL  = auto()
    PUSH  = auto()


# ── Background worker ────────────────────────────────────────────────────────

class _GitWorker(QObject):
    """Executes a single git network operation on a background thread.

    Receives job requests via the ``_run`` signal (queued across threads) and
    emits ``finished`` / ``failed`` back to the main thread.

    The ``auth`` payload is a plain dict with the following schema:

        {"type": "none"}
        {"type": "ssh",   "key_path": "/path/to/key"}
        {"type": "https", "username": "user", "token": "ghp_..."}

    The HTTPS token value is obtained from the OS keyring by the controller
    in the main thread (before dispatch) and is carried inside the dict.
    """

    # Input signal: the controller enqueues work by emitting this
    _run = pyqtSignal(_Op, object, object)   # (op, repo, auth_dict)

    # Output signals: results forwarded to the main thread
    finished = pyqtSignal(_Op, str)   # (op, detail)
    failed   = pyqtSignal(_Op, str)   # (op, error_message)

    def __init__(self) -> None:
        super().__init__()
        self._run.connect(self._execute)

    @pyqtSlot(_Op, object, object)
    def _execute(self, op: _Op, repo: git.Repo, auth: dict) -> None:
        auth_type = auth.get("type", "none")
        askpass_ctx: AskPassScript | None = None
        env_override: dict[str, str] = {}

        try:
            # ── Apply auth ─────────────────────────────────────────
            if auth_type == "ssh":
                key = auth.get("key_path", "")
                if key:
                    env_override["GIT_SSH_COMMAND"] = (
                        f"ssh -i {shlex.quote(key)} -o IdentitiesOnly=yes"
                    )

            elif auth_type == "https":
                askpass_ctx = AskPassScript(auth["username"], auth["token"])
                script_path = askpass_ctx.__enter__()
                env_override["GIT_ASKPASS"] = script_path
                env_override["GIT_TERMINAL_PROMPT"] = "0"

            # ── Execute the git operation ──────────────────────────
            with repo.git.custom_environment(**env_override):
                if op is _Op.FETCH:
                    detail = self._fetch(repo)
                elif op is _Op.PULL:
                    detail = self._pull(repo)
                else:
                    detail = self._push(repo)

            self.finished.emit(op, detail)

        except git.GitCommandError as exc:
            msg = exc.stderr.strip() if exc.stderr else str(exc)
            self.failed.emit(op, msg)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(op, str(exc))

        finally:
            if askpass_ctx is not None:
                askpass_ctx.__exit__(None, None, None)

    # ── Git operations ────────────────────────────────────────────────

    @staticmethod
    def _fetch(repo: git.Repo) -> str:
        collected: list[str] = []
        for remote in repo.remotes:
            info = remote.fetch(prune=True)
            collected.extend(item.name for item in info)
        if collected:
            names = ", ".join(collected[:5])
            extra = f" (+{len(collected) - 5} more)" if len(collected) > 5 else ""
            return f"Fetched: {names}{extra}"
        return "Already up to date."

    @staticmethod
    def _pull(repo: git.Repo) -> str:
        if not repo.remotes:
            return "No remote configured."
        try:
            branch = repo.active_branch
        except TypeError as exc:
            raise RuntimeError("Cannot pull while HEAD is detached.") from exc
        upstream = branch.tracking_branch()
        if upstream is None:
            raise RuntimeError(
                f"Branch '{branch.name}' has no upstream remote branch configured."
            )
        remote_name = upstream.remote_name
        merge_target = upstream.remote_head
        output = repo.git.pull("--ff-only", remote_name, merge_target)
        return output.splitlines()[0] if output else "Already up to date."

    @staticmethod
    def _push(repo: git.Repo) -> str:
        if not repo.remotes:
            return "No remote configured."
        try:
            branch = repo.active_branch
        except TypeError as exc:
            raise RuntimeError("Cannot push while HEAD is detached.") from exc
        upstream = branch.tracking_branch()
        if upstream is None:
            raise RuntimeError(
                f"Branch '{branch.name}' has no upstream remote branch configured."
            )
        output = repo.git.push(upstream.remote_name, f"{branch.name}:{upstream.remote_head}")
        return output.splitlines()[0] if output else "Pushed successfully."


# ── Controller ───────────────────────────────────────────────────────────────

class ToolbarController(QObject):
    """Manages all toolbar git operations for the open repository.

    Instantiate once in MainWindow and keep alive for the application lifetime.
    """

    # ── Public signals ────────────────────────────────────────────────
    operation_started    = pyqtSignal(str)        # op_name
    operation_finished   = pyqtSignal(str, str)   # op_name, detail
    operation_failed     = pyqtSignal(str, str)   # op_name, error_message
    refs_changed         = pyqtSignal()
    working_tree_changed = pyqtSignal()

    _OP_NAMES: dict[_Op, str] = {
        _Op.FETCH: "Fetch",
        _Op.PULL:  "Pull",
        _Op.PUSH:  "Push",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repo: git.Repo | None = None
        self._profile: "Profile | None" = None
        self._ssh_key_path: str = ""   # fallback when no profile is set
        self._busy: bool = False

        self._thread = QThread(self)
        self._worker = _GitWorker()
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self.destroyed.connect(self._shutdown_thread)
        self._thread.start()

    def _shutdown_thread(self) -> None:
        self._thread.quit()
        self._thread.wait(3000)

    # ── Repo / identity ───────────────────────────────────────────────

    def set_repo(self, repo: git.Repo | None) -> None:
        """Attach or detach the active repository."""
        self._repo = repo

    def set_profile(self, profile: "Profile | None") -> None:
        """Update the auth profile used for all network operations.

        Replaces the legacy ``set_ssh_key()`` call — both SSH and HTTPS
        profiles are handled here.
        """
        self._profile = profile
        # Keep _ssh_key_path in sync for any remaining callers of set_ssh_key()
        if profile and profile.auth_method == AuthMethod.SSH:
            self._ssh_key_path = profile.ssh_key_path or ""
        else:
            self._ssh_key_path = ""

    def set_ssh_key(self, path: str) -> None:
        """Set the SSH private-key path directly (legacy / profile-less path).

        Prefer ``set_profile()`` when a full profile is available.
        """
        self._ssh_key_path = path or ""

    @property
    def is_busy(self) -> bool:
        return self._busy

    # ── Async network operations ──────────────────────────────────────

    def fetch(self) -> None:
        self._dispatch_async(_Op.FETCH)

    def pull(self) -> None:
        self._dispatch_async(_Op.PULL)

    def push(self) -> None:
        self._dispatch_async(_Op.PUSH)

    # ── Sync local operations ─────────────────────────────────────────

    def create_branch(self, name: str) -> None:
        if self._repo is None:
            raise RuntimeError("No repository open.")
        name = name.strip()
        if not name:
            raise ValueError("Branch name cannot be empty.")
        self._repo.git.checkout("-b", name)
        self.refs_changed.emit()
        self.operation_finished.emit("Branch", f"Switched to new branch '{name}'.")

    def stash(self) -> None:
        if self._repo is None:
            raise RuntimeError("No repository open.")
        output = self._repo.git.stash("push", "--include-untracked")
        self.working_tree_changed.emit()
        detail = output.splitlines()[0] if output else "Changes stashed."
        self.operation_finished.emit("Stash", detail)

    def pop_stash(self) -> None:
        if self._repo is None:
            raise RuntimeError("No repository open.")
        output = self._repo.git.stash("pop")
        self.working_tree_changed.emit()
        detail = output.splitlines()[0] if output else "Stash applied."
        self.operation_finished.emit("Pop", detail)

    # ── Private helpers ───────────────────────────────────────────────

    def _build_auth_info(self) -> dict:
        """Build the auth dict to pass to the worker for the current profile."""
        profile = self._profile

        if profile is not None:
            if profile.auth_method == AuthMethod.HTTPS:
                # Retrieve token from the OS keyring in the main thread
                token = get_token(profile.https_username)
                return {
                    "type":     "https",
                    "username": profile.https_username,
                    "token":    token,
                }
            if profile.auth_method == AuthMethod.SYSTEM:
                # Let git use its own credential helper / ssh-agent; no injection
                return {"type": "none"}
            # SSH profile
            key = profile.ssh_key_path or self._ssh_key_path
            if key:
                return {"type": "ssh", "key_path": key}
            return {"type": "none"}

        # No profile — fall back to the legacy ssh_key_path attribute
        if self._ssh_key_path:
            return {"type": "ssh", "key_path": self._ssh_key_path}
        return {"type": "none"}

    def _dispatch_async(self, op: _Op) -> None:
        op_name = self._OP_NAMES[op]
        if self._repo is None:
            self.operation_failed.emit(op_name, "No repository open.")
            return
        if self._busy:
            self.operation_failed.emit(op_name, "Another operation is already running.")
            return
        self._busy = True
        self.operation_started.emit(op_name)
        self._worker._run.emit(op, self._repo, self._build_auth_info())  # type: ignore[attr-defined]

    # ── Worker callbacks (main thread) ────────────────────────────────

    @pyqtSlot(_Op, str)
    def _on_worker_finished(self, op: _Op, detail: str) -> None:
        self._busy = False
        if op in (_Op.FETCH, _Op.PULL):
            self.refs_changed.emit()
        if op is _Op.PULL:
            self.working_tree_changed.emit()
        self.operation_finished.emit(self._OP_NAMES[op], detail)

    @pyqtSlot(_Op, str)
    def _on_worker_failed(self, op: _Op, error: str) -> None:
        self._busy = False
        self.operation_failed.emit(self._OP_NAMES[op], error)
