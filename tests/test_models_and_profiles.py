from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.controllers.profile_controller import ProfileController
from src.models.profile import Profile, ProfileRepository
from src.models.recent_repos import RecentRepositoryManager
from src.utils.credentials import AuthMethod


class RecentRepositoriesTest(unittest.TestCase):
    def test_missing_paths_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "recent.json"
            existing = Path(tmp) / "repo"
            existing.mkdir()
            storage.write_text(
                json.dumps(
                    [
                        {"path": str(existing), "name": "repo"},
                        {"path": str(Path(tmp) / "gone"), "name": "gone"},
                    ]
                ),
                encoding="utf-8",
            )
            manager = RecentRepositoryManager(path=storage)
            entries = manager.get_all()
            self.assertEqual([entry["name"] for entry in entries], ["repo"])


class ProfileRepositoryTest(unittest.TestCase):
    def test_active_profile_is_emitted_when_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "profiles.json"
            repo = ProfileRepository(path=storage)
            controller = ProfileController()
            controller._repo_instance = repo  # type: ignore[attr-defined]

            profile = Profile(
                name="Work",
                git_name="Jane Doe",
                git_email="jane@example.com",
                auth_method=AuthMethod.SYSTEM.value,
                ssh_key_path="",
                https_username="",
            )
            controller.add_profile(profile)
            controller.activate_profile(profile.id)

            emitted: list[str] = []
            controller.active_changed.connect(lambda value: emitted.append(value.name))

            updated = Profile(
                id=profile.id,
                name="Work 2",
                git_name="Jane Doe",
                git_email="jane@example.com",
                auth_method=AuthMethod.SYSTEM.value,
                ssh_key_path="",
                https_username="",
            )
            controller.update_profile(updated)
            self.assertEqual(emitted, ["Work 2"])
