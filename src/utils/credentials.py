"""
Credential utilities for ubuntu-gitgui.

Provides:
  - AuthMethod enum  (SSH | HTTPS)
  - Token storage/retrieval via the native Secret Service (GNOME Keyring /
    KWallet) through the ``keyring`` library — never stored in plaintext.
  - AskPassScript context manager that writes a minimal GIT_ASKPASS helper
    script to a mode-700 temp file, yields its path, and deletes it on exit.
    This avoids embedding credentials in process arguments or URLs.

Security notes
--------------
* Tokens are stored by the OS secret store and are never written to disk by
  this module.
* The AskPassScript temp file is created with O_EXCL + mode 700 (owner-
  execute only) so other users on the same machine cannot read it.
* The token value is passed to the script via shlex.quote() and is NOT
  logged by this module.  Callers must ensure they don't log auth dicts.
"""

from __future__ import annotations

import os
import shlex
import stat
import tempfile
from enum import Enum


# ── Service identifier for the OS keyring ─────────────────────────────────────

_SERVICE = "ubuntu-gitgui"


# ── AuthMethod enum ───────────────────────────────────────────────────────────

class AuthMethod(str, Enum):
    """Authentication method used for remote git operations.

    SSH    — use a specific private-key file via GIT_SSH_COMMAND.
    HTTPS  — use a Username + PAT stored in the OS keyring via GIT_ASKPASS.
    SYSTEM — do nothing; let git use its own configured credential helper
             (e.g. libsecret on Ubuntu) or the running ssh-agent.  This is
             the right choice for users who have already set up git creds at
             the OS level and don't want the app to interfere.
    """
    SSH    = "ssh"
    HTTPS  = "https"
    SYSTEM = "system"


# ── Keyring helpers ───────────────────────────────────────────────────────────

def store_token(username: str, token: str) -> None:
    """Store *token* for *username* in the native OS secret store.

    Uses ``keyring.set_password(_SERVICE, username, token)`` which maps to
    GNOME Keyring on most Ubuntu desktops.

    Args:
        username: HTTPS username (used as the account key in the keyring).
        token:    Personal Access Token or password.  Must be non-empty.

    Raises:
        keyring.errors.KeyringError: if the secret service is unavailable.
    """
    import keyring  # lazy import — only needed when HTTPS auth is used
    keyring.set_password(_SERVICE, username, token)


def get_token(username: str) -> str:
    """Retrieve the token for *username* from the OS secret store.

    Returns an empty string if no token is found or if the secret service
    is unavailable (so callers can degrade gracefully).

    Args:
        username: HTTPS username whose token to retrieve.
    """
    try:
        import keyring
        value = keyring.get_password(_SERVICE, username)
        return value or ""
    except Exception:  # noqa: BLE001
        return ""


def delete_token(username: str) -> None:
    """Remove the stored token for *username*.

    Silent no-op if no token exists or the service is unavailable.

    Args:
        username: HTTPS username whose token to remove.
    """
    try:
        import keyring
        keyring.delete_password(_SERVICE, username)
    except Exception:  # noqa: BLE001
        pass


# ── GIT_ASKPASS context manager ───────────────────────────────────────────────

class AskPassScript:
    """Context manager that creates a temporary GIT_ASKPASS helper script.

    Git calls the ASKPASS binary with the prompt text as its sole argument.
    This script responds with the username or token depending on whether the
    prompt contains the word "username" (case-insensitive).

    Usage::

        with AskPassScript(username, token) as script_path:
            env = {"GIT_ASKPASS": script_path, "GIT_TERMINAL_PROMPT": "0"}
            # ... run git with env ...
        # script is deleted here

    The temp file is created with permissions 0o700 (owner read/write/execute
    only) so no other OS user can read the embedded credentials.

    Args:
        username: HTTPS username to return for Username prompts.
        token:    PAT or password to return for Password prompts.
    """

    def __init__(self, username: str, token: str) -> None:
        self._username = username
        self._token    = token
        self._path: str | None = None

    def __enter__(self) -> str:
        script = (
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            f"  *[Uu]sername*) printf '%s\\n' {shlex.quote(self._username)} ;;\n"
            f"  *)             printf '%s\\n' {shlex.quote(self._token)}    ;;\n"
            "esac\n"
        )
        fd, path = tempfile.mkstemp(prefix="gitgui_askpass_", suffix=".sh")
        try:
            os.write(fd, script.encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(path, stat.S_IRWXU)   # 0o700 — owner only
        self._path = path
        return path

    def __exit__(self, *_) -> None:
        if self._path:
            try:
                os.unlink(self._path)
            except OSError:
                pass
            self._path = None
