"""
Profile data model and JSON persistence layer.

Profiles are stored in:
    ~/.config/ubuntu-gitgui/profiles.json

Schema:
{
    "active_profile_id": "<uuid> | null",
    "profiles": [
        {
            "id": "<uuid>",
            "name": "Work",
            "git_name": "Jane Doe",
            "git_email": "jane@company.com",
            "auth_method": "ssh",          ← "ssh" | "https"
            "ssh_key_path": "/home/jane/.ssh/id_rsa_work",
            "https_username": ""           ← HTTPS username (token in keyring)
        },
        ...
    ]
}

SECURITY: HTTPS tokens / passwords are NEVER written to this file.
They are stored exclusively in the native OS secret store (GNOME Keyring /
KWallet) via the ``keyring`` library.  The ``https_username`` field is the
look-up key used to retrieve the token at auth time.
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.utils.credentials import AuthMethod

logger = logging.getLogger(__name__)


# ── Config path (XDG-compliant) ──────────────────────────────────────────────

CONFIG_DIR: Path = Path.home() / ".config" / "ubuntu-gitgui"
PROFILES_FILE: Path = CONFIG_DIR / "profiles.json"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Profile:
    """Represents a single Git identity profile."""

    name: str               # Display name, e.g. "Work", "Personal"
    git_name: str           # Git user.name
    git_email: str          # Git user.email
    auth_method: str        # AuthMethod.SSH or AuthMethod.HTTPS (stored as str)
    ssh_key_path: str       # Absolute path to the private SSH key (may be empty)
    https_username: str     # HTTPS username; token retrieved from keyring at runtime
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON encoding.

        NOTE: the HTTPS token is intentionally excluded — it lives in the
        OS keyring, not in this file.
        """
        return {
            "id":             self.id,
            "name":           self.name,
            "git_name":       self.git_name,
            "git_email":      self.git_email,
            "auth_method":    self.auth_method,
            "ssh_key_path":   self.ssh_key_path,
            "https_username": self.https_username,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        """Deserialise from a plain dict.

        Handles legacy profiles (created before auth_method was introduced)
        by defaulting to SSH so existing SSH-key profiles keep working.
        """
        return cls(
            id=data["id"],
            name=data["name"],
            git_name=data["git_name"],
            git_email=data["git_email"],
            auth_method=data.get("auth_method", AuthMethod.SSH.value),
            ssh_key_path=data.get("ssh_key_path", ""),
            https_username=data.get("https_username", ""),
        )

    def __str__(self) -> str:
        return f"{self.name} <{self.git_email}>"


# ── Repository (persistence) ──────────────────────────────────────────────────

class ProfileRepository:
    """Loads and persists profiles to/from ``PROFILES_FILE``."""

    def __init__(self, path: Path = PROFILES_FILE) -> None:
        self._path = path
        self._profiles: list[Profile] = []
        self._active_id: str | None = None
        self._ensure_config_dir()
        self._load()

    # ── Public API ────────────────────────────────────────────────────

    @property
    def profiles(self) -> list[Profile]:
        """Return a shallow copy of the profiles list."""
        return list(self._profiles)

    @property
    def active_profile(self) -> Profile | None:
        """Return the currently active profile, or None."""
        if self._active_id is None:
            return None
        return next((p for p in self._profiles if p.id == self._active_id), None)

    def get_by_id(self, profile_id: str) -> Profile | None:
        """Return the profile with the given id, or None."""
        return next((p for p in self._profiles if p.id == profile_id), None)

    def add(self, profile: Profile) -> None:
        """Append a new profile and persist."""
        self._profiles.append(profile)
        self._save()

    def update(self, profile: Profile) -> None:
        """Replace an existing profile by id and persist."""
        for i, existing in enumerate(self._profiles):
            if existing.id == profile.id:
                self._profiles[i] = profile
                self._save()
                return
        raise ValueError(f"Profile with id '{profile.id}' not found.")

    def delete(self, profile_id: str) -> None:
        """Remove a profile by id and persist. Clears active if needed."""
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        if self._active_id == profile_id:
            self._active_id = None
        self._save()

    def set_active(self, profile_id: str | None) -> None:
        """Set the active profile by id (None to deactivate)."""
        if profile_id is not None and not any(p.id == profile_id for p in self._profiles):
            raise ValueError(f"Profile with id '{profile_id}' not found.")
        self._active_id = profile_id
        self._save()

    # ── Private helpers ───────────────────────────────────────────────

    def _ensure_config_dir(self) -> None:
        """Create the config directory if it does not exist."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load profiles from disk. Silently starts fresh if file is absent."""
        if not self._path.exists():
            self._profiles = []
            self._active_id = None
            return

        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data: dict = json.load(fh)
            self._profiles = [Profile.from_dict(p) for p in data.get("profiles", [])]
            self._active_id = data.get("active_profile_id")
        except (json.JSONDecodeError, KeyError) as exc:
            # Corrupted file — start with empty state rather than crashing
            logger.warning("Could not parse profiles file: %s", exc)
            self._profiles = []
            self._active_id = None

    def _save(self) -> None:
        """Persist the current state to disk (atomic write via temp file).

        Security: the temp file is created with mode 0o600 (owner read/write
        only) before the atomic rename, so the final profiles.json is never
        world-readable regardless of the process umask.
        """
        payload = {
            "active_profile_id": self._active_id,
            "profiles": [p.to_dict() for p in self._profiles],
        }
        tmp_path = self._path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self._path)
