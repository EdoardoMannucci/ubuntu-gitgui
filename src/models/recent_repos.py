"""
RecentRepositoryManager — persists the list of recently opened Git repositories.

Storage: ~/.config/ubuntu-gitgui/recent_repos.json

Each entry is a plain dict:
    {"path": "/abs/path/to/repo", "name": "repo-folder-name"}

The list is kept sorted newest-first and capped at MAX_RECENT entries.
Paths that no longer exist on disk are silently pruned on read.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / ".config" / "ubuntu-gitgui"
_RECENT_FILE = _CONFIG_DIR / "recent_repos.json"

MAX_RECENT: int = 10


class RecentRepositoryManager:
    """Loads and persists the list of recently opened repositories."""

    def __init__(self, path: Path = _RECENT_FILE) -> None:
        self._path = path
        self._entries: list[dict] = []
        self._ensure_dir()
        self._load()

    # ── Public API ────────────────────────────────────────────────────

    def add(self, repo_path: str) -> None:
        """Push *repo_path* to the front of the list and persist.

        De-duplicates by path: if the repo is already in the list it is moved
        to the front rather than added a second time.
        """
        name = Path(repo_path).name
        self._entries = [e for e in self._entries if e["path"] != repo_path]
        self._entries.insert(0, {"path": repo_path, "name": name})
        self._entries = self._entries[:MAX_RECENT]
        self._save()

    def get_all(self) -> list[dict]:
        """Return all valid recent entries, newest first.

        Entries whose path no longer exists on disk are pruned and the
        updated list is persisted automatically.
        """
        valid = [e for e in self._entries if Path(e["path"]).exists()]
        if len(valid) != len(self._entries):
            self._entries = valid
            self._save()
        return list(valid)

    def clear(self) -> None:
        """Remove all entries and persist."""
        self._entries = []
        self._save()

    # ── Private helpers ───────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._entries = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load recent_repos.json: %s", exc)
            self._entries = []

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._entries, fh, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            tmp.replace(self._path)
        except OSError as exc:
            logger.error("Could not save recent_repos.json: %s", exc)
