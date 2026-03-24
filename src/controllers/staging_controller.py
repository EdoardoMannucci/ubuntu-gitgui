"""
StagingController — business logic for the working directory and staging area.

Responsibilities:
  - Read unstaged changes (working tree vs index)
  - Read staged changes (index vs HEAD)
  - Stage / unstage individual files or everything
  - Perform commits using the active Git identity profile

The controller never touches the UI.  It emits signals when state changes so
that connected views can refresh themselves.

Signals:
    status_changed()         — emitted after any staging/unstaging operation
    commit_made(short_hash)  — emitted after a successful commit

Git command strategy:
  For reading status we use the GitPython object model (index.diff, untracked_files).
  For mutating operations we use the git porcelain wrapper (repo.git.add / reset /
  rm) which handles edge cases (deleted files, empty repos, rename tracking) more
  reliably than the Python-level index API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import git
from PyQt6.QtCore import QObject, pyqtSignal


# ── File-status types ─────────────────────────────────────────────────────────

class FileStatus(str, Enum):
    """Single-character status codes, compatible with git's short format."""
    MODIFIED  = "M"
    ADDED     = "A"
    DELETED   = "D"
    RENAMED   = "R"
    COPIED    = "C"
    UNTRACKED = "?"
    CONFLICT  = "U"   # unmerged / merge conflict
    UNKNOWN   = " "

    @classmethod
    def from_change_type(cls, change_type: str) -> "FileStatus":
        try:
            return cls(change_type[0].upper())
        except (ValueError, IndexError):
            return cls.UNKNOWN


@dataclass(frozen=True)
class FileEntry:
    """A single file in the staging area with its status."""
    status: FileStatus
    path: str   # repo-relative path, uses forward slashes

    @property
    def display(self) -> str:
        """Human-readable label: '<STATUS> path/to/file'."""
        return f"{self.status.value}  {self.path}"


# ── Controller ────────────────────────────────────────────────────────────────

class StagingController(QObject):
    """Manages working-tree status and staging operations for the open repo."""

    status_changed = pyqtSignal()          # after any stage / unstage / checkout
    commit_made    = pyqtSignal(str)        # payload: short commit hash (7 chars)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repo: git.Repo | None = None

    # ── Repo lifecycle ────────────────────────────────────────────────

    def set_repo(self, repo: git.Repo | None) -> None:
        """Attach or detach the active repository and notify views."""
        self._repo = repo
        self.status_changed.emit()

    @property
    def has_repo(self) -> bool:
        return self._repo is not None

    @property
    def is_merging(self) -> bool:
        """True when the repository is in a mid-merge conflict state."""
        if self._repo is None:
            return False
        import os
        merge_head = os.path.join(str(self._repo.git_dir), "MERGE_HEAD")
        return os.path.exists(merge_head)

    # ── Merge abort ───────────────────────────────────────────────────

    def abort_merge(self) -> None:
        """Abort the current merge and restore the pre-merge working tree.

        Raises:
            RuntimeError:        if no repo is open.
            git.GitCommandError: if there is no merge in progress.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._repo.git.merge("--abort")
        self.status_changed.emit()

    # ── Status readers ────────────────────────────────────────────────

    def get_unstaged(self) -> list[FileEntry]:
        """Return files that have changes in the working tree not yet staged.

        Includes:
          - Conflicted files        (unmerged blobs — shown first)
          - Modified tracked files  (index vs working tree)
          - Deleted tracked files   (in index, removed from disk)
          - Untracked files         (not in index at all)
        """
        if self._repo is None:
            return []

        entries: list[FileEntry] = []

        # Conflicted files take priority over regular modifications
        conflict_paths: set[str] = set()
        for path in self._repo.index.unmerged_blobs():
            conflict_paths.add(path)
            entries.append(FileEntry(status=FileStatus.CONFLICT, path=path))

        # Tracked changes: index vs working tree (skip already-listed conflicts)
        for diff in self._repo.index.diff(None):
            path = diff.b_path if diff.renamed_file else diff.a_path
            if path not in conflict_paths:
                status = FileStatus.from_change_type(diff.change_type)
                entries.append(FileEntry(status=status, path=path))

        # Untracked files (not known to git at all)
        for path in self._repo.untracked_files:
            if path not in conflict_paths:
                entries.append(FileEntry(status=FileStatus.UNTRACKED, path=path))

        return sorted(entries, key=lambda e: e.path)

    def get_staged(self) -> list[FileEntry]:
        """Return files that are staged (index differs from HEAD).

        For a repo with no commits yet, every file in the index is listed
        as "Added" since there is no HEAD to compare against.
        """
        if self._repo is None:
            return []

        entries: list[FileEntry] = []

        try:
            # Compare index against HEAD commit
            for diff in self._repo.index.diff(self._repo.head.commit):
                status = FileStatus.from_change_type(diff.change_type)
                path = diff.b_path if diff.renamed_file else diff.a_path
                entries.append(FileEntry(status=status, path=path))
        except (ValueError, git.BadName):
            # No HEAD yet (empty repo after git init) — every indexed entry is new
            seen: set[str] = set()
            for (path, _stage) in self._repo.index.entries.keys():
                if path not in seen:
                    seen.add(path)
                    entries.append(FileEntry(status=FileStatus.ADDED, path=path))

        return sorted(entries, key=lambda e: e.path)

    # ── Stage operations ──────────────────────────────────────────────

    def stage(self, paths: list[str]) -> None:
        """Stage the given file paths (adds or removes from index as needed).

        Uses ``git add`` which handles modified, deleted, and untracked files.

        Raises:
            git.GitCommandError: on any git error.
            RuntimeError: if no repo is open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        if not paths:
            return
        self._repo.git.add("--", *paths)
        self.status_changed.emit()

    def stage_all(self) -> None:
        """Stage all changes in the working tree (equivalent to ``git add -A``).

        Raises:
            git.GitCommandError: on any git error.
            RuntimeError: if no repo is open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        self._repo.git.add("-A")
        self.status_changed.emit()

    # ── Unstage operations ────────────────────────────────────────────

    def unstage(self, paths: list[str]) -> None:
        """Unstage the given file paths (move from index back to working tree).

        For repos with no HEAD commit, uses ``git rm --cached`` instead of
        ``git reset HEAD`` which requires at least one commit.

        Raises:
            git.GitCommandError: on any git error.
            RuntimeError: if no repo is open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        if not paths:
            return
        try:
            self._repo.git.reset("HEAD", "--", *paths)
        except git.GitCommandError:
            # Empty repo: no HEAD exists yet, fall back to rm --cached
            self._repo.git.rm("--cached", "--", *paths)
        self.status_changed.emit()

    def unstage_all(self) -> None:
        """Unstage everything (move all staged changes back to working tree).

        Raises:
            git.GitCommandError: on any git error.
            RuntimeError: if no repo is open.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")
        try:
            self._repo.git.reset("HEAD")
        except git.GitCommandError:
            # Empty repo: remove all entries from index
            entries = list(self._repo.index.entries.keys())
            if entries:
                self._repo.git.rm("--cached", "-r", ".")
        self.status_changed.emit()

    # ── Diff generation ──────────────────────────────────────────────

    def get_diff(self, path: str, is_staged: bool) -> str:
        """Return the unified diff text for *path*.

        Args:
            path:      Repo-relative file path (forward slashes).
            is_staged: True  → index vs HEAD   (``git diff --cached``)
                       False → working tree vs index (``git diff``)

        Returns:
            A unified diff string (may be empty for binary files or no changes).
            Returns a descriptive placeholder string on error.
        """
        if self._repo is None:
            return ""

        try:
            if is_staged:
                # Staged changes: index vs HEAD
                try:
                    diff_text = self._repo.git.diff("--cached", "--", path)
                except git.GitCommandError:
                    # No HEAD yet (empty repo) — the whole file is new
                    diff_text = self._build_new_file_diff(path)
            else:
                # Unstaged changes: working tree vs index
                # Detect whether the file is untracked (not in index)
                is_untracked = any(
                    e.path == path and e.status == FileStatus.UNTRACKED
                    for e in self.get_unstaged()
                )
                if is_untracked:
                    diff_text = self._build_new_file_diff(path)
                else:
                    diff_text = self._repo.git.diff("--", path)

        except git.GitCommandError as exc:
            return f"# Error generating diff:\n# {exc}"

        return diff_text or "# No textual changes detected (binary file or empty diff)."

    def get_commit_diff(self, full_hash: str, path: str) -> str:
        """Return the unified diff for *path* as introduced by commit *full_hash*.

        Equivalent to ``git show <hash> -- <path>``.

        Returns an empty string if no repo is open, or a descriptive error
        message if the git command fails.
        """
        if self._repo is None:
            return ""
        try:
            return self._repo.git.show(full_hash, "--", path)
        except git.GitCommandError as exc:
            return f"# Error generating diff:\n# {exc}"

    def _build_new_file_diff(self, path: str) -> str:
        """Construct a synthetic unified diff for a brand-new (untracked) file.

        Since git has no previous version to compare against, we present the
        entire file content as added lines so the viewer can highlight it.

        Security: the resolved absolute path is verified to be strictly inside
        the repository working tree before the file is opened, preventing path
        traversal via crafted repository entries (CWE-22).
        """
        import os

        root = os.path.realpath(str(self._repo.working_tree_dir))  # type: ignore[arg-type]
        full_path = os.path.realpath(os.path.join(root, path))

        # Reject paths that escape the repository root (e.g. /abs/path, ../../etc)
        try:
            if os.path.commonpath([root, full_path]) != root:
                return f"# Access denied: path escapes repository root: {path}"
        except ValueError:
            # commonpath raises ValueError on mixed absolute/relative on Windows;
            # treat as a traversal attempt.
            return f"# Access denied: invalid path: {path}"

        try:
            with open(full_path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return f"# Cannot read file: {path}"

        header = [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            f"@@ -0,0 +1,{len(lines)} @@",
        ]
        return "\n".join(header + ["+" + line for line in lines])

    # ── Commit ────────────────────────────────────────────────────────

    @staticmethod
    def _validate_identity_field(value: str, field_name: str) -> str:
        """Strip and reject values that contain newline or carriage-return characters.

        Git commit objects use line-based headers; embedding CR/LF in the
        author name or email would corrupt the object format (newline injection,
        CWE-93 / CWE-117).

        Returns the stripped value on success.
        Raises ValueError if the value is blank or contains control characters.
        """
        value = value.strip()
        if not value:
            raise ValueError(f"Commit {field_name} cannot be empty.")
        if any(ch in value for ch in ("\n", "\r")):
            raise ValueError(
                f"Commit {field_name} must not contain newline characters."
            )
        return value

    def commit(self, message: str, git_name: str, git_email: str) -> str:
        """Create a commit with the given message and explicit author identity.

        The author and committer are set directly on the commit object via
        GitPython's ``Actor`` API — no changes are made to the git config.

        Args:
            message:   The commit message (must not be blank).
            git_name:  The author/committer display name.
            git_email: The author/committer email address.

        Returns:
            The full SHA-1 hash of the new commit.

        Raises:
            ValueError:            if the message, name, or email is blank or
                                   contains newline characters.
            RuntimeError:          if no repo is open or nothing is staged.
            git.GitCommandError:   on any lower-level git error.
        """
        if self._repo is None:
            raise RuntimeError("No repository open.")

        message = message.strip()
        if not message:
            raise ValueError("Commit message cannot be empty.")

        git_name  = self._validate_identity_field(git_name,  "author name")
        git_email = self._validate_identity_field(git_email, "author email")

        actor = git.Actor(git_name, git_email)
        new_commit = self._repo.index.commit(
            message,
            author=actor,
            committer=actor,
        )

        self.status_changed.emit()
        self.commit_made.emit(new_commit.hexsha[:7])
        return new_commit.hexsha
