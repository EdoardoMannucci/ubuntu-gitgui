"""
ProfileController — business logic for identity management.

Responsibilities:
  - CRUD delegation to ProfileRepository
  - Activating a profile: updates in-memory state and emits active_changed
  - Applying a profile to an open GitPython Repo (sets local git config)
  - Emitting a Qt signal when the active profile changes so the UI can react

NOTE: This controller intentionally does NOT touch os.environ or
GIT_SSH_COMMAND.  SSH key injection is the exclusive responsibility of
ToolbarController, which applies the key only for the duration of each
network operation and restores the previous environment in a finally block.

Usage (from a view):
    controller = ProfileController()
    controller.active_changed.connect(my_slot)
    controller.activate_profile(profile_id)
"""

import git
from PyQt6.QtCore import QObject, pyqtSignal

from src.models.profile import Profile, ProfileRepository


class ProfileController(QObject):
    """Manages profile CRUD and Git identity switching.

    Signals:
        active_changed(Profile | None): emitted whenever the active profile
            is set, updated, or cleared.  The argument is the new active
            profile, or None when no profile is active.
    """

    # Emitted after the active profile changes (payload: the new active Profile or None)
    active_changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repo_instance: ProfileRepository = ProfileRepository()

    # ── Read ──────────────────────────────────────────────────────────

    @property
    def profiles(self) -> list[Profile]:
        """Return all stored profiles."""
        return self._repo_instance.profiles

    @property
    def active_profile(self) -> Profile | None:
        """Return the currently active profile, or None."""
        return self._repo_instance.active_profile

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_profile(self, profile: Profile) -> None:
        """Persist a new profile."""
        self._repo_instance.add(profile)

    def update_profile(self, profile: Profile) -> None:
        """Persist changes to an existing profile.

        If the edited profile is currently active, emit active_changed so the
        UI and ToolbarController can update their in-memory state (SSH key path,
        author label, etc.).
        """
        self._repo_instance.update(profile)
        if self.active_profile and self.active_profile.id == profile.id:
            self.active_changed.emit(profile)

    def delete_profile(self, profile_id: str) -> None:
        """Delete a profile.  Clears active state if it was the active one."""
        was_active = (
            self.active_profile is not None
            and self.active_profile.id == profile_id
        )
        self._repo_instance.delete(profile_id)
        if was_active:
            self.active_changed.emit(None)

    # ── Activation ────────────────────────────────────────────────────

    def activate_profile(self, profile_id: str) -> None:
        """Set the given profile as active and notify listeners.

        Raises:
            ValueError: if no profile with that id exists.
        """
        self._repo_instance.set_active(profile_id)
        profile = self._repo_instance.active_profile
        if profile:
            self.active_changed.emit(profile)

    def deactivate_profile(self) -> None:
        """Clear the active profile and notify listeners."""
        self._repo_instance.set_active(None)
        self.active_changed.emit(None)

    def apply_to_repo(self, repo: git.Repo) -> None:
        """Write the active profile's name/email into a repo's local git config.

        This sets ``user.name`` and ``user.email`` at the *local* level so
        commits made inside this repo use the active profile's identity,
        regardless of the user's global git config.

        Args:
            repo: An open GitPython ``Repo`` instance.

        Raises:
            RuntimeError: if no profile is currently active.
        """
        profile = self.active_profile
        if profile is None:
            raise RuntimeError("No active profile — cannot apply git config.")

        with repo.config_writer() as cfg:
            cfg.set_value("user", "name", profile.git_name)
            cfg.set_value("user", "email", profile.git_email)

