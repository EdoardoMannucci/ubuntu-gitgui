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

SSH identity
────────────
Before each network operation the controller reads the active profile's
ssh_key_path and passes a GIT_SSH_COMMAND string to the worker, which applies
it only for the duration of that call.  The main thread's environment is
never mutated.

Signals (always delivered on the main thread via queued connections):
    operation_started(op_name)           — a git operation has begun
    operation_finished(op_name, detail)  — completed successfully
    operation_failed(op_name, detail)    — completed with an error
    refs_changed()                       — remote refs updated (fetch / pull)
    working_tree_changed()               — working tree changed (pull / pop)
"""

from __future__ import annotations

import os
import shlex
from enum import Enum, auto

import git
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot


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
    """

    # Input: the controller enqueues work by emitting this signal
    _run = pyqtSignal(_Op, object, str)  # (op, repo, ssh_env)

    # Output: results forwarded to the main thread
    finished = pyqtSignal(_Op, str)   # (op, detail)
    failed   = pyqtSignal(_Op, str)   # (op, error_message)

    def __init__(self) -> None:
        super().__init__()
        self._run.connect(self._execute)

    @pyqtSlot(_Op, object, str)
    def _execute(self, op: _Op, repo: git.Repo, ssh_env: str) -> None:
        # Apply SSH env for this call only
        old_ssh = os.environ.get("GIT_SSH_COMMAND")
        if ssh_env:
            os.environ["GIT_SSH_COMMAND"] = ssh_env
        elif old_ssh is not None:
            del os.environ["GIT_SSH_COMMAND"]

        try:
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
            if old_ssh is not None:
                os.environ["GIT_SSH_COMMAND"] = old_ssh
            elif "GIT_SSH_COMMAND" in os.environ:
                del os.environ["GIT_SSH_COMMAND"]

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
        output = repo.git.pull("--ff-only")
        return output.splitlines()[0] if output else "Already up to date."

    @staticmethod
    def _push(repo: git.Repo) -> str:
        if not repo.remotes:
            return "No remote configured."
        remote_name = repo.remotes[0].name
        branch_name = repo.active_branch.name
        output = repo.git.push("--set-upstream", remote_name, branch_name)
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
        self._ssh_key_path: str = ""
        self._busy: bool = False

        # Worker thread (lives for the entire application lifetime)
        self._thread = QThread(self)
        self._worker = _GitWorker()
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        # Clean up the thread when this QObject is destroyed
        self.destroyed.connect(self._shutdown_thread)
        self._thread.start()

    def _shutdown_thread(self) -> None:
        """Quit the worker thread gracefully (called on destruction)."""
        self._thread.quit()
        self._thread.wait(3000)  # up to 3 s

    # ── Repo / identity ───────────────────────────────────────────────

    def set_repo(self, repo: git.Repo | None) -> None:
        """Attach or detach the active repository."""
        self._repo = repo

    def set_ssh_key(self, path: str) -> None:
        """Update the SSH private-key path used for network operations."""
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
        """Create a new branch at HEAD and check it out.

        Raises:
            RuntimeError:          if no repo is open.
            ValueError:            if *name* is blank.
            git.GitCommandError:   on any git error.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        name = name.strip()
        if not name:
            raise ValueError("Branch name cannot be empty.")
        self._repo.git.checkout("-b", name)
        self.refs_changed.emit()
        self.operation_finished.emit("Branch", f"Switched to new branch '{name}'.")

    def stash(self) -> None:
        """Push the current working tree onto the stash stack.

        Raises:
            RuntimeError:          if no repo is open.
            git.GitCommandError:   on any git error.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        output = self._repo.git.stash("push", "--include-untracked")
        self.working_tree_changed.emit()
        detail = output.splitlines()[0] if output else "Changes stashed."
        self.operation_finished.emit("Stash", detail)

    def pop_stash(self) -> None:
        """Apply and drop the most-recent stash entry.

        Raises:
            RuntimeError:          if no repo is open.
            git.GitCommandError:   on any git error (e.g. no stash, conflicts).
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        output = self._repo.git.stash("pop")
        self.working_tree_changed.emit()
        detail = output.splitlines()[0] if output else "Stash applied."
        self.operation_finished.emit("Pop", detail)

    # ── Private helpers ───────────────────────────────────────────────

    def _build_ssh_env(self) -> str:
        if not self._ssh_key_path:
            return ""
        # shlex.quote() produces a shell-safe single-quoted token that survives
        # any character in the path (spaces, double quotes, backticks, $, etc.).
        return f"ssh -i {shlex.quote(self._ssh_key_path)} -o IdentitiesOnly=yes"

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
        # Emit the worker's internal signal — queued connection delivers it
        # on the worker's thread automatically
        self._worker._run.emit(op, self._repo, self._build_ssh_env())  # type: ignore[attr-defined]

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
