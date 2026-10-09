#!/usr/bin/env python3
"""Unit tests for the Stow Sync backend.

All tests use real ``git`` against throwaway repositories created under a
temporary directory, never the owner's real dotfiles repos. The git
environment is isolated from the host's global config, identity and hooks.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stow_sync as ss  # noqa: E402


# --------------------------------------------------------------------------
# git test environment and helpers (pattern from gladimdim.config-sync tests)
# --------------------------------------------------------------------------


def git_test_env() -> dict[str, str]:
    """Isolate test git from the host's global config, identity and hooks."""
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
        env=git_test_env(),
    )


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        env=git_test_env(),
    )
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def porcelain_bytes(repo: Path) -> bytes:
    """Real bytes of ``git status --porcelain=v2 --branch -z`` for a repo."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
        ],
        capture_output=True,
        check=True,
        env=git_test_env(),
    )
    return result.stdout


def make_bare_and_clone(root: Path) -> tuple[Path, Path]:
    """Create a bare remote and a clone tracking it; return (bare, work)."""
    bare = root / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
        env=git_test_env(),
    )
    work = root / "work"
    subprocess.run(
        ["git", "clone", str(bare), str(work)],
        check=True,
        capture_output=True,
        env=git_test_env(),
    )
    git(work, "config", "user.name", "Test")
    git(work, "config", "user.email", "test@example.com")
    return bare, work


class TempHome:
    """Temporary HOME/TMPDIR with a temp root for throwaway repos."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="stow-sync-test-")
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "TempHome":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------
# T1 Config
# --------------------------------------------------------------------------


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_missing_file_creates_defaults(self) -> None:
        path = self.env.home / ".config" / "stow-sync" / "config.json"
        self.assertFalse(path.exists())
        config = ss.load_config()
        self.assertTrue(path.exists())
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["fetch_minutes"], 15)
        self.assertEqual(config["refresh_minutes"], 5)
        self.assertEqual(config["notify_after_hours"], 0)
        self.assertEqual(len(config["repos"]), 2)
        self.assertEqual(config["repos"][1]["packages"], ["walls"])
        self.assertEqual(config["repos"][0]["packages"], "auto")
        self.assertIn(str(self.env.home / ".config" / "*"), config["watch"])
        self.assertTrue(any("BraveSoftware" in p for p in config["ignore"]))

    def test_created_file_keeps_tilde_defaults_on_disk(self) -> None:
        path = self.env.home / ".config" / "stow-sync" / "config.json"
        ss.load_config()
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["repos"][0]["path"], "~/.dotfiles")
        self.assertEqual(raw["repos"][0]["target"], "~")

    def test_existing_file_is_not_overwritten(self) -> None:
        path = self.env.home / "custom" / "config.json"
        path.parent.mkdir(parents=True)
        custom = {
            "version": 1,
            "repos": [{"path": "~/mine", "target": "~", "packages": ["p"]}],
            "watch": [],
            "ignore": [],
            "fetch_minutes": 99,
            "refresh_minutes": 1,
            "notify_after_hours": 3,
        }
        path.write_text(json.dumps(custom), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        config = ss.load_config(str(path))
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual(config["fetch_minutes"], 99)

    def test_config_path_flag_expands_and_overrides_home(self) -> None:
        path = self.env.root / "elsewhere.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "repos": [{"path": "~/x", "target": "~/t", "packages": "auto"}],
                    "watch": ["~/w"],
                    "ignore": ["~/i"],
                    "fetch_minutes": 15,
                    "refresh_minutes": 5,
                    "notify_after_hours": 0,
                }
            ),
            encoding="utf-8",
        )
        config = ss.load_config(str(path))
        self.assertEqual(config["repos"][0]["path"], str(self.env.home / "x"))
        self.assertEqual(config["repos"][0]["target"], str(self.env.home / "t"))
        self.assertEqual(config["watch"], [str(self.env.home / "w")])
        self.assertEqual(config["ignore"], [str(self.env.home / "i")])

    def test_expand_path_and_to_tilde(self) -> None:
        self.assertEqual(ss.expand_path("~/a/b"), str(self.env.home / "a" / "b"))
        self.assertEqual(ss.to_tilde(str(self.env.home / ".dotfiles")), "~/.dotfiles")
        self.assertEqual(ss.to_tilde(str(self.env.home)), "~")
        self.assertEqual(ss.to_tilde("/etc/hosts"), "/etc/hosts")


# --------------------------------------------------------------------------
# T2 Package auto-detection
# --------------------------------------------------------------------------


class DetectPackagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self.repo = self.env.root / "repo"

    def test_returns_dirs_skips_dotdirs_and_files(self) -> None:
        for name in ("fish", "nvim", ".git", "notes"):
            (self.repo / name).mkdir(parents=True)
        write(self.repo / "README.md", "x\n")
        write(self.repo / "fish" / ".config", "x\n")
        self.assertEqual(ss.detect_packages(str(self.repo)), ["fish", "notes", "nvim"])

    def test_skips_package_that_ignores_everything(self) -> None:
        (self.repo / "fish").mkdir(parents=True)
        (self.repo / "odd").mkdir(parents=True)
        write(self.repo / "odd" / ".stow-local-ignore", ".*\n")
        self.assertEqual(ss.detect_packages(str(self.repo)), ["fish"])

    def test_keeps_package_with_partial_ignore_and_ignore_comments(self) -> None:
        (self.repo / "fish").mkdir(parents=True)
        write(self.repo / "fish" / ".stow-local-ignore", "# comment\n\nREADME.*\n")
        (self.repo / "zen").mkdir(parents=True)
        write(self.repo / "zen" / ".stow-local-ignore", "# only a comment\n")
        self.assertEqual(ss.detect_packages(str(self.repo)), ["fish", "zen"])

    def test_missing_repo_returns_empty(self) -> None:
        self.assertEqual(ss.detect_packages(str(self.repo / "nope")), [])


# --------------------------------------------------------------------------
# T3 Bounded runner
# --------------------------------------------------------------------------


class RunBoundedTests(unittest.TestCase):
    def test_success_captures_output(self) -> None:
        result = ss.run_bounded([sys.executable, "-c", "print('hello')"], timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"hello", result.stdout)

    def test_stdin_is_forwarded(self) -> None:
        result = ss.run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
            timeout=10,
            stdin="payload",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"payload")

    def test_timeout_raises_timeout_expired(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            ss.run_bounded(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=0.3,
            )

    def test_output_overflow_stops_group_and_flags(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import sys, time; sys.stdout.write('x' * 500000); sys.stdout.flush(); time.sleep(30)",
        ]
        started = __import__("time").monotonic()
        result = ss.run_bounded(command, timeout=20, max_output=1000)
        elapsed = __import__("time").monotonic() - started
        self.assertLess(elapsed, 10, "overflow must stop the child, not wait for the timeout")
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), 1000)
        self.assertIn(b"truncated", result.stderr)


# --------------------------------------------------------------------------
# T4 git runner
# --------------------------------------------------------------------------


class GitRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)

    def test_git_env_is_safe_and_noninteractive(self) -> None:
        env = ss.git_env()
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GIT_ASKPASS"], "true")
        self.assertEqual(env["GIT_SSH_COMMAND"], "ssh -oBatchMode=yes")
        self.assertEqual(env["LC_ALL"], "C")

    def test_build_git_argv_with_repo(self) -> None:
        argv = ss.build_git_argv("/tmp/repo", ["status"])
        self.assertEqual(
            argv,
            [
                "git",
                "-C",
                "/tmp/repo",
                "-c",
                "core.hooksPath=",
                "-c",
                "color.ui=false",
                "status",
            ],
        )

    def test_build_git_argv_without_repo(self) -> None:
        argv = ss.build_git_argv(None, ["version"])
        self.assertEqual(
            argv,
            ["git", "-c", "core.hooksPath=", "-c", "color.ui=false", "version"],
        )

    def test_run_git_runs_real_git_in_a_repo(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "init")
        result = ss.run_git(repo, ["rev-parse", "--is-inside-work-tree"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b"true")


# --------------------------------------------------------------------------
# T5 porcelain v2 -z parser
# --------------------------------------------------------------------------


class PorcelainParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)

    def test_branch_upstream_ahead(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "b.txt", "b\n")
        commit_all(work, "c2")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(work))
        self.assertEqual(parsed["branch"], "main")
        self.assertFalse(parsed["detached"])
        self.assertEqual(parsed["upstream"], "origin/main")
        self.assertEqual(parsed["ahead"], 1)
        self.assertEqual(parsed["behind"], 0)

    def test_behind(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self.env.root / "other"
        subprocess.run(
            ["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env()
        )
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(work))
        self.assertEqual(parsed["ahead"], 0)
        self.assertEqual(parsed["behind"], 1)

    def test_changes_untracked_and_paths_with_spaces(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "normal.txt", "a\n")
        write(repo / "with space.txt", "b\n")
        commit_all(repo, "c1")
        git(repo, "mv", "normal.txt", "renamed.txt")
        write(repo / "with space.txt", "changed\n")
        write(repo / "untracked.txt", "u\n")
        write(repo / "sub" / "inside.txt", "x\n")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(repo))

        changes = {entry["path"]: entry for entry in parsed["changes"]}
        self.assertIn("renamed.txt", changes)
        self.assertIn("with space.txt", changes)
        self.assertEqual(changes["renamed.txt"]["x"], "R")
        self.assertEqual(changes["renamed.txt"]["kind"], "renamed")
        self.assertEqual(changes["with space.txt"]["y"], "M")
        self.assertEqual(changes["with space.txt"]["kind"], "modified")
        self.assertEqual(changes["renamed.txt"]["package"], "renamed.txt")

        untracked = {entry["path"] for entry in parsed["untracked"]}
        self.assertEqual(untracked, {"untracked.txt", "sub/inside.txt"})
        self.assertNotIn("normal.txt", changes, "original rename path must be consumed, not emitted")

    def test_package_is_first_path_segment(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "fish" / ".config" / "fish" / "config.fish", "x\n")
        commit_all(repo, "c1")
        write(repo / "fish" / ".config" / "fish" / "config.fish", "y\n")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(repo))
        self.assertEqual(parsed["changes"][0]["package"], "fish")

    def test_unmerged_entry(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "conflict.txt", "base\n")
        commit_all(repo, "base")
        git(repo, "checkout", "-q", "-b", "feature")
        write(repo / "conflict.txt", "feature\n")
        commit_all(repo, "feature")
        git(repo, "checkout", "-q", "main")
        write(repo / "conflict.txt", "main\n")
        commit_all(repo, "main")
        git(repo, "merge", "feature", check=False)
        parsed = ss.parse_porcelain_v2(porcelain_bytes(repo))
        self.assertEqual(len(parsed["changes"]), 1)
        entry = parsed["changes"][0]
        self.assertEqual(entry["path"], "conflict.txt")
        self.assertEqual(entry["kind"], "unmerged")
        self.assertEqual((entry["x"], entry["y"]), ("U", "U"))

    def test_detached_head(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "checkout", "-q", "--detach", "HEAD")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(repo))
        self.assertTrue(parsed["detached"])
        self.assertEqual(parsed["branch"], "(detached)")
        self.assertEqual(parsed["upstream"], "")

    def test_no_upstream(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        parsed = ss.parse_porcelain_v2(porcelain_bytes(repo))
        self.assertEqual(parsed["branch"], "main")
        self.assertEqual(parsed["upstream"], "")
        self.assertEqual(parsed["ahead"], 0)
        self.assertEqual(parsed["behind"], 0)


# --------------------------------------------------------------------------
# T7 state precedence
# --------------------------------------------------------------------------


def state_args(**overrides):
    base = {
        "exists": True,
        "operation": None,
        "detached": False,
        "upstream": "origin/main",
        "ahead": 0,
        "behind": 0,
        "changes": [],
        "untracked": [],
    }
    base.update(overrides)
    return base


class ComputeStateTests(unittest.TestCase):
    def test_missing_wins_over_everything(self) -> None:
        args = state_args(exists=False, operation="merge", detached=True, changes=[{"path": "x"}])
        self.assertEqual(ss.compute_state(**args), "missing")

    def test_operation_wins_over_detached_and_dirty(self) -> None:
        args = state_args(operation="rebase", detached=True, changes=[{"path": "x"}])
        self.assertEqual(ss.compute_state(**args), "operation")

    def test_detached(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(detached=True, upstream="")), "detached")

    def test_no_upstream(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(upstream="")), "no-upstream")

    def test_diverged(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(ahead=2, behind=1)), "diverged")

    def test_diverged_wins_over_dirty(self) -> None:
        args = state_args(ahead=2, behind=1, changes=[{"path": "x"}])
        self.assertEqual(ss.compute_state(**args), "diverged")

    def test_dirty_from_changes(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(changes=[{"path": "x"}])), "dirty")

    def test_dirty_from_untracked(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(untracked=[{"path": "x"}])), "dirty")

    def test_ahead(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(ahead=1)), "ahead")

    def test_behind(self) -> None:
        self.assertEqual(ss.compute_state(**state_args(behind=1)), "behind")

    def test_clean(self) -> None:
        self.assertEqual(ss.compute_state(**state_args()), "clean")


class DetectOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self.repo = self.env.root / "repo"

    def _base_conflict_repo(self) -> None:
        init_repo(self.repo)
        write(self.repo / "conflict.txt", "base\n")
        commit_all(self.repo, "base")
        git(self.repo, "checkout", "-q", "-b", "feature")
        write(self.repo / "conflict.txt", "feature\n")
        commit_all(self.repo, "feature")
        git(self.repo, "checkout", "-q", "main")
        write(self.repo / "conflict.txt", "main\n")
        commit_all(self.repo, "main")

    def test_clean_repo_has_no_operation(self) -> None:
        init_repo(self.repo)
        write(self.repo / "a.txt", "a\n")
        commit_all(self.repo, "c1")
        self.assertIsNone(ss.detect_operation(str(self.repo)))

    def test_detects_merge(self) -> None:
        self._base_conflict_repo()
        git(self.repo, "merge", "feature", check=False)
        self.assertEqual(ss.detect_operation(str(self.repo)), "merge")

    def test_detects_rebase(self) -> None:
        init_repo(self.repo)
        write(self.repo / "conflict.txt", "base\n")
        commit_all(self.repo, "base")
        git(self.repo, "checkout", "-q", "-b", "feature")
        write(self.repo / "conflict.txt", "feature\n")
        commit_all(self.repo, "feature")
        git(self.repo, "checkout", "-q", "main")
        write(self.repo / "conflict.txt", "main\n")
        commit_all(self.repo, "main")
        git(self.repo, "rebase", "feature", check=False)
        self.assertEqual(ss.detect_operation(str(self.repo)), "rebase")

    def test_detects_cherry_pick(self) -> None:
        self._base_conflict_repo()
        git(self.repo, "cherry-pick", "feature", check=False)
        self.assertEqual(ss.detect_operation(str(self.repo)), "cherry-pick")


# --------------------------------------------------------------------------
# T6/T8 status command and CLI
# --------------------------------------------------------------------------


def write_config(path: Path, repos: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repos": repos,
                "watch": [],
                "ignore": [],
                "fetch_minutes": 15,
                "refresh_minutes": 5,
                "notify_after_hours": 0,
            }
        ),
        encoding="utf-8",
    )
    return path


class StatusCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"

    def status(self, *extra: str) -> dict:
        return ss.dispatch(["status", *extra], str(self.config))

    def test_clean_repo_lists_packages_placeholders(self) -> None:
        bare, repo = make_bare_and_clone(self.env.root)
        (repo / "fish").mkdir()
        write(repo / "fish" / ".config", "x\n")
        (repo / "odd").mkdir()
        write(repo / "odd" / ".stow-local-ignore", ".*\n")
        commit_all(repo, "c1")
        git(repo, "push", "-q", "origin", "main")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])

        result = self.status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(result["repos"]), 1)
        entry = result["repos"][0]
        self.assertTrue(entry["exists"])
        self.assertEqual(entry["state"], "clean")
        self.assertEqual(entry["branch"], "main")
        self.assertEqual(entry["packages"], [{"name": "fish", "health": "ok", "pending_links": [], "conflicts": [], "dangling": []}])
        self.assertIsNone(entry["operation"])
        self.assertIsNone(entry["last_fetch"])
        self.assertIsNone(entry["fetch_error"])

    def test_missing_repo_is_missing_without_exception(self) -> None:
        write_config(self.config, [{"path": str(self.env.root / "nope"), "target": "~", "packages": "auto"}])
        result = self.status()
        self.assertTrue(result["ok"])
        entry = result["repos"][0]
        self.assertFalse(entry["exists"])
        self.assertEqual(entry["state"], "missing")

    def test_dirty_repo(self) -> None:
        bare, repo = make_bare_and_clone(self.env.root)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "push", "-q", "origin", "main")
        write(repo / "a.txt", "changed\n")
        write(repo / "new.txt", "n\n")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "dirty")
        self.assertEqual([c["path"] for c in entry["changes"]], ["a.txt"])
        self.assertEqual([u["path"] for u in entry["untracked"]], ["new.txt"])

    def test_ahead(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "b.txt", "b\n")
        commit_all(work, "c2")
        write_config(self.config, [{"path": str(work), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "ahead")
        self.assertEqual(entry["ahead"], 1)
        self.assertEqual(entry["behind"], 0)

    def test_behind(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self.env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env())
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        write_config(self.config, [{"path": str(work), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "behind")
        self.assertEqual(entry["behind"], 1)

    def test_diverged(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self.env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env())
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        write(work / "c.txt", "c\n")
        commit_all(work, "c3")
        git(work, "fetch", "-q", "origin")
        write_config(self.config, [{"path": str(work), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "diverged")
        self.assertEqual(entry["ahead"], 1)
        self.assertEqual(entry["behind"], 1)

    def test_no_upstream(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "no-upstream")
        self.assertEqual(entry["upstream"], "")

    def test_detached(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "checkout", "-q", "--detach", "HEAD")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "detached")
        self.assertEqual(entry["branch"], "(detached)")

    def test_operation(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "conflict.txt", "base\n")
        commit_all(repo, "base")
        git(repo, "checkout", "-q", "-b", "feature")
        write(repo / "conflict.txt", "feature\n")
        commit_all(repo, "feature")
        git(repo, "checkout", "-q", "main")
        write(repo / "conflict.txt", "main\n")
        commit_all(repo, "main")
        git(repo, "merge", "feature", check=False)
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        entry = self.status()["repos"][0]
        self.assertEqual(entry["state"], "operation")
        self.assertEqual(entry["operation"], "merge")

    def test_summary_is_worst_state_and_count(self) -> None:
        bare_a, clean = make_bare_and_clone(self.env.root / "a")
        write(clean / "a.txt", "a\n")
        commit_all(clean, "c1")
        git(clean, "push", "-q", "origin", "main")
        bare_b, dirty = make_bare_and_clone(self.env.root / "b")
        write(dirty / "a.txt", "a\n")
        commit_all(dirty, "c1")
        git(dirty, "push", "-q", "origin", "main")
        write(dirty / "a.txt", "changed\n")
        write(dirty / "new.txt", "n\n")
        write_config(
            self.config,
            [
                {"path": str(clean), "target": "~", "packages": "auto"},
                {"path": str(dirty), "target": "~", "packages": "auto"},
            ],
        )
        summary = self.status()["summary"]
        self.assertEqual(summary["state"], "dirty")
        self.assertEqual(summary["count"], 2)

    def test_fetch_success_sets_last_fetch(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self.env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env())
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        write_config(self.config, [{"path": str(work), "target": "~", "packages": "auto"}])
        result = self.status("--fetch")
        self.assertTrue(result["ok"])
        entry = result["repos"][0]
        self.assertIsNone(entry["fetch_error"])
        self.assertIsNotNone(entry["last_fetch"])
        self.assertEqual(entry["behind"], 1)

    def test_fetch_failure_is_non_fatal(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "remote", "add", "origin", str(self.env.root / "nonexistent.git"))
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        result = self.status("--fetch")
        self.assertTrue(result["ok"])
        entry = result["repos"][0]
        self.assertIsNotNone(entry["fetch_error"])
        self.assertIsNone(entry["last_fetch"])

    def test_status_is_read_only(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        write(repo / "a.txt", "changed\n")
        write(repo / "new.txt", "n\n")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        before_status = git(repo, "status", "--porcelain").stdout
        before_head = git(repo, "rev-parse", "HEAD").stdout
        self.status()
        self.status("--fetch")
        self.assertEqual(git(repo, "status", "--porcelain").stdout, before_status)
        self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def run_main(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = ss.main(argv)
        return code, buffer.getvalue()

    def test_version_prints_json_and_exits_zero(self) -> None:
        code, out = self.run_main(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ok": True, "version": "0.1.0"})

    def test_unknown_command_exits_one(self) -> None:
        code, out = self.run_main(["bogus"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])

    def test_status_with_config_flag(self) -> None:
        bare, repo = make_bare_and_clone(self.env.root)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "push", "-q", "origin", "main")
        config = write_config(
            self.env.root / "custom.json",
            [{"path": str(repo), "target": "~", "packages": "auto"}],
        )
        code, out = self.run_main(["--config", str(config), "status"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["repos"][0]["state"], "clean")

    def test_response_is_capped_at_two_megabytes(self) -> None:
        huge = {"ok": True, "blob": "x" * (3 * 1024 * 1024)}
        with patch.object(ss, "dispatch", return_value=huge):
            code, out = self.run_main(["version"])
        self.assertEqual(code, 1)
        self.assertLessEqual(len(out.encode("utf-8")), ss.MAX_RESPONSE_BYTES + 1)
        self.assertFalse(json.loads(out)["ok"])


if __name__ == "__main__":
    unittest.main()