from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import git

from src.controllers.staging_controller import StagingController
from src.controllers.toolbar_controller import _GitWorker


def git_run(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class ToolbarWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _create_repo_with_initial_commit(self, name: str = "repo") -> Path:
        repo_path = self.root / name
        repo_path.mkdir()
        git_run(repo_path, "init", "-b", "main")
        git_run(repo_path, "config", "user.name", "Test User")
        git_run(repo_path, "config", "user.email", "test@example.com")
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")
        git_run(repo_path, "add", "README.md")
        git_run(repo_path, "commit", "-m", "initial")
        return repo_path

    def test_pull_requires_non_detached_head(self) -> None:
        repo_path = self._create_repo_with_initial_commit()
        remote_path = self.root / "remote.git"
        git_run(self.root, "init", "--bare", str(remote_path))
        git_run(repo_path, "remote", "add", "origin", str(remote_path))
        repo = git.Repo(repo_path)
        repo.git.checkout("--detach", repo.head.commit.hexsha)
        with self.assertRaises(RuntimeError):
            _GitWorker._pull(repo)

    def test_push_requires_upstream(self) -> None:
        repo_path = self._create_repo_with_initial_commit()
        remote_path = self.root / "remote.git"
        git_run(self.root, "init", "--bare", str(remote_path))
        git_run(repo_path, "remote", "add", "origin", str(remote_path))
        repo = git.Repo(repo_path)
        with self.assertRaises(RuntimeError):
            _GitWorker._push(repo)

    def test_push_uses_tracking_remote(self) -> None:
        repo_path = self._create_repo_with_initial_commit("work")
        remote_path = self.root / "remote.git"
        git_run(self.root, "init", "--bare", str(remote_path))
        git_run(repo_path, "remote", "add", "origin", str(remote_path))
        git_run(repo_path, "push", "-u", "origin", "main")

        repo = git.Repo(repo_path)
        output = _GitWorker._push(repo)
        self.assertTrue(output)


class StagingControllerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_stage_unstage_in_empty_repo(self) -> None:
        repo_path = self.root / "empty"
        repo_path.mkdir()
        repo = git.Repo.init(repo_path)
        (repo_path / "new.txt").write_text("new\n", encoding="utf-8")

        ctrl = StagingController()
        ctrl.set_repo(repo)
        ctrl.stage(["new.txt"])
        staged = [entry.path for entry in ctrl.get_staged()]
        self.assertIn("new.txt", staged)

        ctrl.unstage(["new.txt"])
        staged_after = [entry.path for entry in ctrl.get_staged()]
        self.assertNotIn("new.txt", staged_after)

    def test_abort_merge_after_conflict(self) -> None:
        repo_path = self.root / "merge"
        repo_path.mkdir()
        git_run(repo_path, "init", "-b", "main")
        git_run(repo_path, "config", "user.name", "Test User")
        git_run(repo_path, "config", "user.email", "test@example.com")
        (repo_path / "conflict.txt").write_text("base\n", encoding="utf-8")
        git_run(repo_path, "add", "conflict.txt")
        git_run(repo_path, "commit", "-m", "base")
        git_run(repo_path, "checkout", "-b", "feature")
        (repo_path / "conflict.txt").write_text("feature\n", encoding="utf-8")
        git_run(repo_path, "commit", "-am", "feature change")
        git_run(repo_path, "checkout", "main")
        (repo_path / "conflict.txt").write_text("main\n", encoding="utf-8")
        git_run(repo_path, "commit", "-am", "main change")

        repo = git.Repo(repo_path)
        ctrl = StagingController()
        ctrl.set_repo(repo)
        with self.assertRaises(git.GitCommandError):
            repo.git.merge("feature")
        self.assertTrue(ctrl.is_merging)

        ctrl.abort_merge()
        self.assertFalse(ctrl.is_merging)
