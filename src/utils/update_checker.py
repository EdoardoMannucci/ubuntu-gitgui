"""
UpdateChecker — background worker that queries GitHub Releases for a newer version.

Emits ``update_available(latest_version, release_url)`` when the remote tag is
strictly newer than the running version.  Network errors are silently swallowed
so a connectivity problem never interrupts the user.
"""

from __future__ import annotations

import urllib.request
import urllib.error
import json

from packaging.version import Version, InvalidVersion

from PyQt6.QtCore import QThread, pyqtSignal

_RELEASES_API = (
    "https://api.github.com/repos/edoardottt/ubuntu-gitgui/releases/latest"
)
_RELEASES_PAGE = "https://github.com/edoardottt/ubuntu-gitgui/releases/latest"
_TIMEOUT = 8  # seconds


def _parse(tag: str) -> Version | None:
    """Strip leading 'v', return a Version or None on parse failure."""
    try:
        return Version(tag.lstrip("v"))
    except InvalidVersion:
        return None


class UpdateChecker(QThread):
    """
    Fire-and-forget QThread.  Create, connect ``update_available``, call
    ``start()``.  The thread exits when the check completes.
    """

    update_available = pyqtSignal(str, str)  # (latest_version, release_url)

    def __init__(self, current_version: str, parent=None) -> None:
        super().__init__(parent)
        self._current = current_version

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                _RELEASES_API,
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": "ubuntu-gitgui-update-checker"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())

            tag: str = data.get("tag_name", "")
            html_url: str = data.get("html_url", _RELEASES_PAGE)

            current = _parse(self._current)
            latest  = _parse(tag)

            if current is None or latest is None:
                return
            if latest > current:
                self.update_available.emit(tag.lstrip("v"), html_url)

        except Exception:
            pass  # network unavailable or API error — do nothing
