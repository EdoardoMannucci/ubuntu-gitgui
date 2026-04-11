from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import git
from PyQt6.QtCore import QCoreApplication

from src.controllers.repository_controller import (
    BranchState,
    RepositoryController,
    _CloneWorker,
)


APP = QCoreApplication.instance() or QCoreApplication([])


def git_run(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class RepositoryControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.repo_path = self.root / "repo"
        self.repo_path.mkdir()
        git_run(self.repo_path, "init", "-b", "main")
        git_run(self.repo_path, "config", "user.name", "Test User")
        git_run(self.repo_path, "config", "user.email", "test@example.com")
        (self.repo_path / "README.md").write_text("hello\n", encoding="utf-8")
        git_run(self.repo_path, "add", "README.md")
        git_run(self.repo_path, "commit", "-m", "initial")
        self.ctrl = RepositoryController()
        self.addCleanup(self.ctrl._shutdown_thread)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_state_reports_no_remote_and_upstream_variants(self) -> None:
        self.ctrl.open_repo(str(self.repo_path))
        self.assertEqual(self.ctrl.state.branch_state, BranchState.NO_REMOTE)

        bare = self.root / "remote.git"
        git_run(self.root, "init", "--bare", str(bare))
        git_run(self.repo_path, "remote", "add", "origin", str(bare))
        self.assertEqual(self.ctrl.state.branch_state, BranchState.NO_UPSTREAM)

        git_run(self.repo_path, "push", "-u", "origin", "main")
        self.assertEqual(self.ctrl.state.branch_state, BranchState.READY)

    def test_state_reports_detached_head(self) -> None:
        self.ctrl.open_repo(str(self.repo_path))
        full_hash = git.Repo(self.repo_path).head.commit.hexsha
        self.ctrl.checkout_commit(full_hash)
        self.assertEqual(self.ctrl.state.branch_state, BranchState.DETACHED)
        self.assertTrue(self.ctrl.state.display_name.startswith("HEAD"))

    def test_navigation_undo_redo(self) -> None:
        self.ctrl.open_repo(str(self.repo_path))
        git_run(self.repo_path, "checkout", "-b", "feature")
        git_run(self.repo_path, "checkout", "main")
        self.ctrl.checkout_branch("feature")
        self.assertEqual(self.ctrl.current_branch_name, "feature")

        undo_label = self.ctrl.undo_navigation()
        self.assertEqual(undo_label, "main")
        self.assertEqual(self.ctrl.current_branch_name, "main")

        redo_label = self.ctrl.redo_navigation()
        self.assertEqual(redo_label, "feature")
        self.assertEqual(self.ctrl.current_branch_name, "feature")

    def test_create_branch_at_ref_from_commit(self) -> None:
        self.ctrl.open_repo(str(self.repo_path))
        full_hash = git.Repo(self.repo_path).head.commit.hexsha
        self.ctrl.create_branch_at_ref("release/test", full_hash)
        self.assertEqual(self.ctrl.current_branch_name, "release/test")

    def test_submodules_are_listed(self) -> None:
        sub_remote = self.root / "submodule-remote.git"
        git_run(self.root, "init", "--bare", str(sub_remote))

        sub_work = self.root / "submodule-work"
        sub_work.mkdir()
        git_run(sub_work, "init", "-b", "main")
        git_run(sub_work, "config", "user.name", "Test User")
        git_run(sub_work, "config", "user.email", "test@example.com")
        (sub_work / "sub.txt").write_text("sub\n", encoding="utf-8")
        git_run(sub_work, "add", "sub.txt")
        git_run(sub_work, "commit", "-m", "sub init")
        git_run(sub_work, "remote", "add", "origin", str(sub_remote))
        git_run(sub_work, "push", "-u", "origin", "main")

        git_run(
            self.repo_path,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(sub_work),
            "vendor/sub",
        )
        git_run(self.repo_path, "commit", "-am", "add submodule")

        self.ctrl.open_repo(str(self.repo_path))
        self.assertIn("vendor/sub", self.ctrl.submodules())


class CloneWorkerTest(unittest.TestCase):
    def test_clone_worker_builds_ssh_environment(self) -> None:
        worker = _CloneWorker()
        seen: dict[str, object] = {}

        def fake_clone(url: str, destination: str, env=None):  # type: ignore[no-untyped-def]
            seen["env"] = env
            return object()

        worker.finished.connect(lambda _repo: seen.setdefault("finished", True))
        with patch("git.Repo.clone_from", side_effect=fake_clone):
            worker.clone("git@example.com:repo.git", "/tmp/repo", "/tmp/key", "", "")

        self.assertIn("GIT_SSH_COMMAND", seen["env"])
        self.assertTrue(seen.get("finished"))

    def test_clone_worker_builds_https_environment(self) -> None:
        worker = _CloneWorker()
        seen: dict[str, object] = {}

        def fake_clone(url: str, destination: str, env=None):  # type: ignore[no-untyped-def]
            seen["env"] = env
            return object()

        worker.finished.connect(lambda _repo: seen.setdefault("finished", True))
        with patch("git.Repo.clone_from", side_effect=fake_clone):
            worker.clone("https://example.com/repo.git", "/tmp/repo", "", "alice", "secret")

        env = seen["env"]
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("GIT_ASKPASS", env)
        self.assertTrue(seen.get("finished"))
