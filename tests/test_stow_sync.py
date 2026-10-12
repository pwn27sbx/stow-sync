#!/usr/bin/env python3
"""Unit tests for the Stow Sync backend.

All tests use real ``git`` against throwaway repositories created under a
temporary directory, never the owner's real dotfiles repos. The git
environment is isolated from the host's global config, identity and hooks.
"""

from __future__ import annotations

import copy
import errno
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
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


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def stow_apply(repo: Path, target: Path, package: str) -> subprocess.CompletedProcess[str]:
    """Run a real ``stow`` for ``package`` from ``repo`` into ``target``.

    ``HOME`` is the caller's (patched) environment so stow never reads a real
    ``~/.stowrc``.
    """
    return subprocess.run(
        ["stow", "-v", "-d", str(repo), "-t", str(target), package],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
    )


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
# T9/T10 Stow health (real stow 2.4.1 in a temp HOME)
# --------------------------------------------------------------------------


class StowHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.repo = self.home / ".dotfiles"

    def _write_package(self) -> None:
        write(self.repo / "mypkg" / ".config" / "app" / "conf", "hello\n")
        write(self.repo / "mypkg" / ".config" / "app" / "keep", "keep\n")

    def _anti_fold(self) -> None:
        # A real sibling dir forces stow to link files individually instead of
        # folding the whole tree into one directory symlink.
        write(self.home / ".config" / "app" / "sibling", "s\n")

    def test_stow_dry_run_reports_to_stderr_with_empty_stdout(self) -> None:
        self._write_package()
        self._anti_fold()
        result = ss.stow_dry_run(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"LINK: .config/app/conf", result.stderr)

    def test_pending_link_shape_and_tilde_paths(self) -> None:
        self._write_package()
        self._anti_fold()
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(health["name"], "mypkg")
        self.assertEqual(health["health"], "pending")
        self.assertEqual(health["conflicts"], [])
        self.assertEqual(health["dangling"], [])
        self.assertEqual(
            health["pending_links"],
            [
                {"target": "~/.config/app/conf", "source": "~/.dotfiles/mypkg/.config/app/conf"},
                {"target": "~/.config/app/keep", "source": "~/.dotfiles/mypkg/.config/app/keep"},
            ],
        )

    def test_fully_stowed_package_is_ok(self) -> None:
        self._write_package()
        self._anti_fold()
        stow_apply(self.repo, self.home, "mypkg")
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(health["health"], "ok")
        self.assertEqual(health["pending_links"], [])
        self.assertEqual(health["conflicts"], [])
        self.assertEqual(health["dangling"], [])

    def test_real_file_in_the_way_is_a_conflict(self) -> None:
        self._write_package()
        os.remove(self.repo / "mypkg" / ".config" / "app" / "keep")
        self._anti_fold()
        write(self.home / ".config" / "app" / "conf", "real\n")
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(health["health"], "conflicts")
        self.assertEqual(health["pending_links"], [])
        self.assertEqual(len(health["conflicts"]), 1)
        conflict = health["conflicts"][0]
        self.assertEqual(conflict["target"], "~/.config/app/conf")
        self.assertEqual(conflict["source"], "~/.dotfiles/mypkg/.config/app/conf")
        self.assertTrue(
            conflict["message"].startswith(
                "cannot stow .dotfiles/mypkg/.config/app/conf over existing target "
                ".config/app/conf since neither a link nor a directory and --adopt not specified"
            ),
            conflict["message"],
        )

    def test_dangling_link_is_detected_from_the_filesystem(self) -> None:
        self._write_package()
        self._anti_fold()
        stow_apply(self.repo, self.home, "mypkg")
        os.remove(self.repo / "mypkg" / ".config" / "app" / "conf")
        # stow's own dry run does not report the dangling link at all
        dry = ss.stow_dry_run(str(self.repo), str(self.home), "mypkg")
        self.assertNotIn(b"LINK:", dry.stderr)
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(health["health"], "dangling")
        self.assertEqual(health["pending_links"], [])
        self.assertEqual(health["conflicts"], [])
        self.assertEqual(
            health["dangling"],
            [{"target": "~/.config/app/conf", "source": "~/.dotfiles/mypkg/.config/app/conf"}],
        )

    def test_health_precedence_conflicts_beat_pending(self) -> None:
        self._write_package()
        os.remove(self.repo / "mypkg" / ".config" / "app" / "keep")
        self._anti_fold()
        write(self.home / ".config" / "app" / "conf", "real\n")  # conflict
        write(self.repo / "mypkg" / ".config" / "app" / "new", "new\n")  # pending
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(len(health["conflicts"]), 1)
        self.assertEqual(len(health["pending_links"]), 1)
        self.assertEqual(health["health"], "conflicts")

    def test_health_precedence_dangling_beats_pending(self) -> None:
        self._write_package()
        self._anti_fold()
        stow_apply(self.repo, self.home, "mypkg")
        os.remove(self.repo / "mypkg" / ".config" / "app" / "keep")  # dangling
        write(self.repo / "mypkg" / ".config" / "app" / "added", "added\n")  # pending
        health = ss.package_health(str(self.repo), str(self.home), "mypkg")
        self.assertEqual(len(health["dangling"]), 1)
        self.assertEqual(len(health["pending_links"]), 1)
        self.assertEqual(health["health"], "dangling")


class ConflictFixtureTests(unittest.TestCase):
    def test_pinned_fixture_parses_real_stow_wording(self) -> None:
        fixture = (FIXTURES / "stow_conflict_stderr.txt").read_text(encoding="utf-8")
        self.assertIn("would cause conflicts:", fixture)
        self.assertIn("neither a link nor a directory and --adopt not specified", fixture)
        self.assertIn("All operations aborted.", fixture)
        target_dir = "/tmp/target"
        conflicts = ss.parse_conflicts(fixture, target_dir)
        self.assertEqual(len(conflicts), 1)
        conflict = conflicts[0]
        self.assertEqual(ss.to_tilde(conflict["target"]), ss.to_tilde(os.path.join(target_dir, ".config/app/conf")))
        self.assertEqual(
            ss.to_tilde(conflict["source"]),
            ss.to_tilde(os.path.normpath(os.path.join(target_dir, "../crepo/mypkg/.config/app/conf"))),
        )
        self.assertEqual(
            conflict["message"],
            "cannot stow ../crepo/mypkg/.config/app/conf over existing target "
            ".config/app/conf since neither a link nor a directory and --adopt not specified",
        )

    def test_pinned_not_owned_fixture_parses_real_stow_wording(self) -> None:
        fixture = (FIXTURES / "stow_conflict_not_owned_stderr.txt").read_text(encoding="utf-8")
        self.assertIn("existing target is not owned by stow", fixture)
        target_dir = "/tmp/target"
        entries = ss.parse_conflict_entries(fixture, target_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["form"], "not-owned")
        self.assertEqual(entries[0]["target_abs"], os.path.join(target_dir, ".config/app/conf"))
        self.assertEqual(entries[0]["source_abs"], "")
        self.assertEqual(
            entries[0]["message"], "existing target is not owned by stow: .config/app/conf"
        )


# --------------------------------------------------------------------------
# T11 Candidates (README section 5.3)
# --------------------------------------------------------------------------


class CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.repo = self.home / ".dotfiles"

    def _candidates(self, watch, ignore=None, repos=None):
        config = {
            "repos": repos or [],
            "watch": watch,
            "ignore": ignore or [],
        }
        return ss.compute_candidates(config)

    def test_plain_watch_dir_children_are_watched(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "#!/bin/sh\n")
        write(self.home / ".local" / "bin" / "other", "x\n")
        candidates = self._candidates(["~/.local/bin"])
        by_path = {c["path"]: c for c in candidates}
        self.assertEqual(set(by_path), {"~/.local/bin/tool", "~/.local/bin/other"})
        for candidate in by_path.values():
            self.assertEqual(candidate["group"], "watched")
            self.assertEqual(candidate["type"], "file")

    def test_glob_matches_are_group_other(self) -> None:
        write(self.home / ".config" / "foo.conf", "x\n")
        write(self.home / ".config" / "kitty" / "kitty.conf", "k\n")
        candidates = self._candidates(["~/.config/*"])
        by_path = {c["path"]: c for c in candidates}
        self.assertEqual(set(by_path), {"~/.config/foo.conf", "~/.config/kitty"})
        self.assertEqual(by_path["~/.config/foo.conf"]["group"], "other")
        self.assertEqual(by_path["~/.config/foo.conf"]["type"], "file")
        self.assertEqual(by_path["~/.config/kitty"]["group"], "other")
        self.assertEqual(by_path["~/.config/kitty"]["type"], "dir")

    def test_ignore_glob_skips_matching_children(self) -> None:
        write(self.home / ".config" / "systemd" / "user" / "app.service", "x\n")
        write(self.home / ".config" / "systemd" / "user" / "foo.wants" / "x", "x\n")
        candidates = self._candidates(
            ["~/.config/systemd/user"],
            ignore=["~/.config/systemd/user/*.wants"],
        )
        self.assertEqual([c["path"] for c in candidates], ["~/.config/systemd/user/app.service"])

    def test_symlink_into_repo_is_not_a_candidate(self) -> None:
        write(self.repo / "ai-tools" / ".config" / "systemd" / "user" / "ai-tools-check.timer", "t\n")
        # real file first so stow links the .timer individually (no tree folding)
        write(self.home / ".config" / "systemd" / "user" / "other.service", "x\n")
        stow_apply(self.repo, self.home, "ai-tools")
        candidates = self._candidates(
            ["~/.config/systemd/user"],
            repos=[{"path": str(self.repo), "target": str(self.home), "packages": ["ai-tools"]}],
        )
        self.assertEqual([c["path"] for c in candidates], ["~/.config/systemd/user/other.service"])

    def test_candidate_inside_stowed_directory_is_skipped(self) -> None:
        write(self.repo / "mycfg" / ".config" / "myapp" / "settings", "s\n")
        # Home has no .config yet, so stow folds the whole tree into one symlink.
        stow_apply(self.repo, self.home, "mycfg")
        self.assertTrue(os.path.islink(self.home / ".config"))
        candidates = self._candidates(
            ["~/.config/*"],
            repos=[{"path": str(self.repo), "target": str(self.home), "packages": ["mycfg"]}],
        )
        self.assertEqual(candidates, [])

    def test_badge_counts_unknown_candidates(self) -> None:
        candidates = [
            {"group": "watched", "known": False},
            {"group": "other", "known": True},
            {"group": "other", "known": False},
        ]
        self.assertEqual(ss.compute_badge(candidates), 2)

    def test_sibling_package_suggestion_wins(self) -> None:
        write(self.repo / "ai-tools" / ".config" / "systemd" / "user" / "ai-tools-check.timer", "t\n")
        write(self.home / ".config" / "systemd" / "user" / "easyeffects.service", "x\n")
        stow_apply(self.repo, self.home, "ai-tools")
        candidates = self._candidates(
            ["~/.config/systemd/user"],
            repos=[{"path": str(self.repo), "target": str(self.home), "packages": ["ai-tools"]}],
        )
        self.assertEqual([c["path"] for c in candidates], ["~/.config/systemd/user/easyeffects.service"])
        self.assertEqual(candidates[0]["suggested_package"], "ai-tools")

    def test_suggestion_fallback_user_becomes_systemd(self) -> None:
        write(self.home / ".config" / "systemd" / "user" / "easyeffects.service", "x\n")
        candidates = self._candidates(["~/.config/systemd/user"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["suggested_package"], "systemd")

    def test_suggestion_fallback_for_directory_is_basename(self) -> None:
        write(self.home / ".config" / "kitty" / "kitty.conf", "k\n")
        candidates = self._candidates(["~/.config/*"])
        self.assertEqual([c["path"] for c in candidates], ["~/.config/kitty"])
        self.assertEqual(candidates[0]["suggested_package"], "kitty")

    def test_directory_candidate_suggests_own_name_over_stowed_sibling(self) -> None:
        # A stowed app (cava) already owns a sibling in ~/.config; a new
        # directory candidate must suggest its own name, not that app.
        write(self.repo / "cava" / ".config" / "cava" / "conf", "c\n")
        write(self.home / ".config" / "keep.conf", "k\n")  # keep ~/.config a real dir
        stow_apply(self.repo, self.home, "cava")
        write(self.home / ".config" / "stow-sync" / "config.json", "{}\n")
        candidates = self._candidates(
            ["~/.config/*"],
            repos=[{"path": str(self.repo), "target": str(self.home), "packages": ["cava"]}],
        )
        by_path = {c["path"]: c for c in candidates}
        self.assertIn("~/.config/stow-sync", by_path)
        self.assertEqual(by_path["~/.config/stow-sync"]["type"], "dir")
        self.assertEqual(by_path["~/.config/stow-sync"]["suggested_package"], "stow-sync")

    def test_candidate_fields_are_exact(self) -> None:
        content = "hello\n"
        write(self.home / ".local" / "bin" / "tool", content)
        candidates = self._candidates(["~/.local/bin"])
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(
            set(candidate),
            {"path", "type", "size", "mtime", "group", "suggested_package", "known"},
        )
        self.assertFalse(candidate["known"])
        self.assertEqual(candidate["size"], len(content.encode("utf-8")))
        self.assertEqual(datetime.fromisoformat(candidate["mtime"]).tzinfo is not None, True)

    def test_oversized_candidate_is_skipped(self) -> None:
        big = self.home / ".local" / "bin" / "big.bin"
        big.parent.mkdir(parents=True, exist_ok=True)
        with open(big, "wb") as handle:
            handle.seek(ss.MAX_CANDIDATE_SIZE + 1)
            handle.write(b"x")
        write(self.home / ".local" / "bin" / "small", "s\n")
        candidates = self._candidates(["~/.local/bin"])
        self.assertEqual([c["path"] for c in candidates], ["~/.local/bin/small"])

    def test_candidate_size_stops_once_over_the_cap(self) -> None:
        # `status --short` must stay fast: an over-cap directory only needs to
        # be known as "over", so the recursive walk stops at the first file
        # that pushes the total past MAX_CANDIDATE_SIZE.
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.bin", "b.bin"):
                with open(os.path.join(tmp, name), "wb") as handle:
                    handle.truncate(ss.MAX_CANDIDATE_SIZE + 1)
            size = ss._candidate_size(tmp)
            self.assertGreater(size, ss.MAX_CANDIDATE_SIZE)
            self.assertLess(size, 2 * (ss.MAX_CANDIDATE_SIZE + 1))

    def test_special_file_is_skipped(self) -> None:
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        os.mkfifo(bindir / "pipe")
        write(bindir / "tool", "x\n")
        candidates = self._candidates(["~/.local/bin"])
        self.assertEqual([c["path"] for c in candidates], ["~/.local/bin/tool"])


# --------------------------------------------------------------------------
# Compiled binaries (README section 5.3b item 1)
# --------------------------------------------------------------------------

MACHO_MAGICS = (
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)


class CompiledBinaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home

    def _candidates(self, watch):
        return ss.compute_candidates({"repos": [], "watch": watch, "ignore": []})

    def test_is_compiled_binary_detects_elf_and_macho_magics(self) -> None:
        elf = self.home / "elf"
        write_bytes(elf, b"\x7fELF\x02\x01\x01\x00")
        self.assertTrue(ss.is_compiled_binary(str(elf)))
        for index, magic in enumerate(MACHO_MAGICS):
            path = self.home / f"macho-{index}"
            write_bytes(path, magic + b"\x00\x00\x00\x00")
            self.assertTrue(ss.is_compiled_binary(str(path)), magic)

    def test_is_compiled_binary_is_false_for_text_scripts_and_missing(self) -> None:
        script = self.home / "script"
        write(script, "#!/bin/sh\necho hi\n")
        self.assertFalse(ss.is_compiled_binary(str(script)))
        self.assertFalse(ss.is_compiled_binary(str(self.home / "missing")))

    def test_elf_and_macho_candidates_are_skipped_text_kept(self) -> None:
        write_bytes(self.home / ".local" / "bin" / "elf", b"\x7fELF\x02\x01\x01\x00")
        write_bytes(self.home / ".local" / "bin" / "macho", b"\xcf\xfa\xed\xfe\x00\x00\x00\x00")
        write(self.home / ".local" / "bin" / "script", "#!/bin/sh\necho hi\n")
        candidates = self._candidates(["~/.local/bin"])
        self.assertEqual([c["path"] for c in candidates], ["~/.local/bin/script"])


# --------------------------------------------------------------------------
# T12 status integration: real package health, candidates, summary
# --------------------------------------------------------------------------


class StatusIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.config = self.env.root / "config.json"

    def status(self, *extra: str) -> dict:
        return ss.dispatch(["status", *extra], str(self.config))

    def _clean_repo(self, files: dict[str, str]) -> Path:
        repo = self.home / ".dotfiles"
        init_repo(repo)
        for rel, content in files.items():
            write(repo / rel, content)
        commit_all(repo, "c1")
        bare = self.env.root / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
            env=git_test_env(),
        )
        git(repo, "remote", "add", "origin", str(bare))
        git(repo, "push", "-u", "-q", "origin", "main")
        return repo

    def test_status_reports_pending_package_and_summary_state(self) -> None:
        repo = self._clean_repo({"mypkg/.config/app/conf": "hello\n"})
        write_config(self.config, [{"path": str(repo), "target": str(self.home), "packages": "auto"}])
        result = self.status()
        entry = result["repos"][0]
        self.assertEqual(entry["state"], "clean")
        self.assertEqual(
            entry["packages"],
            [
                {
                    "name": "mypkg",
                    "health": "pending",
                    "pending_links": [{"target": "~/.config", "source": "~/.dotfiles/mypkg/.config"}],
                    "conflicts": [],
                    "dangling": [],
                }
            ],
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["summary"]["state"], "pending")
        self.assertEqual(result["summary"]["count"], 1)

    def test_status_uses_explicit_package_list(self) -> None:
        repo = self._clean_repo(
            {
                "mypkg/.config/app/conf": "hello\n",
                "other/.config/other/conf": "x\n",
            }
        )
        write_config(self.config, [{"path": str(repo), "target": str(self.home), "packages": ["other"]}])
        entry = self.status()["repos"][0]
        self.assertEqual([package["name"] for package in entry["packages"]], ["other"])

    def test_summary_state_is_conflict_for_stow_conflict(self) -> None:
        repo = self._clean_repo({"mypkg/.config/app/conf": "hello\n"})
        write(self.home / ".config" / "app" / "sibling", "s\n")
        write(self.home / ".config" / "app" / "conf", "real\n")
        write_config(self.config, [{"path": str(repo), "target": str(self.home), "packages": "auto"}])
        result = self.status()
        self.assertEqual(result["repos"][0]["packages"][0]["health"], "conflicts")
        self.assertEqual(result["summary"]["state"], "conflict")
        self.assertEqual(result["summary"]["count"], 1)

    def test_first_run_baseline_marks_candidates_known(self) -> None:
        repo = self._clean_repo({"mypkg/.config/app/conf": "hello\n"})
        write(self.home / ".local" / "bin" / "tool", "x\n")
        write_config(
            self.config,
            [{"path": str(repo), "target": str(self.home), "packages": "auto"}],
            watch=["~/.local/bin"],
        )
        result = self.status()
        self.assertEqual([c["path"] for c in result["candidates"]], ["~/.local/bin/tool"])
        self.assertEqual(result["candidates"][0]["group"], "watched")
        self.assertTrue(result["candidates"][0]["known"])
        self.assertEqual(result["summary"]["state"], "pending")
        # 1 pending link; the candidate is now known, so it no longer counts.
        self.assertEqual(result["summary"]["count"], 1)

    def test_summary_count_includes_dangling(self) -> None:
        repo = self._clean_repo(
            {
                "mypkg/.config/app/conf": "hello\n",
                "mypkg/.config/app/keep": "keep\n",
            }
        )
        write(self.home / ".config" / "app" / "sibling", "s\n")
        stow_apply(repo, self.home, "mypkg")
        os.remove(repo / "mypkg" / ".config" / "app" / "conf")
        commit_all(repo, "remove conf")
        git(repo, "push", "-q", "origin", "main")
        write_config(self.config, [{"path": str(repo), "target": str(self.home), "packages": "auto"}])
        result = self.status()
        entry = result["repos"][0]
        self.assertEqual(entry["state"], "clean")
        self.assertEqual(entry["packages"][0]["health"], "dangling")
        self.assertEqual(result["summary"]["state"], "dangling")
        self.assertEqual(result["summary"]["count"], 1)

    def test_package_state_rank_pins_severity_order(self) -> None:
        rank = ss._STATE_RANK
        self.assertGreater(rank["pending"], rank["clean"])
        self.assertGreater(rank["dangling"], rank["dirty"])
        self.assertGreater(rank["conflict"], rank["dirty"])
        self.assertGreater(rank["missing"], rank["conflict"])
        self.assertGreater(rank["operation"], rank["conflict"])


# --------------------------------------------------------------------------
# T6/T8 status command and CLI
# --------------------------------------------------------------------------


def write_config(
    path: Path,
    repos: list[dict],
    watch: list[str] | None = None,
    ignore: list[str] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repos": repos,
                "watch": watch or [],
                "ignore": ignore or [],
                "fetch_minutes": 15,
                "refresh_minutes": 5,
                "notify_after_hours": 0,
            }
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# First-run baseline (README section 5.3b items 2-6)
# --------------------------------------------------------------------------


class BaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        os.environ.pop("STOW_SYNC_STATE_DIR", None)
        self.addCleanup(lambda: os.environ.pop("STOW_SYNC_STATE_DIR", None))
        self.home = self.env.home
        self.config = self.env.root / "config.json"
        self.state_dir = self.env.root / "state"
        write_config(self.config, [], watch=["~/.local/bin"])
        self.baseline_file = self.state_dir / "baseline.json"

    def status(self, *extra: str) -> dict:
        return ss.dispatch(["status", *extra], str(self.config), str(self.state_dir))

    def baseline(self, *extra: str) -> dict:
        return ss.dispatch(["baseline", *extra], str(self.config), str(self.state_dir))

    def test_resolve_state_dir_precedence(self) -> None:
        explicit = self.env.root / "explicit"
        self.assertEqual(ss.resolve_state_dir(str(explicit)), str(explicit))
        with patch.dict(os.environ, {"STOW_SYNC_STATE_DIR": "~/envstate"}):
            self.assertEqual(ss.resolve_state_dir(None), str(self.home / "envstate"))
        os.environ.pop("STOW_SYNC_STATE_DIR", None)
        self.assertEqual(
            ss.resolve_state_dir(None),
            str(self.home / ".local" / "state" / "stow-sync"),
        )

    def test_first_status_creates_baseline_with_current_candidates(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        write(self.home / ".local" / "bin" / "other", "y\n")
        self.assertFalse(self.baseline_file.exists())
        result = self.status()
        self.assertTrue(result["ok"])
        paths = {c["path"] for c in result["candidates"]}
        self.assertEqual(paths, {"~/.local/bin/tool", "~/.local/bin/other"})
        self.assertIsNone(result["baseline_error"])
        data = json.loads(self.baseline_file.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(set(data["paths"]), paths)
        self.assertIsNotNone(data["created"])
        self.assertEqual(os.stat(self.baseline_file).st_mode & 0o777, 0o600)
        self.assertTrue(all(c["known"] for c in result["candidates"]))
        self.assertEqual(result["summary"]["count"], 0)

    def test_second_run_reads_baseline_and_marks_known(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        self.status()
        result = self.status()
        self.assertEqual([c["path"] for c in result["candidates"]], ["~/.local/bin/tool"])
        self.assertTrue(result["candidates"][0]["known"])
        self.assertIsNone(result["baseline_error"])
        self.assertEqual(result["summary"]["count"], 0)

    def test_file_created_after_baseline_is_unknown_and_counted(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        self.status()
        write(self.home / ".local" / "bin" / "newtool", "n\n")
        result = self.status()
        by_path = {c["path"]: c for c in result["candidates"]}
        self.assertTrue(by_path["~/.local/bin/tool"]["known"])
        self.assertFalse(by_path["~/.local/bin/newtool"]["known"])
        self.assertEqual(ss.compute_badge(result["candidates"]), 1)
        self.assertEqual(result["summary"]["count"], 1)

    def test_known_file_modified_later_stays_known(self) -> None:
        target = self.home / ".local" / "bin" / "tool"
        write(target, "x\n")
        self.status()
        write(target, "changed\n")
        stamp = time.time() + 100
        os.utime(target, (stamp, stamp))
        result = self.status()
        self.assertTrue(result["candidates"][0]["known"])
        self.assertEqual(result["summary"]["count"], 0)

    def test_baseline_reset_picks_up_new_file(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        self.status()
        write(self.home / ".local" / "bin" / "newtool", "n\n")
        self.assertEqual(self.status()["summary"]["count"], 1)
        reset = self.baseline("--reset")
        self.assertTrue(reset["ok"])
        self.assertFalse(reset["dry_run"])
        self.assertEqual(reset["paths"], 2)
        self.assertIsNotNone(reset["created"])
        after = self.status()
        self.assertTrue(all(c["known"] for c in after["candidates"]))
        self.assertEqual(after["summary"]["count"], 0)

    def test_baseline_dry_run_writes_nothing(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        result = self.baseline("--dry-run")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["paths"], 1)
        self.assertIsNone(result["created"])
        self.assertFalse(self.baseline_file.exists())

    def test_readonly_state_dir_without_baseline_reports_error_not_crash(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        os.makedirs(self.state_dir, 0o555, exist_ok=True)
        try:
            result = self.status()
        finally:
            os.chmod(self.state_dir, 0o755)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["baseline_error"])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertFalse(result["candidates"][0]["known"])
        self.assertFalse(self.baseline_file.exists())


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

    def test_clean_repo_reports_stowed_package_health(self) -> None:
        bare, repo = make_bare_and_clone(self.env.root)
        (repo / "fish").mkdir()
        write(repo / "fish" / ".config", "x\n")
        (repo / "odd").mkdir()
        write(repo / "odd" / ".stow-local-ignore", ".*\n")
        commit_all(repo, "c1")
        git(repo, "push", "-q", "origin", "main")
        stow_apply(repo, self.env.home, "fish")
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

    def test_status_with_state_dir_flag(self) -> None:
        write(self.env.home / ".local" / "bin" / "tool", "x\n")
        config = write_config(
            self.env.root / "custom.json",
            [],
            watch=["~/.local/bin"],
        )
        state = self.env.root / "state"
        code, out = self.run_main(["--config", str(config), "--state-dir", str(state), "status"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertTrue(parsed["ok"])
        self.assertEqual([c["path"] for c in parsed["candidates"]], ["~/.local/bin/tool"])
        self.assertTrue(parsed["candidates"][0]["known"])
        self.assertIsNone(parsed["baseline_error"])
        self.assertTrue((state / "baseline.json").exists())

    def test_state_dir_equals_form_is_accepted(self) -> None:
        write(self.env.home / ".local" / "bin" / "tool", "x\n")
        config = write_config(self.env.root / "custom.json", [], watch=["~/.local/bin"])
        state = self.env.root / "state-eq"
        code, out = self.run_main([f"--config={config}", f"--state-dir={state}", "status"])
        self.assertEqual(code, 0)
        self.assertTrue((state / "baseline.json").exists())

    def test_response_is_capped_at_two_megabytes(self) -> None:
        huge = {"ok": True, "blob": "x" * (3 * 1024 * 1024)}
        with patch.object(ss, "dispatch", return_value=huge):
            code, out = self.run_main(["version"])
        self.assertEqual(code, 1)
        self.assertLessEqual(len(out.encode("utf-8")), ss.MAX_RESPONSE_BYTES + 1)
        self.assertFalse(json.loads(out)["ok"])


# --------------------------------------------------------------------------
# Unit 3: shared repo resolution and path validation
# --------------------------------------------------------------------------


class ResolveRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.repo = self.env.home / "repo"
        self.config = {
            "repos": [{"path": "~/repo", "target": "~", "packages": "auto"}],
            "watch": [],
            "ignore": [],
        }

    def test_resolves_expanded_path(self) -> None:
        found = ss.resolve_repo(self.config, "~/repo")
        self.assertEqual(found["path"], str(self.repo))

    def test_unknown_repo_raises_command_error(self) -> None:
        with self.assertRaises(ss.CommandError):
            ss.resolve_repo(self.config, "~/other")
        with self.assertRaises(ss.CommandError):
            ss.resolve_repo(self.config, None)


class ValidateRelpathTests(unittest.TestCase):
    def test_accepts_relative(self) -> None:
        self.assertEqual(
            ss.validate_repo_relpath("fish/.config/fish/config.fish"),
            "fish/.config/fish/config.fish",
        )

    def test_rejects_absolute(self) -> None:
        with self.assertRaises(ss.CommandError):
            ss.validate_repo_relpath("/etc/passwd")

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(ss.CommandError):
            ss.validate_repo_relpath("../secret")
        with self.assertRaises(ss.CommandError):
            ss.validate_repo_relpath("fish/../../secret")

    def test_rejects_nul_and_tilde(self) -> None:
        with self.assertRaises(ss.CommandError):
            ss.validate_repo_relpath("a\x00b")
        with self.assertRaises(ss.CommandError):
            ss.validate_repo_relpath("~/x")


class RunGitStdinTests(unittest.TestCase):
    def test_run_git_forwards_stdin(self) -> None:
        result = ss.run_git(None, ["hash-object", "--stdin"], stdin="hello\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b"ce013625030ba8dba906f756967f9e9ca394464a")


class DiffCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"

    def _repo(self) -> Path:
        repo = self.env.home / ".dotfiles"
        init_repo(repo)
        write(repo / "a.txt", "old\n")
        commit_all(repo, "c1")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        return repo

    def diff(self, repo: Path, path: str) -> dict:
        return ss.dispatch(["diff", "--repo", str(repo), "--path", path], str(self.config))

    def test_unstaged_diff_text_and_not_truncated(self) -> None:
        repo = self._repo()
        write(repo / "a.txt", "new\n")
        result = self.diff(repo, "a.txt")
        self.assertTrue(result["ok"])
        self.assertIn("-old", result["text"])
        self.assertIn("+new", result["text"])
        self.assertFalse(result["truncated"])

    def test_falls_back_to_cached_diff(self) -> None:
        repo = self._repo()
        write(repo / "a.txt", "staged\n")
        git(repo, "add", "a.txt")
        result = self.diff(repo, "a.txt")
        self.assertTrue(result["ok"])
        self.assertIn("+staged", result["text"])
        self.assertFalse(result["truncated"])

    def test_truncates_at_400_lines(self) -> None:
        repo = self._repo()
        write(repo / "big.txt", "".join(f"line-{i}\n" for i in range(600)))
        commit_all(repo, "big")
        write(repo / "big.txt", "".join(f"changed-{i}\n" for i in range(600)))
        result = self.diff(repo, "big.txt")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"].splitlines()), ss.DIFF_MAX_LINES)

    def test_truncates_at_32_kilobytes(self) -> None:
        repo = self._repo()
        write(repo / "long.txt", "seed\n")
        commit_all(repo, "long")
        write(repo / "long.txt", ("y" * 60000) + "\n")
        result = self.diff(repo, "long.txt")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"].encode("utf-8")), ss.DIFF_MAX_BYTES)

    def test_unknown_repo_is_error(self) -> None:
        self._repo()
        result = ss.dispatch(["diff", "--repo", str(self.env.home / "nope"), "--path", "a.txt"], str(self.config))
        self.assertFalse(result["ok"])
        self.assertIn("repo", result["error"].lower())

    def test_absolute_path_is_rejected(self) -> None:
        repo = self._repo()
        result = self.diff(repo, "/etc/passwd")
        self.assertFalse(result["ok"])


# --------------------------------------------------------------------------
# Unit 3: secret scan (README section 6)
# --------------------------------------------------------------------------

SECRET_SAMPLES = [
    ("private-key", "-----BEGIN RSA PRIVATE KEY-----"),
    ("github-token", "ghp_" + "A" * 36),
    ("github-pat", "github_pat_" + "A" * 60),
    ("aws-access-key", "AKIA" + "A" * 16),
    ("slack-token", "xoxb-" + "A" * 10),
    ("openai-key", "sk-" + "A" * 32),
    ("google-api-key", "AIza" + "A" * 35),
    ("assignment", "password = \"supersecretvalue\""),
]


def synthetic_diff(path: str, line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{line}\n"
    )


class SecretScanTests(unittest.TestCase):
    def test_every_rule_is_detected(self) -> None:
        for rule, sample in SECRET_SAMPLES:
            found = ss.scan_secrets(synthetic_diff("file.txt", sample))
            self.assertEqual([entry["rule"] for entry in found], [rule], sample)

    def test_clean_line_has_no_secrets(self) -> None:
        self.assertEqual(ss.scan_secrets(synthetic_diff("file.txt", "just a normal line")), [])

    def test_path_and_line_number_are_reported(self) -> None:
        found = ss.scan_secrets(synthetic_diff("dir/secret.env", "ghp_" + "A" * 36))
        self.assertEqual(found[0]["path"], "dir/secret.env")
        self.assertEqual(found[0]["line"], 1)

    def test_line_numbers_track_hunks(self) -> None:
        diff = (
            "diff --git a/f b/f\n"
            "--- a/f\n"
            "+++ b/f\n"
            "@@ -1,2 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            "+ghp_" + "A" * 36 + "\n"
        )
        found = ss.scan_secrets(diff)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["path"], "f")
        self.assertEqual(found[0]["line"], 3)


class CommitCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"
        self.repo = self.env.home / ".dotfiles"
        init_repo(self.repo)
        write(self.repo / "a.txt", "a\n")
        commit_all(self.repo, "c1")
        write_config(self.config, [{"path": str(self.repo), "target": "~", "packages": "auto"}])

    def run_stdin(self, payload, *extra: str) -> dict:
        argv = ["commit", "--repo", str(self.repo), *extra]
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            return ss.dispatch(argv, str(self.config))

    def test_commit_only_selected_paths(self) -> None:
        write(self.repo / "b.txt", "b\n")
        write(self.repo / "c.txt", "c\n")
        result = self.run_stdin({"message": "chore: add b", "paths": ["b.txt"]})
        self.assertTrue(result["ok"])
        self.assertRegex(result["commit"], r"^[0-9a-f]{7,40}$")
        self.assertEqual(result["secrets"], [])
        message = git(self.repo, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(message, "chore: add b")
        porcelain = git(self.repo, "status", "--porcelain").stdout
        self.assertIn("?? c.txt", porcelain)
        self.assertNotIn("b.txt", porcelain)

    def test_empty_message_is_refused(self) -> None:
        write(self.repo / "b.txt", "b\n")
        result = self.run_stdin({"message": "   ", "paths": ["b.txt"]})
        self.assertFalse(result["ok"])
        self.assertEqual(git(self.repo, "log", "--oneline").stdout.count("\n"), 1)

    def test_missing_path_is_refused(self) -> None:
        result = self.run_stdin({"message": "chore: nope", "paths": ["missing.txt"]})
        self.assertFalse(result["ok"])
        self.assertIn("missing.txt", result["error"])

    def test_each_secret_rule_blocks_the_commit(self) -> None:
        for index, (rule, sample) in enumerate(SECRET_SAMPLES):
            name = f"secret-{index}.txt"
            write(self.repo / name, sample + "\n")
            result = self.run_stdin({"message": "chore: secret", "paths": [name]})
            self.assertFalse(result["ok"], rule)
            self.assertEqual([entry["rule"] for entry in result["secrets"]], [rule], rule)
            self.assertEqual(result["secrets"][0]["path"], name)
            git(self.repo, "reset", "-q")
            os.remove(self.repo / name)

    def test_secret_value_is_never_echoed(self) -> None:
        token = "ghp_" + "A" * 36
        write(self.repo / "leak.txt", "token = " + token + "\n")
        result = self.run_stdin({"message": "chore: leak", "paths": ["leak.txt"]})
        self.assertFalse(result["ok"])
        self.assertNotIn(token, json.dumps(result))

    def test_secret_block_leaves_index_staged_and_retry_succeeds(self) -> None:
        token = "ghp_" + "A" * 36
        write(self.repo / "leak.txt", token + "\n")
        blocked = self.run_stdin({"message": "chore: leak", "paths": ["leak.txt"]})
        self.assertFalse(blocked["ok"])
        staged = git(self.repo, "diff", "--cached", "--name-only").stdout
        self.assertIn("leak.txt", staged)
        retry = self.run_stdin(
            {"message": "chore: leak", "paths": ["leak.txt"], "allow_secrets": True}
        )
        self.assertTrue(retry["ok"])
        self.assertEqual(retry["secrets"], [])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s").stdout.strip(), "chore: leak")


# --------------------------------------------------------------------------
# Unit 3: push and pull
# --------------------------------------------------------------------------


class PushPullCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"

    def _use(self, repo: Path) -> None:
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])

    def _clone_other(self, bare: Path) -> Path:
        other = self.env.root / "other"
        subprocess.run(
            ["git", "clone", str(bare), str(other)],
            check=True,
            capture_output=True,
            env=git_test_env(),
        )
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        return other

    def push(self, repo: Path) -> dict:
        return ss.dispatch(["push", "--repo", str(repo)], str(self.config))

    def pull(self, repo: Path) -> dict:
        return ss.dispatch(["pull", "--repo", str(repo)], str(self.config))

    def test_push_success(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "b.txt", "b\n")
        commit_all(work, "c2")
        self._use(work)
        result = self.push(work)
        self.assertTrue(result["ok"])
        self.assertTrue(result["pushed"])
        remote_head = git(bare, "rev-parse", "main").stdout.strip()
        local_head = git(work, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_head, local_head)

    def test_push_non_fast_forward_is_non_fatal(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self._clone_other(bare)
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        write(work / "c.txt", "c\n")
        commit_all(work, "c3")
        self._use(work)
        result = self.push(work)
        self.assertTrue(result["ok"])
        self.assertNotIn("pushed", result)
        self.assertIn("push_error", result)
        self.assertIn("Pull first", result["push_error"])

    def test_pull_fast_forward(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self._clone_other(bare)
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        self._use(work)
        result = self.pull(work)
        self.assertTrue(result["ok"])
        self.assertTrue(result["pulled"])
        self.assertEqual(
            git(work, "rev-parse", "HEAD").stdout.strip(),
            git(bare, "rev-parse", "main").stdout.strip(),
        )

    def test_pull_refuses_dirty_worktree(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self._clone_other(bare)
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        write(work / "a.txt", "changed\n")
        self._use(work)
        result = self.pull(work)
        self.assertFalse(result["ok"])
        self.assertIn("uncommitted", result["error"])

    def test_pull_refuses_untracked_worktree(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "new.txt", "n\n")
        self._use(work)
        result = self.pull(work)
        self.assertFalse(result["ok"])
        self.assertIn("uncommitted", result["error"])

    def test_pull_refuses_diverged(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self._clone_other(bare)
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        write(work / "c.txt", "c\n")
        commit_all(work, "c3")
        git(work, "fetch", "-q", "origin")
        self._use(work)
        result = self.pull(work)
        self.assertFalse(result["ok"])
        self.assertIn("diverged", result["error"].lower())

    def test_pull_refuses_no_upstream(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        self._use(repo)
        result = self.pull(repo)
        self.assertFalse(result["ok"])
        self.assertIn("upstream", result["error"].lower())


# --------------------------------------------------------------------------
# Unit 3: stow actions and restow
# --------------------------------------------------------------------------


class ParseStowActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home

    def test_link_actions_are_resolved_and_warning_skipped(self) -> None:
        text = (
            "LINK: .config/app/conf => ../../.dotfiles/mypkg/.config/app/conf\n"
            "WARNING: in simulation mode so not modifying filesystem.\n"
        )
        actions = ss.parse_stow_actions(text, str(self.home))
        self.assertEqual(
            actions,
            [
                {
                    "action": "LINK",
                    "target": "~/.config/app/conf",
                    "source": "~/.dotfiles/mypkg/.config/app/conf",
                }
            ],
        )

    def test_non_link_action_is_target_only(self) -> None:
        actions = ss.parse_stow_actions("MKDIR: .config/app\n", str(self.home))
        self.assertEqual(actions, [{"action": "MKDIR", "target": "~/.config/app"}])


class RestowCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.repo = self.home / ".dotfiles"
        self.config = self.env.root / "config.json"
        write(self.repo / "mypkg" / ".config" / "app" / "conf", "hello\n")
        write(self.repo / "mypkg" / ".config" / "app" / "keep", "keep\n")
        # A real sibling forces per-file linking instead of folding the tree.
        write(self.home / ".config" / "app" / "sibling", "s\n")
        write_config(self.config, [{"path": str(self.repo), "target": str(self.home), "packages": "auto"}])

    def restow(self, *extra: str) -> dict:
        return ss.dispatch(
            ["restow", "--repo", str(self.repo), "--package", "mypkg", *extra],
            str(self.config),
        )

    def test_dry_run_reports_actions_and_touches_nothing(self) -> None:
        result = self.restow("--dry-run")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(
            result["actions"],
            [
                {"action": "LINK", "target": "~/.config/app/conf", "source": "~/.dotfiles/mypkg/.config/app/conf"},
                {"action": "LINK", "target": "~/.config/app/keep", "source": "~/.dotfiles/mypkg/.config/app/keep"},
            ],
        )
        self.assertFalse(os.path.islink(self.home / ".config" / "app" / "conf"))

    def test_real_restow_links_the_files(self) -> None:
        result = self.restow()
        self.assertTrue(result["ok"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(len(result["actions"]), 2)
        link = self.home / ".config" / "app" / "conf"
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.path.realpath(link), str(self.repo / "mypkg" / ".config" / "app" / "conf"))

    def test_conflict_refuses_without_mutating(self) -> None:
        os.remove(self.repo / "mypkg" / ".config" / "app" / "keep")
        write(self.home / ".config" / "app" / "conf", "real\n")
        result = self.restow()
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertIn("conflict", result["error"].lower())
        real = self.home / ".config" / "app" / "conf"
        self.assertFalse(os.path.islink(real))
        self.assertEqual(real.read_text(encoding="utf-8"), "real\n")

    def test_unknown_package_name_is_rejected(self) -> None:
        result = ss.dispatch(
            ["restow", "--repo", str(self.repo), "--package", "../evil"], str(self.config)
        )
        self.assertFalse(result["ok"])


# --------------------------------------------------------------------------
# Unit 3: adopt (README section 5.3)
# --------------------------------------------------------------------------


class AdoptCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.repo = self.home / ".dotfiles"
        self.config = self.env.root / "config.json"

    def _write_config(self, watch: list[str]) -> None:
        write_config(
            self.config,
            [{"path": str(self.repo), "target": str(self.home), "packages": "auto"}],
            watch=watch,
        )

    def _mypkg_with_sibling(self) -> None:
        write(self.repo / "mypkg" / "watch" / "existing", "e\n")

    def adopt(self, package: str, path: Path, *extra: str, rename=None) -> dict:
        argv = [
            "adopt",
            "--repo",
            str(self.repo),
            "--package",
            package,
            "--path",
            str(path),
            *extra,
        ]
        if rename is None:
            return ss.dispatch(argv, str(self.config))
        return ss.cmd_adopt(argv[1:], str(self.config), None, rename=rename)

    def test_dry_run_reports_and_touches_nothing(self) -> None:
        self._mypkg_with_sibling()
        write(self.home / "watch" / "keep", "k\n")
        target = self.home / "watch" / "new.conf"
        write(target, "content\n")
        self._write_config(["~/watch"])
        result = self.adopt("mypkg", target, "--dry-run")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["moved_to"], "~/.dotfiles/mypkg/watch/new.conf")
        self.assertTrue(target.is_file() and not target.is_symlink())
        self.assertFalse((self.repo / "mypkg" / "watch" / "new.conf").exists())

    def test_happy_path_moves_and_links(self) -> None:
        self._mypkg_with_sibling()
        write(self.home / "watch" / "keep", "k\n")
        target = self.home / "watch" / "new.conf"
        write(target, "content\n")
        self._write_config(["~/watch"])
        result = self.adopt("mypkg", target)
        self.assertTrue(result["ok"])
        self.assertNotIn("dry_run", result)
        self.assertEqual(result["moved_to"], "~/.dotfiles/mypkg/watch/new.conf")
        dest = self.repo / "mypkg" / "watch" / "new.conf"
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_text(encoding="utf-8"), "content\n")
        self.assertTrue(os.path.islink(target))
        self.assertEqual(os.path.realpath(target), str(dest))
        self.assertTrue(result["actions"])
        self.assertTrue(all(a["action"] == "LINK" for a in result["actions"]))
        self.assertIn(
            {"action": "LINK", "target": "~/watch/new.conf", "source": "~/.dotfiles/mypkg/watch/new.conf"},
            result["actions"],
        )

    def test_destination_exists_is_refused(self) -> None:
        self._mypkg_with_sibling()
        write(self.repo / "mypkg" / "watch" / "new.conf", "already\n")
        write(self.home / "watch" / "new.conf", "content\n")
        self._write_config(["~/watch"])
        result = self.adopt("mypkg", self.home / "watch" / "new.conf")
        self.assertFalse(result["ok"])
        self.assertIn("destination already exists", result["error"])

    def test_conflict_rolls_back(self) -> None:
        write(self.repo / "mypkg" / ".config" / "app" / "keep", "keep\n")
        write(self.home / ".config" / "app" / "keep", "real\n")  # conflict
        write(self.home / ".config" / "app" / "sibling", "s\n")  # anti-fold
        target = self.home / ".config" / "app" / "newfile"
        write(target, "original\n")
        self._write_config(["~/.config/app"])
        result = self.adopt("mypkg", target)
        self.assertFalse(result["ok"])
        self.assertIn("conflict", result["error"].lower())
        self.assertTrue(target.is_file() and not target.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
        self.assertFalse((self.repo / "mypkg" / ".config" / "app" / "newfile").exists())

    def test_exdev_falls_back_to_copy(self) -> None:
        self._mypkg_with_sibling()
        write(self.home / "watch" / "keep", "k\n")
        target = self.home / "watch" / "new.conf"
        write(target, "content\n")
        self._write_config(["~/watch"])

        def always_exdev(src: str, dst: str) -> None:
            raise OSError(errno.EXDEV, "cross-device link")

        result = self.adopt("mypkg", target, rename=always_exdev)
        self.assertTrue(result["ok"])
        dest = self.repo / "mypkg" / "watch" / "new.conf"
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_text(encoding="utf-8"), "content\n")
        self.assertTrue(os.path.islink(target))

    def test_path_outside_watch_area_is_refused(self) -> None:
        self._mypkg_with_sibling()
        target = self.home / "elsewhere" / "x.conf"
        write(target, "x\n")
        self._write_config(["~/watch"])
        result = self.adopt("mypkg", target)
        self.assertFalse(result["ok"])
        self.assertIn("watch", result["error"].lower())

    def test_path_outside_home_is_refused(self) -> None:
        self._mypkg_with_sibling()
        self._write_config(["~"])
        result = self.adopt("mypkg", Path("/etc/hosts"))
        self.assertFalse(result["ok"])

    def test_invalid_package_name_is_refused(self) -> None:
        self._mypkg_with_sibling()
        target = self.home / "watch" / "x.conf"
        write(target, "x\n")
        self._write_config(["~/watch"])
        result = self.adopt("../evil", target)
        self.assertFalse(result["ok"])


# --------------------------------------------------------------------------
# Unit 3: ignore / unignore
# --------------------------------------------------------------------------


class IgnoreCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.config = self.env.root / "config.json"
        write_config(self.config, [], watch=["~/.local/bin"], ignore=["~/.config/hypr"])

    def run_cmd(self, command: str, payload) -> dict:
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            return ss.dispatch([command], str(self.config))

    def raw(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_ignore_bare_string_adds_tilde_path(self) -> None:
        result = self.run_cmd("ignore", "~/.config/foo")
        self.assertTrue(result["ok"])
        self.assertEqual(result["ignore"], ["~/.config/hypr", "~/.config/foo"])
        self.assertEqual(self.raw()["ignore"], ["~/.config/hypr", "~/.config/foo"])

    def test_ignore_list_dedupes(self) -> None:
        result = self.run_cmd("ignore", ["~/.config/a", "~/.config/a", "~/.config/b"])
        self.assertEqual(result["ignore"], ["~/.config/hypr", "~/.config/a", "~/.config/b"])

    def test_ignore_normalizes_absolute_path_under_home(self) -> None:
        result = self.run_cmd("ignore", str(self.home / ".config" / "x"))
        self.assertEqual(result["ignore"], ["~/.config/hypr", "~/.config/x"])

    def test_ignore_preserves_other_config_keys(self) -> None:
        before = self.raw()
        self.run_cmd("ignore", "~/.config/foo")
        after = self.raw()
        for key in ("version", "repos", "watch", "fetch_minutes", "refresh_minutes", "notify_after_hours"):
            self.assertEqual(after[key], before[key], key)

    def test_unignore_removes_exact_match(self) -> None:
        result = self.run_cmd("unignore", "~/.config/hypr")
        self.assertTrue(result["ok"])
        self.assertEqual(result["ignore"], [])
        self.assertEqual(self.raw()["ignore"], [])

    def test_unignore_unknown_is_noop(self) -> None:
        result = self.run_cmd("unignore", "~/.config/absent")
        self.assertTrue(result["ok"])
        self.assertEqual(result["ignore"], ["~/.config/hypr"])


# --------------------------------------------------------------------------
# Unit 3: suggest-message (README section 5.4)
# --------------------------------------------------------------------------


class SuggestMessagePureTests(unittest.TestCase):
    def test_one_package_modified(self) -> None:
        paths = ["fish/.config/fish/config.fish"]
        statuses = {paths[0]: "modified"}
        self.assertEqual(
            ss.suggest_message(paths, statuses),
            "chore(fish): update config.fish",
        )

    def test_one_package_many_files(self) -> None:
        paths = [
            "fish/.config/fish/config.fish",
            "fish/.config/fish/a.fish",
            "fish/.config/fish/b.fish",
            "fish/.config/fish/c.fish",
            "fish/.config/fish/d.fish",
        ]
        statuses = {p: "modified" for p in paths}
        self.assertEqual(
            ss.suggest_message(paths, statuses),
            "chore(fish): update config.fish, a.fish, b.fish, +2 more",
        )

    def test_several_packages(self) -> None:
        paths = ["fish/.config/fish/config.fish", "nvim/.config/nvim/init.lua"]
        statuses = {p: "modified" for p in paths}
        self.assertEqual(ss.suggest_message(paths, statuses), "chore: update fish, nvim")

    def test_several_packages_more_than_two(self) -> None:
        paths = ["a/x", "b/y", "c/z", "d/w"]
        statuses = {p: "modified" for p in paths}
        self.assertEqual(ss.suggest_message(paths, statuses), "chore: update a, b, +2 more")

    def test_only_additions(self) -> None:
        paths = ["fish/.config/fish/new.fish"]
        statuses = {paths[0]: "untracked"}
        self.assertEqual(ss.suggest_message(paths, statuses), "feat(fish): add new.fish")

    def test_added_status_is_also_an_addition(self) -> None:
        paths = ["fish/.config/fish/new.fish"]
        statuses = {paths[0]: "added"}
        self.assertEqual(ss.suggest_message(paths, statuses), "feat(fish): add new.fish")


class SuggestMessageCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"
        self.repo = self.env.home / ".dotfiles"
        init_repo(self.repo)
        write(self.repo / "fish" / ".config" / "fish" / "config.fish", "old\n")
        commit_all(self.repo, "c1")
        write_config(self.config, [{"path": str(self.repo), "target": "~", "packages": "auto"}])

    def suggest(self, payload) -> dict:
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            return ss.dispatch(["suggest-message", "--repo", str(self.repo)], str(self.config))

    def test_modified_file_message(self) -> None:
        write(self.repo / "fish" / ".config" / "fish" / "config.fish", "new\n")
        result = self.suggest(["fish/.config/fish/config.fish"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "chore(fish): update config.fish")

    def test_untracked_file_is_feat(self) -> None:
        write(self.repo / "fish" / ".config" / "fish" / "new.fish", "n\n")
        result = self.suggest(["fish/.config/fish/new.fish"])
        self.assertEqual(result["message"], "feat(fish): add new.fish")

    def test_dict_payload_and_several_packages(self) -> None:
        write(self.repo / "nvim" / ".config" / "nvim" / "init.lua", "l\n")
        commit_all(self.repo, "add nvim")
        write(self.repo / "fish" / ".config" / "fish" / "config.fish", "new\n")
        write(self.repo / "nvim" / ".config" / "nvim" / "init.lua", "changed\n")
        result = self.suggest(
            {"paths": ["fish/.config/fish/config.fish", "nvim/.config/nvim/init.lua"]}
        )
        self.assertEqual(result["message"], "chore: update fish, nvim")

    def test_tilde_path_is_accepted(self) -> None:
        write(self.repo / "fish" / ".config" / "fish" / "config.fish", "new\n")
        result = self.suggest(["~/.dotfiles/fish/.config/fish/config.fish"])
        self.assertEqual(result["message"], "chore(fish): update config.fish")


# --------------------------------------------------------------------------
# Unit 3: status --short (README section 7)
# --------------------------------------------------------------------------


class StatusShortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        os.environ.pop("STOW_SYNC_STATE_DIR", None)
        self.addCleanup(lambda: os.environ.pop("STOW_SYNC_STATE_DIR", None))
        self.home = self.env.home
        self.config = self.env.root / "config.json"
        self.state_dir = self.env.root / "state"

    def short(self) -> str:
        return ss.cmd_status_short(["--short"], str(self.config), str(self.state_dir))

    def _repo_with_remote(self, name: str) -> Path:
        repo = self.home / name
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        bare = self.env.root / f"{name}.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
            env=git_test_env(),
        )
        git(repo, "remote", "add", "origin", str(bare))
        git(repo, "push", "-u", "-q", "origin", "main")
        return repo

    def test_clean_repo_is_empty(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        self.assertEqual(self.short(), "")

    def test_changed_and_untracked_segments(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write(repo / "a.txt", "changed\n")
        write(repo / "new.txt", "n\n")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        self.assertEqual(self.short(), "dotfiles: 1 changed, 1 untracked")

    def test_unpushed_segment(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write(repo / "b.txt", "b\n")
        commit_all(repo, "c2")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        self.assertEqual(self.short(), "dotfiles: 1 unpushed")

    def test_behind_segment(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        bare = self.env.root / ".dotfiles.git"
        other = self.env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env())
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2")
        git(other, "push", "-q", "origin", "main")
        git(repo, "fetch", "-q", "origin")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        self.assertEqual(self.short(), "dotfiles: 1 behind")

    def test_multiple_repos_are_joined(self) -> None:
        one = self._repo_with_remote(".dotfiles")
        two = self._repo_with_remote("wallpapers")
        write(one / "a.txt", "changed\n")
        write(two / "a.txt", "changed\n")
        write_config(
            self.config,
            [
                {"path": str(one), "target": "~", "packages": "auto"},
                {"path": str(two), "target": "~", "packages": "auto"},
            ],
        )
        self.assertEqual(self.short(), "dotfiles: 1 changed · wallpapers: 1 changed")

    def test_first_run_creates_baseline_and_prints_nothing(self) -> None:
        # §5.3b: --short shares the baseline logic. A fresh state dir creates
        # baseline.json from the current candidates, so pre-existing files are
        # known and never reported as "new config".
        write(self.home / ".local" / "bin" / "tool", "x\n")
        write_config(self.config, [], watch=["~/.local/bin"])
        self.assertEqual(self.short(), "")
        self.assertTrue((self.state_dir / "baseline.json").exists())

    def test_known_candidate_does_not_add_segment(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        write_config(self.config, [], watch=["~/.local/bin"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "baseline.json").write_text(
            json.dumps({"version": 1, "created": "x", "paths": ["~/.local/bin/tool"]}),
            encoding="utf-8",
        )
        self.assertEqual(self.short(), "")

    def test_new_file_after_baseline_shows_new_config(self) -> None:
        write(self.home / ".local" / "bin" / "tool", "x\n")
        write_config(self.config, [], watch=["~/.local/bin"])
        self.short()  # first run creates the baseline
        write(self.home / ".local" / "bin" / "another", "y\n")
        self.assertEqual(self.short(), "1 new config")

    def test_skips_stow_health(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write(repo / "mypkg" / ".config" / "app" / "conf", "x\n")
        commit_all(repo, "add pkg")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        with patch.object(ss, "package_health", side_effect=AssertionError("stow health must be skipped")):
            self.assertEqual(self.short(), "dotfiles: 1 unpushed")

    def test_main_prints_plain_line(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write(repo / "a.txt", "changed\n")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = ss.main(["--config", str(self.config), "--state-dir", str(self.state_dir), "status", "--short"])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "dotfiles: 1 changed\n")

    def test_main_prints_nothing_when_clean(self) -> None:
        repo = self._repo_with_remote(".dotfiles")
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = ss.main(["--config", str(self.config), "--state-dir", str(self.state_dir), "status", "--short"])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "")


# --------------------------------------------------------------------------
# Unit 4d Task 1: repo info fields (README section 8, Unit 4d)
# --------------------------------------------------------------------------


ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class SanitizeUrlTests(unittest.TestCase):
    def test_strips_user_and_password(self) -> None:
        self.assertEqual(
            ss.sanitize_url("https://user:secret@github.com/u/r.git"),
            "https://github.com/u/r.git",
        )

    def test_strips_token_only_userinfo(self) -> None:
        self.assertEqual(
            ss.sanitize_url("https://ghp_secretToken123@github.com/u/r.git"),
            "https://github.com/u/r.git",
        )

    def test_keeps_conventional_ssh_username(self) -> None:
        # ``git@`` is the standard SSH user, not a credential.
        self.assertEqual(
            ss.sanitize_url("ssh://git@github.com/u/r.git"),
            "ssh://git@github.com/u/r.git",
        )
        self.assertEqual(
            ss.sanitize_url("git@github.com:u/r.git"),
            "git@github.com:u/r.git",
        )

    def test_plain_and_empty_values_pass_through(self) -> None:
        self.assertEqual(ss.sanitize_url("https://github.com/u/r.git"), "https://github.com/u/r.git")
        self.assertEqual(ss.sanitize_url(""), "")
        self.assertEqual(ss.sanitize_url(None), "")


class StatusInfoFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.home = self.env.home
        self.config = self.env.root / "config.json"
        self.state_dir = self.env.root / "state"

    def status(self, *extra: str) -> dict:
        return ss.dispatch(["status", *extra], str(self.config), str(self.state_dir))

    def _use(self, repo: Path, packages="auto") -> None:
        write_config(
            self.config,
            [{"path": str(repo), "target": str(self.home), "packages": packages}],
        )

    def test_remote_head_subject_and_time(self) -> None:
        bare, repo = make_bare_and_clone(self.env.root)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1 first commit")
        git(repo, "push", "-q", "origin", "main")
        self._use(repo)
        entry = self.status()["repos"][0]
        self.assertEqual(entry["remote_url"], str(bare))
        self.assertEqual(entry["head"], git(repo, "rev-parse", "--short", "HEAD").stdout.strip())
        self.assertEqual(entry["head_subject"], "c1 first commit")
        self.assertIsNotNone(entry["head_time"])
        self.assertRegex(entry["head_time"], ISO_RE)

    def test_remote_url_strips_embedded_credentials(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        git(repo, "remote", "add", "origin", "https://user:secret@example.com/x.git")
        self._use(repo)
        entry = self.status()["repos"][0]
        self.assertEqual(entry["remote_url"], "https://example.com/x.git")
        self.assertNotIn("secret", entry["remote_url"])

    def test_no_origin_has_empty_remote_url(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        self._use(repo)
        self.assertEqual(self.status()["repos"][0]["remote_url"], "")

    def test_missing_repo_info_defaults(self) -> None:
        self._use(self.env.root / "nope")
        entry = self.status()["repos"][0]
        self.assertFalse(entry["exists"])
        self.assertEqual(entry["remote_url"], "")
        self.assertEqual(entry["head"], "")
        self.assertEqual(entry["head_subject"], "")
        self.assertIsNone(entry["head_time"])
        self.assertEqual(entry["stowed_packages"], 0)
        self.assertEqual(entry["stowed_files"], 0)
        self.assertIsNone(entry["last_publish"])
        self.assertEqual(entry["incoming_commits"], [])

    def test_stowed_packages_and_files_count_only_healthy(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "fish" / ".config" / "fish" / "config.fish", "set -gx X 1\n")
        write(repo / "fish" / ".config" / "fish" / "conf.d" / "abbr.fish", "abbr -a g git\n")
        write(repo / "extra" / ".config" / "extra" / "conf", "x\n")
        commit_all(repo, "c1")
        stow_apply(repo, self.home, "fish")
        self._use(repo)
        entry = self.status()["repos"][0]
        health = {p["name"]: p["health"] for p in entry["packages"]}
        self.assertEqual(health, {"fish": "ok", "extra": "pending"})
        self.assertEqual(entry["stowed_packages"], 1)
        self.assertEqual(entry["stowed_files"], 2)

    def test_last_publish_reads_state_dir_file(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        when = "2026-10-09T12:34:56-05:00"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "publish.json").write_text(
            json.dumps({str(repo): when}), encoding="utf-8"
        )
        self._use(repo)
        self.assertEqual(self.status()["repos"][0]["last_publish"], when)

    def test_last_publish_null_without_file(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        self._use(repo)
        self.assertIsNone(self.status()["repos"][0]["last_publish"])

    def test_incoming_commits_lists_remote_commits_when_behind(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        other = self.env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], check=True, capture_output=True, env=git_test_env())
        git(other, "config", "user.name", "Test")
        git(other, "config", "user.email", "test@example.com")
        write(other / "b.txt", "b\n")
        commit_all(other, "c2 from remote")
        git(other, "push", "-q", "origin", "main")
        git(work, "fetch", "-q", "origin")
        self._use(work)
        entry = self.status()["repos"][0]
        self.assertEqual(entry["behind"], 1)
        self.assertEqual([c["subject"] for c in entry["incoming_commits"]], ["c2 from remote"])
        self.assertTrue(entry["incoming_commits"][0]["hash"])

    def test_status_info_fields_do_not_mutate_repo(self) -> None:
        repo = self.env.root / "repo"
        init_repo(repo)
        write(repo / "a.txt", "a\n")
        commit_all(repo, "c1")
        before = git(repo, "status", "--porcelain").stdout
        before_head = git(repo, "rev-parse", "HEAD").stdout
        self._use(repo)
        self.status()
        self.assertEqual(git(repo, "status", "--porcelain").stdout, before)
        self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)


class PublishStampTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.config = self.env.root / "config.json"
        self.state_dir = self.env.root / "state"
        self.publish_file = self.state_dir / "publish.json"

    def _use(self, repo: Path) -> None:
        write_config(self.config, [{"path": str(repo), "target": "~", "packages": "auto"}])

    def push(self, repo: Path) -> dict:
        return ss.dispatch(["push", "--repo", str(repo)], str(self.config), str(self.state_dir))

    def test_successful_push_records_publish_time(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "b.txt", "b\n")
        commit_all(work, "c2")
        self._use(work)
        result = self.push(work)
        self.assertTrue(result.get("pushed"))
        data = json.loads(self.publish_file.read_text(encoding="utf-8"))
        self.assertIn(str(work), data)
        self.assertRegex(data[str(work)], ISO_RE)
        self.assertEqual(self.publish_file.stat().st_mode & 0o777, 0o600)

    def test_failed_push_does_not_record(self) -> None:
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
        self._use(work)
        result = self.push(work)
        self.assertIn("push_error", result)
        recorded = {}
        if self.publish_file.exists():
            recorded = json.loads(self.publish_file.read_text(encoding="utf-8"))
        self.assertNotIn(str(work), recorded)

    def test_successful_push_refreshes_existing_stamp(self) -> None:
        bare, work = make_bare_and_clone(self.env.root)
        write(work / "a.txt", "a\n")
        commit_all(work, "c1")
        git(work, "push", "-q", "origin", "main")
        write(work / "b.txt", "b\n")
        commit_all(work, "c2")
        self._use(work)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.publish_file.write_text(
            json.dumps({str(work): "2000-01-01T00:00:00+00:00"}), encoding="utf-8"
        )
        self.push(work)
        data = json.loads(self.publish_file.read_text(encoding="utf-8"))
        self.assertNotEqual(data[str(work)], "2000-01-01T00:00:00+00:00")


# --------------------------------------------------------------------------
# Unit 5: notify_after_hours desktop notifications (README section 4/8)
# --------------------------------------------------------------------------


def notify_repo(
    path: str = "~/.dotfiles",
    changes: list | None = None,
    untracked: list | None = None,
    ahead: int = 0,
    behind: int = 0,
    packages: list | None = None,
) -> dict:
    return {
        "path": path,
        "changes": changes if changes is not None else [],
        "untracked": untracked if untracked is not None else [],
        "ahead": ahead,
        "behind": behind,
        "packages": packages if packages is not None else [],
    }


class NotifyDecisionPureTests(unittest.TestCase):
    NOW = "2026-10-09T12:00:00+00:00"

    def decide(self, repos, prior, after_hours=6):
        return ss.notify_decision(repos, prior, self.NOW, after_hours)

    def test_clean_repo_never_sends_and_clears_state(self) -> None:
        result = self.decide(
            [notify_repo()],
            {"~/.dotfiles": {"first_pending": "2026-10-01T00:00:00+00:00", "last_notified": None}},
        )
        self.assertEqual(result["sends"], [])
        self.assertEqual(result["state"], {})

    def test_first_pending_sets_timestamp_without_sending(self) -> None:
        result = self.decide([notify_repo(changes=[{"path": "a"}])], {})
        self.assertEqual(result["sends"], [])
        entry = result["state"]["~/.dotfiles"]
        self.assertEqual(entry["first_pending"], self.NOW)
        self.assertIsNone(entry["last_notified"])

    def test_pending_for_threshold_sends_and_stamps(self) -> None:
        prior = {
            "~/.dotfiles": {
                "first_pending": "2026-10-09T02:00:00+00:00",
                "last_notified": None,
            }
        }
        result = self.decide([notify_repo(untracked=[{"path": "b"}])], prior)
        self.assertEqual(result["sends"], ["~/.dotfiles"])
        entry = result["state"]["~/.dotfiles"]
        self.assertEqual(entry["last_notified"], self.NOW)
        self.assertEqual(entry["first_pending"], "2026-10-09T02:00:00+00:00")

    def test_below_threshold_does_not_send(self) -> None:
        prior = {
            "~/.dotfiles": {
                "first_pending": "2026-10-09T11:00:00+00:00",
                "last_notified": None,
            }
        }
        result = self.decide([notify_repo(untracked=[{"path": "b"}])], prior)
        self.assertEqual(result["sends"], [])
        self.assertIsNone(result["state"]["~/.dotfiles"]["last_notified"])

    def test_already_notified_today_does_not_send(self) -> None:
        prior = {
            "~/.dotfiles": {
                "first_pending": "2026-10-09T02:00:00+00:00",
                "last_notified": "2026-10-09T09:00:00+00:00",
            }
        }
        result = self.decide([notify_repo(ahead=2)], prior)
        self.assertEqual(result["sends"], [])
        self.assertEqual(result["state"]["~/.dotfiles"]["last_notified"], "2026-10-09T09:00:00+00:00")

    def test_notified_previous_day_sends_again(self) -> None:
        prior = {
            "~/.dotfiles": {
                "first_pending": "2026-10-08T00:00:00+00:00",
                "last_notified": "2026-10-08T09:00:00+00:00",
            }
        }
        result = self.decide([notify_repo(behind=1)], prior)
        self.assertEqual(result["sends"], ["~/.dotfiles"])

    def test_after_hours_zero_is_off(self) -> None:
        prior = {
            "~/.dotfiles": {
                "first_pending": "2026-10-01T00:00:00+00:00",
                "last_notified": None,
            }
        }
        result = self.decide([notify_repo(changes=[{"path": "a"}])], prior, after_hours=0)
        self.assertEqual(result["sends"], [])

    def test_ahead_behind_and_unhealthy_package_are_pending(self) -> None:
        self.assertTrue(ss.repo_pending(notify_repo(ahead=1)))
        self.assertTrue(ss.repo_pending(notify_repo(behind=1)))
        self.assertTrue(
            ss.repo_pending(
                notify_repo(packages=[{"name": "p", "health": "pending"}])
            )
        )
        self.assertFalse(ss.repo_pending(notify_repo()))

    def test_counts_attention_items(self) -> None:
        repo = notify_repo(
            changes=[{"path": "a"}, {"path": "b"}],
            untracked=[{"path": "c"}],
            ahead=2,
            behind=1,
            packages=[
                {"name": "p", "health": "conflicts", "pending_links": [], "conflicts": [{"x": 1}], "dangling": []},
            ],
        )
        self.assertEqual(ss.repo_pending_count(repo), 6)

    def test_sends_once_per_repo_in_order(self) -> None:
        prior = {
            "~/.dotfiles": {"first_pending": "2026-10-01T00:00:00+00:00", "last_notified": None},
            "~/wallpapers": {"first_pending": "2026-10-01T00:00:00+00:00", "last_notified": None},
        }
        repos = [notify_repo("~/.dotfiles", ahead=1), notify_repo("~/wallpapers", behind=1)]
        result = self.decide(repos, prior)
        self.assertEqual(result["sends"], ["~/.dotfiles", "~/wallpapers"])

    def test_malformed_first_pending_restarts_clock(self) -> None:
        prior = {"~/.dotfiles": {"first_pending": "not-a-date", "last_notified": None}}
        result = self.decide([notify_repo(ahead=1)], prior)
        self.assertEqual(result["sends"], [])
        self.assertEqual(result["state"]["~/.dotfiles"]["first_pending"], self.NOW)

    def test_naive_timestamps_do_not_crash(self) -> None:
        prior = {"~/.dotfiles": {"first_pending": "2026-10-09T02:00:00", "last_notified": None}}
        result = ss.notify_decision(
            [notify_repo(ahead=1)], prior, "2026-10-09T12:00:00", 6
        )
        self.assertEqual(result["sends"], ["~/.dotfiles"])


class NotifyWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempHome()
        self.addCleanup(self.env.close)
        self._patch = patch.dict(os.environ, {"HOME": str(self.env.home)})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        os.environ.pop("STOW_SYNC_STATE_DIR", None)
        self.addCleanup(lambda: os.environ.pop("STOW_SYNC_STATE_DIR", None))
        self.config = self.env.root / "config.json"
        self.state_dir = self.env.root / "state"
        self.notify_file = self.state_dir / "notify.json"
        self.repo = self.env.root / "repo"
        init_repo(self.repo)
        write(self.repo / "a.txt", "a\n")
        commit_all(self.repo, "c1")
        write(self.repo / "new.txt", "n\n")  # untracked -> pending
        self.cfg = {
            "version": 1,
            "repos": [{"path": str(self.repo), "target": "~", "packages": "auto"}],
            "watch": [],
            "ignore": [],
            "fetch_minutes": 15,
            "refresh_minutes": 5,
            "notify_after_hours": 1,
        }

    def write_config(self, after_hours: int = 1) -> None:
        self.cfg["notify_after_hours"] = after_hours
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")

    def seed_pending_since(self, when: str = "2000-01-01T00:00:00+00:00") -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.notify_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "repos": {
                        str(self.repo): {"first_pending": when, "last_notified": None}
                    },
                }
            ),
            encoding="utf-8",
        )

    def status(self) -> dict:
        return ss.dispatch(["status"], str(self.config), str(self.state_dir))

    def test_status_writes_notify_state_and_spawns_detached(self) -> None:
        self.write_config(1)
        self.seed_pending_since()
        calls: list[tuple] = []
        with patch.object(ss, "spawn_notify", side_effect=lambda *a: calls.append(a)):
            result = self.status()
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], str(self.repo))
        self.assertGreaterEqual(calls[0][1], 1)
        data = json.loads(self.notify_file.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        entry = data["repos"][str(self.repo)]
        self.assertRegex(entry["last_notified"], ISO_RE)
        self.assertEqual(self.notify_file.stat().st_mode & 0o777, 0o600)

    def test_status_off_never_spawns(self) -> None:
        self.write_config(0)
        self.seed_pending_since()
        calls: list[tuple] = []
        with patch.object(ss, "spawn_notify", side_effect=lambda *a: calls.append(a)):
            result = self.status()
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [])
        self.assertEqual(result.get("notifications_sent"), [])

    def test_missing_notify_send_is_swallowed(self) -> None:
        self.write_config(1)
        self.seed_pending_since()
        real_popen = subprocess.Popen

        def fake_popen(argv, *args, **kwargs):
            if isinstance(argv, (list, tuple)) and argv and argv[0] == "notify-send":
                raise FileNotFoundError("notify-send")
            return real_popen(argv, *args, **kwargs)

        with patch.object(ss.subprocess, "Popen", side_effect=fake_popen):
            result = self.status()
        self.assertTrue(result["ok"])
        self.assertEqual([str(self.repo)], result.get("notifications_sent"))

    def test_status_short_does_not_touch_notify_state(self) -> None:
        self.write_config(1)
        self.seed_pending_since()
        before = self.notify_file.read_text(encoding="utf-8")
        with patch("sys.stdout", new_callable=io.StringIO):
            ss.main(["status", "--short", "--config", str(self.config), "--state-dir", str(self.state_dir)])
        self.assertEqual(self.notify_file.read_text(encoding="utf-8"), before)


# --------------------------------------------------------------------------
# Unit 8a: "Set up this machine" backend (README section 8a)
# --------------------------------------------------------------------------

SETUP_EXAMPLE = ROOT / "docs" / "setup-recipe.example.json"


def valid_setup_recipe() -> dict:
    """A fresh, valid copy of the documented example recipe."""
    return json.loads(SETUP_EXAMPLE.read_text(encoding="utf-8"))


# A scriptable ``gh`` stub for the candidate-detection tests (README 11c.1):
# routes are a list of {"match": [tokens], "exit": N, "stdout"/"stderr": ...,
# "sleep": seconds} and the first route whose tokens are all substrings of the
# joined argv wins. No test ever reaches the real GitHub API.
_GH_ROUTER = '''#!/usr/bin/env python3
import json
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "gh_routes.json"), "r", encoding="utf-8") as handle:
    spec = json.load(handle)
joined = " ".join(sys.argv[1:])
for route in spec.get("routes", []):
    if all(token in joined for token in route.get("match", [])):
        delay = float(route.get("sleep", 0.0))
        if delay:
            time.sleep(delay)
        if route.get("stdout"):
            sys.stdout.write(route["stdout"])
        if route.get("stderr"):
            sys.stderr.write(route["stderr"])
        sys.exit(int(route.get("exit", 0)))
sys.stderr.write("gh: no fake route for: " + joined + "\\n")
sys.exit(1)
'''


def gh_missing_patch():
    """Patch ``shutil.which`` so only ``gh`` looks absent (README 11c.3)."""
    real = ss.shutil.which

    def which(cmd, *args, **kwargs):
        return None if cmd == "gh" else real(cmd, *args, **kwargs)

    return patch.object(ss.shutil, "which", side_effect=which)


class FreshOmarchyHome:
    """Temp HOME that simulates a fresh Omarchy install plus two remotes.

    Seeds the Omarchy default files the recipe packages collide with, two bare
    remotes (dotfiles with a recipe and packages, and wallpapers) and a third
    bare with no recipe. Every setup test runs inside this HOME; a fake
    ``systemctl`` earlier on ``PATH`` keeps service detection hermetic.
    """

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="stow-sync-setup-")
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.remotes = self.root / "remotes"
        self.remotes.mkdir()
        self.state = self.root / "state"
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self.systemctl_log = self.root / "systemctl.log"
        self.real_stow = shutil.which("stow")
        self.fish_default = "fish default\n"
        self.ghostty_default = "ghostty default\n"
        self.nvim_default = "nvim default\n"
        self.config_default = '{\n  "version": 1\n}\n'
        self._install_fake_systemctl()
        self._seed_defaults()
        self.dotfiles_bare = self.remotes / "dotfiles.git"
        self.wallpapers_bare = self.remotes / "wallpapers.git"
        self.plain_bare = self.remotes / "plain.git"
        self._seed_dotfiles_remote()
        self._seed_wallpapers_remote()
        self._seed_plain_remote()

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "FreshOmarchyHome":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _install_fake_systemctl(self) -> None:
        script = self.fakebin / "systemctl"
        write(
            script,
            "#!/bin/sh\n"
            f'echo "$@" >> "{self.systemctl_log}"\n'
            'case "$*" in\n'
            "  *is-enabled*) echo disabled ;;\n"
            "esac\n"
            'case "$*" in\n'
            "  *disable*)\n"
            '    for u in "$@"; do\n'
            '      case "$u" in\n'
            '        -*|"") ;;\n'
            '        *.*) rm -f "$HOME"/.config/systemd/user/*.wants/"$u" 2>/dev/null ;;\n'
            "      esac\n"
            "    done\n"
            "    ;;\n"
            "esac\n"
            "exit 0\n",
        )
        os.chmod(script, 0o755)

    def install_fake_gh(self, exit_code: int = 0) -> Path:
        """Install a ``gh`` on the fake PATH that always exits ``exit_code``."""
        script = self.fakebin / "gh"
        write(script, "#!/bin/sh\n" + f"exit {exit_code}\n")
        os.chmod(script, 0o755)
        return script

    def install_fake_gh_output(self, output: str, exit_code: int = 0) -> Path:
        """Install a ``gh`` that prints ``output`` (via a quoted heredoc)."""
        script = self.fakebin / "gh"
        write(script, "#!/bin/sh\ncat <<'STOW_SYNC_GH_EOF'\n" + output + "\nSTOW_SYNC_GH_EOF\nexit " + str(exit_code) + "\n")
        os.chmod(script, 0o755)
        return script

    def install_fake_gh_routes(self, routes: list[dict]) -> Path:
        """Install a scriptable ``gh`` stub for the candidate-detection tests."""
        script = self.fakebin / "gh"
        write(script, _GH_ROUTER)
        os.chmod(script, 0o755)
        (self.fakebin / "gh_routes.json").write_text(
            json.dumps({"routes": routes}), encoding="utf-8"
        )
        return script

    def install_fake_stow_wrapper(self, log: Path) -> Path:
        """Front ``stow`` with a wrapper that logs its argv, then execs it."""
        script = self.fakebin / "stow"
        write(
            script,
            "#!/bin/sh\n" f'echo "stow $@" >> "{log}"\n' f'exec "{self.real_stow}" "$@"\n',
        )
        os.chmod(script, 0o755)
        return script

    def install_fake_slow_git(self, sleep: float = 0.15) -> Path:
        """A ``git`` that emits clone progress with delays, then creates the dest."""
        script = self.fakebin / "git"
        write(
            script,
            "#!/bin/sh\n"
            'case "$*" in\n'
            "  *clone*)\n"
            '    for arg in "$@"; do dest="$arg"; done\n'
            f"    printf 'Receiving objects:  10%% (10/100), 1.00 MiB | 1.00 MiB/s\\r' >&2; sleep {sleep}\n"
            f"    printf 'Receiving objects:  55%% (55/100), 5.00 MiB | 5.00 MiB/s\\r' >&2; sleep {sleep}\n"
            "    printf 'Receiving objects: 100%% (100/100), 10.00 MiB | 5.00 MiB/s, done.\\n' >&2\n"
            "    mkdir -p \"$dest\"; printf 'x\\n' > \"$dest/README.md\"; exit 0 ;;\n"
            "esac\n"
            "exit 0\n",
        )
        os.chmod(script, 0o755)
        return script

    def install_fake_slow_stow(self, sleep: float = 0.12) -> Path:
        """Front ``stow`` with a wrapper that sleeps, then execs the real stow."""
        script = self.fakebin / "stow"
        write(script, "#!/bin/sh\n" f"sleep {sleep}\n" f'exec "{self.real_stow}" "$@"\n')
        os.chmod(script, 0o755)
        return script

    def _seed_defaults(self) -> None:
        home = self.home
        write(home / ".config" / "fish" / "config.fish", self.fish_default)
        write(home / ".config" / "ghostty" / "config", self.ghostty_default)
        write(home / ".config" / "nvim" / "init.lua", self.nvim_default)
        write(
            home / ".config" / "omarchy" / "backgrounds" / "everforest" / "existing.png",
            "existing\n",
        )
        write(home / ".config" / "stow-sync" / "config.json", self.config_default)

    def _init_bare(self, bare: Path) -> None:
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(bare)],
            check=True,
            capture_output=True,
            env=git_test_env(),
        )

    def _seed_dotfiles_remote(self) -> None:
        self._init_bare(self.dotfiles_bare)
        work = self.root / "seed-dotfiles"
        init_repo(work)
        recipe = {
            "version": 1,
            "repos": [
                {
                    "path": "~/wallpapers",
                    "url": str(self.wallpapers_bare),
                    "packages": ["walls"],
                    "order": 1,
                    "private": True,
                },
                {
                    "path": "~/.dotfiles",
                    "url": str(self.dotfiles_bare),
                    "packages": "auto",
                    "order": 2,
                },
            ],
            "skip_packages": ["odd"],
            "services": ["ai-tools-check.timer"],
            "requires": ["git", "stow"],
            "post": [
                {
                    "id": "hello",
                    "label": "Say hello",
                    "argv": ["~/.local/bin/hello"],
                    "default": True,
                    "timeout_s": 30,
                },
                {
                    "id": "slow",
                    "label": "Sleep",
                    "argv": ["~/.local/bin/slow"],
                    "default": False,
                    "timeout_s": 1,
                },
                {
                    "id": "needy",
                    "label": "Needs a tool",
                    "argv": ["~/.local/bin/needy"],
                    "default": False,
                    "timeout_s": 30,
                    "needs": ["stow-sync-missing-tool"],
                },
            ],
            "notes": ["note one", "note two"],
        }
        write(work / ".stow-sync" / "setup.json", json.dumps(recipe, indent=2))
        write(work / "fish" / ".config" / "fish" / "config.fish", self.fish_default)
        write(work / "ghostty" / ".config" / "ghostty" / "config", "repo ghostty\n")
        write(work / "nvim" / ".config" / "nvim" / "init.lua", "repo nvim\n")
        write(
            work / "omarchy" / ".config" / "omarchy" / "backgrounds" / "everforest" / "wall.png",
            "wall\n",
        )
        write(work / "app" / ".config" / "app" / "conf", "app repo\n")
        write(
            work / "stow-sync" / ".config" / "stow-sync" / "config.json",
            '{"version": 1, "repos": []}\n',
        )
        write(work / "odd" / ".stow-local-ignore", ".*\n")
        write(work / "odd" / "junk", "junk\n")
        commit_all(work, "seed")
        git(work, "remote", "add", "origin", str(self.dotfiles_bare))
        git(work, "push", "-q", "origin", "main")

    def _seed_wallpapers_remote(self) -> None:
        self._init_bare(self.wallpapers_bare)
        work = self.root / "seed-wallpapers"
        init_repo(work)
        write(work / "walls" / ".config" / "walls" / "wall.png", "wall\n")
        commit_all(work, "seed")
        git(work, "remote", "add", "origin", str(self.wallpapers_bare))
        git(work, "push", "-q", "origin", "main")

    def _seed_plain_remote(self) -> None:
        self._init_bare(self.plain_bare)
        work = self.root / "seed-plain"
        init_repo(work)
        write(work / "README.md", "plain\n")
        commit_all(work, "seed")
        git(work, "remote", "add", "origin", str(self.plain_bare))
        git(work, "push", "-q", "origin", "main")

    def clone_dotfiles(self) -> Path:
        dest = self.home / ".dotfiles"
        subprocess.run(
            ["git", "clone", str(self.dotfiles_bare), str(dest)],
            check=True,
            capture_output=True,
            env=git_test_env(),
        )
        return dest

    def install_script(self, name: str, body: str) -> Path:
        path = self.home / ".local" / "bin" / name
        write(path, body)
        os.chmod(path, 0o755)
        return path


class SetupTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.env = FreshOmarchyHome()
        self.addCleanup(self.env.close)
        os.environ.pop("STOW_SYNC_STATE_DIR", None)
        self.addCleanup(lambda: os.environ.pop("STOW_SYNC_STATE_DIR", None))
        self._env_patch = patch.dict(
            os.environ,
            {
                "HOME": str(self.env.home),
                "PATH": str(self.env.fakebin) + os.pathsep + os.environ.get("PATH", ""),
            },
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.home = self.env.home
        self.state = self.env.state
        self.dotfiles = self.home / ".dotfiles"

    def plan(self, recipe: Path | None = None) -> dict:
        args = ["setup-plan"]
        if recipe is not None:
            args += ["--recipe", str(recipe)]
        return ss.dispatch(args, None, str(self.state))

    def apply(self, token: str, extra: list[str] | None = None) -> dict:
        args = ["setup-apply", "--token", token]
        if extra:
            args += extra
        return ss.dispatch(args, None, str(self.state))

    def plan_and_apply(self, extra: list[str] | None = None) -> dict:
        plan = self.plan()
        self.assertTrue(plan["ok"], plan)
        return self.apply(plan["token"], extra)

    def connect(self) -> dict:
        """Connect (clone dotfiles), then clone every other recipe repo.

        Mirrors the wizard: one request per repo so each clone has its own
        timeout (README 10a.2).
        """
        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertTrue(result["ok"], result)
        for entry in result["repos"]:
            clone = ss.dispatch(["setup-clone", "--path", entry["path"]], None, str(self.state))
            self.assertTrue(clone["ok"], clone)
            self.assertIn(clone["state"], ("cloned", "ready"), clone)
        return result

    def link_entry(self, plan: dict, package: str) -> dict:
        for entry in plan["plan"]["link"]:
            if entry["package"] == package:
                return entry
        raise AssertionError("no link entry for package " + package)


# --------------------------------------------------------------------------
# Recipe validation
# --------------------------------------------------------------------------


class SetupRecipeValidationTests(SetupTestBase):
    def test_example_recipe_is_valid(self) -> None:
        recipe = valid_setup_recipe()
        result = ss.validate_setup_recipe(recipe)
        self.assertEqual(result["version"], 1)
        self.assertEqual(len(result["repos"]), 2)
        self.assertEqual(result["repos"][0]["path"], "~/wallpapers")
        self.assertTrue(result["repos"][0]["private"])
        self.assertEqual(result["skip_packages"], ["odd", "zen"])
        self.assertEqual(result["post"][0]["timeout_s"], 900)
        self.assertFalse(result["post"][1]["default"])

    def _invalid(self, mutate) -> str:
        recipe = copy.deepcopy(valid_setup_recipe())
        mutate(recipe)
        with self.assertRaises(ss.CommandError) as ctx:
            ss.validate_setup_recipe(recipe)
        return str(ctx.exception)

    def test_version_must_be_one(self) -> None:
        self.assertIn("version must be 1", self._invalid(lambda r: r.update(version=2)))

    def test_unknown_top_level_key_rejected(self) -> None:
        message = self._invalid(lambda r: r.update(extra=1))
        self.assertIn("unknown key", message)
        self.assertIn("extra", message)

    def test_repos_must_be_a_list(self) -> None:
        self.assertIn("repos must be a list", self._invalid(lambda r: r.update(repos="x")))

    def test_unknown_repo_key_rejected(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(bogus=1))
        self.assertIn("repos[0] has unknown key", message)

    def test_repo_path_must_be_non_empty_string(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(path=""))
        self.assertIn("path must be a non-empty string", message)

    def test_repo_url_must_be_non_empty_string(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(url=""))
        self.assertIn("url must be a non-empty string", message)

    def test_repo_packages_must_be_auto_or_list(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(packages="all"))
        self.assertIn("auto", message)

    def test_repo_packages_rejects_invalid_name(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(packages=["bad/name"]))
        self.assertIn("invalid package name", message)

    def test_repo_private_must_be_boolean(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(private="yes"))
        self.assertIn("private must be a boolean", message)

    def test_repo_order_must_be_integer(self) -> None:
        message = self._invalid(lambda r: r["repos"][0].update(order="1"))
        self.assertIn("order must be an integer", message)

    def test_duplicate_order_rejected(self) -> None:
        message = self._invalid(lambda r: r["repos"][1].update(order=1))
        self.assertIn("duplicate order: 1", message)

    def test_skip_packages_must_be_list(self) -> None:
        message = self._invalid(lambda r: r.update(skip_packages="odd"))
        self.assertIn("skip_packages", message)

    def test_post_unknown_key_rejected(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(extra=True))
        self.assertIn("post[0] has unknown key", message)

    def test_post_id_must_be_non_empty(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(id=""))
        self.assertIn("id must be a non-empty string", message)

    def test_duplicate_post_id_rejected(self) -> None:
        message = self._invalid(lambda r: r["post"][1].update(id="wallpaper-tint"))
        self.assertIn("duplicate post id", message)

    def test_post_argv_must_be_non_empty_list(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(argv=[]))
        self.assertIn("argv must be a non-empty list", message)

    def test_post_argv0_must_resolve_inside_home(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(argv=["/usr/bin/env"]))
        self.assertIn("$HOME", message)

    def test_post_timeout_must_be_positive_integer(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(timeout_s=0))
        self.assertIn("timeout_s must be a positive integer", message)

    def test_services_must_be_strings(self) -> None:
        message = self._invalid(lambda r: r.update(services=[1]))
        self.assertIn("services must be a list of strings", message)

    def test_post_needs_must_be_a_list_of_strings(self) -> None:
        message = self._invalid(lambda r: r["post"][0].update(needs="gowall"))
        self.assertIn("needs", message)
        message = self._invalid(lambda r: r["post"][0].update(needs=[""]))
        self.assertIn("needs", message)

    def test_post_needs_is_normalized(self) -> None:
        recipe = valid_setup_recipe()
        recipe["post"][0]["needs"] = ["gowall", "jq"]
        result = ss.validate_setup_recipe(recipe)
        self.assertEqual(result["post"][0]["needs"], ["gowall", "jq"])
        self.assertEqual(result["post"][1]["needs"], [])

    def test_example_recipe_declares_needs_and_mise_step(self) -> None:
        recipe = valid_setup_recipe()
        by_id = {entry["id"]: entry for entry in recipe["post"]}
        self.assertEqual(by_id["wallpaper-tint"]["needs"], ["gowall"])
        self.assertIn("mise-install", by_id)
        self.assertTrue(by_id["mise-install"]["argv"][0].startswith("~/"))


# --------------------------------------------------------------------------
# .stow-sync is never a package; connect
# --------------------------------------------------------------------------


class SetupConnectTests(SetupTestBase):
    def test_stow_sync_directory_is_never_a_package(self) -> None:
        self.env.clone_dotfiles()
        self.assertNotIn(".stow-sync", ss.detect_packages(str(self.dotfiles)))
        plan = self.plan()
        self.assertTrue(plan["ok"], plan)
        self.assertNotIn(".stow-sync", [entry["package"] for entry in plan["plan"]["link"]])

    def test_connect_fresh_clone_returns_recipe(self) -> None:
        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "cloned")
        self.assertEqual(result["path"], "~/.dotfiles")
        self.assertEqual([entry["path"] for entry in result["repos"]], ["~/wallpapers"])
        self.assertFalse((self.home / "wallpapers").exists())
        self.assertEqual(result["recipe"]["version"], 1)
        self.assertTrue((self.dotfiles / ".stow-sync" / "setup.json").is_file())

    def test_connect_second_time_reports_ready(self) -> None:
        first = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertEqual(first["state"], "cloned")
        second = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["state"], "ready")

    def test_connect_wrong_remote_refuses(self) -> None:
        self.env.clone_dotfiles()
        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.plain_bare)], None, str(self.state)
        )
        self.assertFalse(result["ok"])
        self.assertIn("different remote", result["error"])

    def test_connect_not_a_repo_refuses(self) -> None:
        self.dotfiles.mkdir(parents=True)
        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertFalse(result["ok"])
        self.assertIn("not a git repository", result["error"])

    def test_connect_missing_recipe_returns_hint(self) -> None:
        result = ss.dispatch(
            [
                "setup-connect",
                "--url",
                str(self.env.plain_bare),
                "--path",
                str(self.home / "plain"),
            ],
            None,
            str(self.state),
        )
        self.assertTrue(result["ok"], result)
        self.assertIsNone(result["recipe"])
        self.assertIn(".stow-sync/setup.json", result["hint"])

    def test_connect_clones_dotfiles_and_lists_other_repos(self) -> None:
        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.dotfiles / ".stow-sync" / "setup.json").is_file())
        self.assertFalse((self.home / "wallpapers").exists())
        self.assertEqual([entry["path"] for entry in result["repos"]], ["~/wallpapers"])
        clone = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(clone["ok"], clone)
        self.assertEqual(clone["state"], "cloned")
        self.assertTrue((self.home / "wallpapers").is_dir())

    def test_connect_reports_private_repo_auth_failure(self) -> None:
        real_run_bounded = ss.run_bounded

        def fake_run_bounded(argv, timeout, *rest, **kwargs):
            if any("clone" in str(a) for a in argv) and any("wallpapers" in str(a) for a in argv):
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    b"",
                    b"fatal: could not read Username for 'https://github.com': "
                    b"terminal prompts disabled",
                )
            return real_run_bounded(argv, timeout, *rest, **kwargs)

        result = ss.dispatch(
            ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.dotfiles / ".stow-sync" / "setup.json").is_file())
        self.assertFalse((self.home / "wallpapers").exists())
        with patch.object(ss, "run_bounded", side_effect=fake_run_bounded):
            clone = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(clone["ok"], clone)
        self.assertEqual(clone["state"], "error")
        self.assertIn("private", clone["error"])
        self.assertIn("gh auth login", clone["error"])

    def test_connect_auth_failure_marks_auth_error(self) -> None:
        # Finding 29: the dotfiles clone failing on auth must carry auth_error so
        # the Connect step can show the fix and "Check again".
        real_run_bounded = ss.run_bounded

        def fake_run_bounded(argv, timeout, *rest, **kwargs):
            if any("clone" in str(a) for a in argv) and any(
                "dotfiles.git" in str(a) for a in argv
            ):
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    b"",
                    b"fatal: could not read Username for 'https://github.com': "
                    b"terminal prompts disabled",
                )
            return real_run_bounded(argv, timeout, *rest, **kwargs)

        with patch.object(ss, "run_bounded", side_effect=fake_run_bounded):
            result = ss.dispatch(
                ["setup-connect", "--url", str(self.env.dotfiles_bare)], None, str(self.state)
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["auth_error"])
        self.assertIn("gh auth login", result["error"])

    def test_clone_auth_failure_marks_auth_error(self) -> None:
        self.env.clone_dotfiles()
        real_run_bounded = ss.run_bounded

        def fake_run_bounded(argv, timeout, *rest, **kwargs):
            if any("clone" in str(a) for a in argv) and any(
                "wallpapers" in str(a) for a in argv
            ):
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    b"",
                    b"fatal: could not read Username for 'https://github.com': "
                    b"terminal prompts disabled",
                )
            return real_run_bounded(argv, timeout, *rest, **kwargs)

        with patch.object(ss, "run_bounded", side_effect=fake_run_bounded):
            clone = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(clone["ok"], clone)
        self.assertEqual(clone["state"], "error")
        self.assertTrue(clone["auth_error"])
        self.assertIn("gh auth login", clone["error"])



# --------------------------------------------------------------------------
# Plan classification
# --------------------------------------------------------------------------


class SetupPlanTests(SetupTestBase):
    def test_plan_classifies_identical_different_new_and_already(self) -> None:
        self.env.clone_dotfiles()
        stow_apply(self.dotfiles, self.home, "omarchy")
        plan = self.plan()
        self.assertTrue(plan["ok"], plan)

        fish = self.link_entry(plan, "fish")
        self.assertEqual(fish["status"], "conflicts")
        self.assertEqual(fish["conflicts"][0]["kind"], "identical")
        self.assertEqual(fish["files_to_backup"], 1)

        ghostty = self.link_entry(plan, "ghostty")
        self.assertEqual(ghostty["status"], "conflicts")
        self.assertEqual(ghostty["conflicts"][0]["kind"], "different")

        nvim = self.link_entry(plan, "nvim")
        self.assertEqual(nvim["conflicts"][0]["kind"], "different")

        omarchy = self.link_entry(plan, "omarchy")
        self.assertEqual(omarchy["status"], "already")

        app = self.link_entry(plan, "app")
        self.assertEqual(app["status"], "new")

        summary = plan["plan"]["summary"]
        self.assertEqual(summary["blocked_packages"], 0)
        self.assertFalse(summary["nothing_to_do"])

    def test_plan_flags_blocked_symlink(self) -> None:
        self.env.clone_dotfiles()
        foreign = self.env.root / "foreign.txt"
        write(foreign, "foreign\n")
        target = self.home / ".config" / "app" / "conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(foreign, target)
        plan = self.plan()
        app = self.link_entry(plan, "app")
        self.assertEqual(app["status"], "blocked")
        self.assertEqual(app["conflicts"][0]["kind"], "blocked")
        self.assertEqual(plan["plan"]["summary"]["blocked_packages"], 1)

    def test_plan_treats_plugin_config_as_different_conflict(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        entry = self.link_entry(plan, "stow-sync")
        self.assertEqual(entry["status"], "conflicts")
        self.assertEqual(entry["conflicts"][0]["kind"], "different")
        self.assertEqual(
            entry["conflicts"][0]["target"], "~/.config/stow-sync/config.json"
        )

    def test_plan_skips_packages_on_missing_repo_as_clone(self) -> None:
        # dotfiles is present, wallpapers is not -> clone step, no link entry.
        self.env.clone_dotfiles()
        plan = self.plan()
        self.assertEqual([entry["path"] for entry in plan["plan"]["clone"]], ["~/wallpapers"])
        self.assertNotIn("walls", [entry["package"] for entry in plan["plan"]["link"]])

    def test_plan_lists_walls_package_after_connect(self) -> None:
        # Connect clones every recipe repo, so the plan sees and reviews walls.
        self.connect()
        plan = self.plan()
        walls = self.link_entry(plan, "walls")
        self.assertEqual(walls["status"], "new")
        self.assertEqual(plan["plan"]["summary"]["repos_to_clone"], 0)
        self.assertEqual([entry["path"] for entry in plan["plan"]["clone"]], [])

    def test_plan_lists_recipe_services_requires_and_notes(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        self.assertEqual([s["unit"] for s in plan["plan"]["services"]], ["ai-tools-check.timer"])
        requires = {entry["name"]: entry["found"] for entry in plan["plan"]["requires"]}
        self.assertTrue(requires["git"])
        self.assertTrue(requires["stow"])
        self.assertEqual(plan["plan"]["notes"], ["note one", "note two"])

    def test_plan_builds_and_writes_a_real_token(self) -> None:
        # Equivalent coverage for the removed hidden `setupFixture` hook
        # (README 11): `setup-plan` always builds a real plan, writes a real
        # token to the state dir, and returns no fixture echo. A stray
        # `--fixture` argument is not a backend option any more.
        self.env.clone_dotfiles()
        stray = self.env.root / "stray-plan.json"
        stray.write_text(json.dumps({"version": 1, "link": []}), encoding="utf-8")
        result = ss.dispatch(["setup-plan", "--fixture", str(stray)], None, str(self.state))
        self.assertTrue(result["ok"], result)
        self.assertNotIn("fixture", result)
        self.assertNotEqual(result["token"], "fixture")
        self.assertGreaterEqual(len(result["plan"]["link"]), 1)
        # The real token file exists and no arbitrary JSON was echoed back.
        self.assertTrue((self.state / "setup-plan.json").exists())


# --------------------------------------------------------------------------
# Token lifecycle
# --------------------------------------------------------------------------


class SetupTokenTests(SetupTestBase):
    def _plan_file(self) -> Path:
        return self.state / "setup-plan.json"

    def test_token_fresh_accepted(self) -> None:
        self.env.clone_dotfiles()
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        self.assertIn("backup", result)

    def test_missing_token_rejected(self) -> None:
        result = self.apply("deadbeef")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "The setup plan changed. Review it again.")

    def test_stale_token_rejected(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        stored = json.loads(self._plan_file().read_text(encoding="utf-8"))
        stored["created"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(
            timespec="seconds"
        )
        self._plan_file().write_text(json.dumps(stored), encoding="utf-8")
        result = self.apply(plan["token"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "The setup plan changed. Review it again.")

    def test_mismatched_plan_rejected(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        recipe_path = self.dotfiles / ".stow-sync" / "setup.json"
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        recipe["notes"].append("changed after review")
        recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        result = self.apply(plan["token"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "The setup plan changed. Review it again.")

    def test_tampered_canonical_rejected(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        stored = json.loads(self._plan_file().read_text(encoding="utf-8"))
        stored["canonical"] = stored["canonical"].replace("version", "verison", 1)
        self._plan_file().write_text(json.dumps(stored), encoding="utf-8")
        result = self.apply(plan["token"])
        self.assertFalse(result["ok"])


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------


class SetupApplyTests(SetupTestBase):
    def test_apply_reports_a_missing_repo_and_never_links_unreviewed(self) -> None:
        # Only dotfiles is on disk: the plan lists wallpapers as a clone step
        # and has no "walls" link, so apply must neither clone nor link it.
        self.env.clone_dotfiles()
        plan = self.plan()
        self.assertEqual([entry["path"] for entry in plan["plan"]["clone"]], ["~/wallpapers"])
        self.assertNotIn("walls", [entry["package"] for entry in plan["plan"]["link"]])
        result = self.apply(plan["token"])
        self.assertTrue(result["ok"], result)
        skipped = {entry["path"]: entry for entry in result["skipped"] if "path" in entry}
        self.assertEqual(skipped["~/wallpapers"]["reason"], "Run Connect again")
        self.assertFalse((self.home / "wallpapers").exists())
        self.assertFalse((self.home / ".config" / "walls").exists())
        self.assertNotIn("walls", [entry["package"] for entry in result["applied"]])
        self.assertIn("fish", [entry["package"] for entry in result["applied"]])

    def test_apply_happy_path_links_backs_up_and_preserves_modes(self) -> None:
        self.connect()
        os.chmod(self.home / ".config" / "fish" / "config.fish", 0o600)
        os.chmod(self.home / ".config" / "ghostty" / "config", 0o640)
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)

        fish = self.home / ".config" / "fish" / "config.fish"
        self.assertTrue(fish.is_symlink())
        self.assertEqual(os.path.realpath(fish), os.path.realpath(self.dotfiles / "fish" / ".config" / "fish" / "config.fish"))
        config = self.home / ".config" / "stow-sync" / "config.json"
        self.assertTrue(config.is_symlink())
        self.assertTrue(result["config_reloaded"])

        manifest_path = self.state / "setup-backups" / result["backup"] / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["moves"]), 4)
        by_path = {move["path"]: move for move in manifest["moves"]}
        backup_root = self.state / "setup-backups" / result["backup"] / "files"
        fish_move = by_path["~/.config/fish/config.fish"]
        fish_backup = backup_root / fish_move["backup"]
        self.assertEqual(fish_backup.read_text(encoding="utf-8"), self.env.fish_default)
        self.assertEqual(fish_backup.stat().st_mode & 0o777, 0o600)
        ghostty_move = by_path["~/.config/ghostty/config"]
        ghostty_backup = backup_root / ghostty_move["backup"]
        self.assertEqual(ghostty_backup.read_text(encoding="utf-8"), self.env.ghostty_default)
        self.assertEqual(ghostty_backup.stat().st_mode & 0o777, 0o640)

    def test_apply_with_one_failing_package_rolls_it_back(self) -> None:
        self.connect()
        real_stow = ss.stow_real

        def fake_stow(repo_dir, target_dir, package, timeout=30):
            if package == "ghostty":
                return subprocess.CompletedProcess(["stow"], 1, b"", b"stow: simulated failure")
            return real_stow(repo_dir, target_dir, package, timeout)

        plan = self.plan()
        with patch.object(ss, "stow_real", side_effect=fake_stow):
            result = self.apply(plan["token"])
        self.assertTrue(result["ok"], result)
        self.assertEqual([entry["package"] for entry in result["failed"]], ["ghostty"])
        ghostty = self.home / ".config" / "ghostty" / "config"
        self.assertFalse(ghostty.is_symlink())
        self.assertEqual(ghostty.read_text(encoding="utf-8"), self.env.ghostty_default)
        fish = self.home / ".config" / "fish" / "config.fish"
        self.assertTrue(fish.is_symlink())

    def test_apply_enables_services_via_fake_systemctl(self) -> None:
        self.connect()
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        self.assertEqual([entry["unit"] for entry in result["services"]], ["ai-tools-check.timer"])
        self.assertTrue(all(entry["ok"] for entry in result["services"]))
        log = self.env.systemctl_log.read_text(encoding="utf-8")
        self.assertIn("--user daemon-reload", log)
        self.assertIn("--user enable --now ai-tools-check.timer", log)

    def test_steps_only_run_writes_no_backup(self) -> None:
        # Finding 89: re-running with only post steps changes no files, so it
        # must not create an empty, un-undoable backup entry.
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\nexit 0\n")
        first = self.plan_and_apply()
        self.assertTrue(first["ok"], first)
        self.assertNotEqual(first["backup"], "")
        backups_dir = self.state / "setup-backups"
        before = sorted(path.name for path in backups_dir.iterdir())
        again = self.plan()
        self.assertTrue(again["plan"]["summary"]["nothing_to_do"], again["plan"]["summary"])
        self.assertEqual(again["plan"]["summary"]["packages_to_link"], 0)
        second = self.apply(again["token"])
        self.assertTrue(second["ok"], second)
        self.assertTrue(second.get("steps_only"), second)
        self.assertEqual(second["backup"], "")
        self.assertEqual(sorted(path.name for path in backups_dir.iterdir()), before)
        listed = ss.dispatch(["setup-backups"], None, str(self.state))
        self.assertEqual([row["id"] for row in listed["backups"]], before)

    def test_post_default_selection_runs_only_defaults(self) -> None:
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\nexit 0\n")
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        self.assertEqual([entry["id"] for entry in result["post"]], ["hello"])
        self.assertTrue(result["post"][0]["ok"])

    def test_post_override_and_timeout_are_reported(self) -> None:
        self.connect()
        self.env.install_script("slow", "#!/bin/sh\nsleep 5\n")
        result = self.plan_and_apply(["--post", "slow"])
        self.assertTrue(result["ok"], result)
        self.assertEqual([entry["id"] for entry in result["post"]], ["slow"])
        self.assertFalse(result["post"][0]["ok"])
        self.assertIn("timed out", result["post"][0]["error"])

    def test_second_plan_is_idempotent(self) -> None:
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\nexit 0\n")
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        second = self.plan()
        summary = second["plan"]["summary"]
        self.assertEqual(summary["repos_to_clone"], 0)
        self.assertEqual(summary["files_to_backup"], 0)
        self.assertEqual(summary["packages_to_link"], 0)
        self.assertTrue(summary["nothing_to_do"])
        self.assertTrue(all(entry["status"] in ("already",) for entry in second["plan"]["link"]))

    def test_apply_returns_rich_result(self) -> None:
        self.connect()
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        self.assertTrue(os.path.isabs(result["backup_dir"]))
        self.assertTrue(os.path.isdir(result["backup_dir"]))
        self.assertEqual(result["notes"], ["note one", "note two"])
        packages = {entry["package"]: entry for entry in result["packages"]}
        self.assertEqual(packages["fish"]["state"], "applied")
        self.assertIn("repo", packages["fish"])
        moved = {entry["path"]: entry for entry in result["moved"]}
        self.assertIn("~/.config/fish/config.fish", moved)
        self.assertTrue(os.path.isabs(moved["~/.config/fish/config.fish"]["backup"]))
        self.assertEqual(result["services"][0]["unit"], "ai-tools-check.timer")
        self.assertEqual(result["services"][0]["state"], "enabled")


# --------------------------------------------------------------------------
# Undo and backups
# --------------------------------------------------------------------------


class SetupUndoTests(SetupTestBase):
    def _apply(self) -> dict:
        self.connect()
        os.chmod(self.home / ".config" / "fish" / "config.fish", 0o600)
        return self.plan_and_apply()

    def test_undo_restores_byte_identical_originals_and_modes(self) -> None:
        result = self._apply()
        undo = ss.dispatch(["setup-undo", "--backup", result["backup"]], None, str(self.state))
        self.assertTrue(undo["ok"], undo)
        self.assertEqual(undo["errors"], [])
        fish = self.home / ".config" / "fish" / "config.fish"
        self.assertFalse(fish.is_symlink())
        self.assertEqual(fish.read_text(encoding="utf-8"), self.env.fish_default)
        self.assertEqual(fish.stat().st_mode & 0o777, 0o600)
        nvim = self.home / ".config" / "nvim" / "init.lua"
        self.assertEqual(nvim.read_text(encoding="utf-8"), self.env.nvim_default)

    def test_undo_refuses_a_destination_that_changed(self) -> None:
        result = self._apply()
        fish = self.home / ".config" / "fish" / "config.fish"
        os.unlink(fish)
        write(fish, "tampered\n")
        undo = ss.dispatch(["setup-undo", "--backup", result["backup"]], None, str(self.state))
        self.assertTrue(undo["ok"], undo)
        self.assertIn("fish", [entry["package"] for entry in undo["refused"]])
        self.assertEqual(fish.read_text(encoding="utf-8"), "tampered\n")
        self.assertTrue(any("~/.config/fish/config.fish" == entry["path"] for entry in undo["errors"]))

    def test_crash_mid_apply_is_undoable(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        real_move = ss._setup_perform_move
        calls = {"count": 0}

        def crashing_move(src, dst):
            calls["count"] += 1
            if calls["count"] > 2:
                raise RuntimeError("simulated crash")
            return real_move(src, dst)

        with patch.object(ss, "_setup_perform_move", side_effect=crashing_move):
            with self.assertRaises(RuntimeError):
                self.apply(plan["token"])

        backups = list((self.state / "setup-backups").iterdir())
        self.assertEqual(len(backups), 1)
        manifest_path = backups[0] / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest["moves"]), 2)

        undo = ss.dispatch(["setup-undo", "--backup", backups[0].name], None, str(self.state))
        self.assertTrue(undo["ok"], undo)
        self.assertEqual(
            (self.home / ".config" / "fish" / "config.fish").read_text(encoding="utf-8"),
            self.env.fish_default,
        )
        self.assertEqual(
            (self.home / ".config" / "ghostty" / "config").read_text(encoding="utf-8"),
            self.env.ghostty_default,
        )
        self.assertEqual(
            (self.home / ".config" / "nvim" / "init.lua").read_text(encoding="utf-8"),
            self.env.nvim_default,
        )

    def test_setup_backups_lists_counts(self) -> None:
        result = self._apply()
        listing = ss.dispatch(["setup-backups"], None, str(self.state))
        self.assertTrue(listing["ok"], listing)
        self.assertEqual(len(listing["backups"]), 1)
        entry = listing["backups"][0]
        self.assertEqual(entry["id"], result["backup"])
        self.assertEqual(entry["counts"]["moved"], 4)
        self.assertEqual(entry["counts"]["packages"], 7)
        self.assertEqual(entry["counts"]["services"], 1)
        self.assertFalse(entry["undone"])

    def test_second_undo_refuses_already_undone(self) -> None:
        result = self._apply()
        first = ss.dispatch(["setup-undo", "--backup", result["backup"]], None, str(self.state))
        self.assertTrue(first["ok"], first)
        listing = ss.dispatch(["setup-backups"], None, str(self.state))
        self.assertTrue(listing["backups"][0]["undone"])
        second = ss.dispatch(["setup-undo", "--backup", result["backup"]], None, str(self.state))
        self.assertFalse(second["ok"])
        self.assertIn("already undone", second["error"])

    def test_undo_disables_services_before_unstow_and_clears_wants(self) -> None:
        result = self._apply()
        wants = (
            self.home
            / ".config"
            / "systemd"
            / "user"
            / "timers.target.wants"
            / "ai-tools-check.timer"
        )
        wants.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(
            str(self.dotfiles / "ai-tools" / ".config" / "systemd" / "user" / "ai-tools-check.timer"),
            wants,
        )
        wrapper = self.env.install_fake_stow_wrapper(self.env.systemctl_log)
        self.addCleanup(lambda: wrapper.unlink(missing_ok=True))
        undo = ss.dispatch(["setup-undo", "--backup", result["backup"]], None, str(self.state))
        self.assertTrue(undo["ok"], undo)
        self.assertEqual(
            [entry["unit"] for entry in undo["services_disabled"]], ["ai-tools-check.timer"]
        )
        self.assertTrue(all(entry["ok"] for entry in undo["services_disabled"]))
        self.assertFalse(wants.exists())
        log = self.env.systemctl_log.read_text(encoding="utf-8")
        self.assertIn("--user disable --now ai-tools-check.timer", log)
        self.assertLess(
            log.index("--user disable --now ai-tools-check.timer"),
            log.index("stow -D"),
        )


class SetupPrereqsTests(SetupTestBase):
    def prereqs(self, extra: list[str] | None = None) -> dict:
        args = ["setup-prereqs"]
        if extra:
            args += extra
        return ss.dispatch(args, None, str(self.state))

    def check(self, result: dict, cid: str) -> dict:
        for entry in result["checks"]:
            if entry["id"] == cid:
                return entry
        raise AssertionError("no prerequisite check " + cid)

    def _db(self) -> str:
        path = self.env.root / "core.db"
        path.write_text("x", encoding="utf-8")
        return str(path)

    def _gh_missing(self):
        """Patch ``which`` so only ``gh`` looks absent (README 11c.3)."""
        return gh_missing_patch()

    def test_all_present_and_no_github(self) -> None:
        with self._gh_missing(), patch.object(ss, "PACMAN_SYNC_DB", self._db()):
            result = self.prereqs()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["ok_to_connect"])
        self.assertFalse(result["needs_gh"])
        self.assertEqual({c["id"] for c in result["checks"]}, {"stow", "git", "pacman-db"})

    def test_gh_login_row_present_when_gh_installed(self) -> None:
        # Finding 29: with gh installed, Check must always show a GitHub login
        # row even before any private repo is known; it never blocks by itself.
        self.env.install_fake_gh_output(
            "github.com\n  - Active account: true\n"
            "  Logged in to github.com account tester (keyring)\n",
            0,
        )
        with patch.object(ss, "PACMAN_SYNC_DB", self._db()):
            result = self.prereqs()
        self.assertFalse(result["needs_gh"])
        self.assertIn("gh", [c["id"] for c in result["checks"]])
        auth = self.check(result, "gh-auth")
        self.assertTrue(auth["ok"])
        self.assertEqual(auth["detail"], "signed in as tester")
        self.assertTrue(result["ok_to_connect"])

    def test_gh_login_row_not_signed_in_is_non_blocking(self) -> None:
        self.env.install_fake_gh(1)
        with patch.object(ss, "PACMAN_SYNC_DB", self._db()):
            result = self.prereqs()
        auth = self.check(result, "gh-auth")
        self.assertFalse(auth["ok"])
        self.assertEqual(auth["detail"], "not signed in")
        self.assertIn("gh auth login", auth["fix"])
        self.assertFalse(result["needs_gh"])
        self.assertTrue(result["ok_to_connect"])
        self.assertNotIn("gh-auth", result["blocking"])


    def test_missing_stow_and_git_block(self) -> None:
        with patch.object(ss.shutil, "which", return_value=None):
            result = self.prereqs()
        self.assertFalse(self.check(result, "stow")["ok"])
        self.assertIn("omarchy pkg add stow", self.check(result, "stow")["fix"])
        self.assertFalse(self.check(result, "git")["ok"])
        self.assertIn("omarchy pkg add git", self.check(result, "git")["fix"])
        self.assertFalse(result["ok_to_connect"])

    def test_pacman_db_missing_blocks_only_when_tool_missing(self) -> None:
        absent = str(self.env.root / "no-such-core.db")
        with patch.object(ss, "PACMAN_SYNC_DB", absent), patch.object(
            ss.shutil, "which", return_value=None
        ):
            result = self.prereqs()
        db = self.check(result, "pacman-db")
        self.assertFalse(db["ok"])
        self.assertIn("omarchy update", db["fix"])
        self.assertIn("pacman -Syu", db["detail"])
        self.assertFalse(result["ok_to_connect"])
        with patch.object(ss, "PACMAN_SYNC_DB", absent):
            ok = self.prereqs()
        self.assertFalse(self.check(ok, "pacman-db")["ok"])
        self.assertTrue(ok["ok_to_connect"])

    def test_gh_checks_only_for_private_recipe(self) -> None:
        self.env.clone_dotfiles()
        self.env.install_fake_gh(0)
        with patch.object(ss, "PACMAN_SYNC_DB", self._db()):
            result = self.prereqs()
        self.assertTrue(result["needs_gh"], result)
        self.assertTrue(self.check(result, "gh")["ok"])
        self.assertTrue(self.check(result, "gh-auth")["ok"])
        self.assertTrue(result["ok_to_connect"])

    def test_gh_auth_failure_blocks_for_private_recipe(self) -> None:
        self.env.clone_dotfiles()
        self.env.install_fake_gh(1)
        with patch.object(ss, "PACMAN_SYNC_DB", self._db()):
            result = self.prereqs()
        self.assertTrue(self.check(result, "gh")["ok"])
        auth = self.check(result, "gh-auth")
        self.assertFalse(auth["ok"])
        self.assertIn("gh auth login", auth["fix"])
        self.assertFalse(result["ok_to_connect"])

    def test_github_url_requires_gh_without_recipe(self) -> None:
        self.env.install_fake_gh(1)
        result = self.prereqs(["--url", "https://github.com/me/dotfiles.git"])
        self.assertTrue(result["needs_gh"], result)
        self.assertIn("gh-auth", [c["id"] for c in result["checks"]])
        self.assertFalse(result["ok_to_connect"])

    def test_non_github_url_without_recipe_skips_gh(self) -> None:
        with self._gh_missing():
            result = self.prereqs(["--url", "/tmp/whatever.git"])
        self.assertFalse(result["needs_gh"])
        self.assertNotIn("gh-auth", [c["id"] for c in result["checks"]])


class SetupCloneTests(SetupTestBase):
    def test_clone_clones_one_recipe_repo(self) -> None:
        self.env.clone_dotfiles()
        result = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "cloned")
        self.assertTrue((self.home / "wallpapers").is_dir())

    def test_clone_ready_when_already_present(self) -> None:
        self.env.clone_dotfiles()
        ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        again = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["state"], "ready")

    def test_clone_unknown_path_refuses(self) -> None:
        self.env.clone_dotfiles()
        result = ss.dispatch(["setup-clone", "--path", "~/nope"], None, str(self.state))
        self.assertFalse(result["ok"])
        self.assertIn("recipe", result["error"])

    def test_clone_uses_900_second_timeout(self) -> None:
        self.env.clone_dotfiles()
        captured: dict = {}
        real_run_bounded = ss.run_bounded

        def spy(argv, timeout, *rest, **kwargs):
            if any("clone" in str(a) for a in argv):
                captured["timeout"] = timeout
            return real_run_bounded(argv, timeout, *rest, **kwargs)

        with patch.object(ss, "run_bounded", side_effect=spy):
            result = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(result["ok"], result)
        self.assertEqual(captured.get("timeout"), 900)


class SetupPostNeedsTests(SetupTestBase):
    def _recipe_with_zen(self, requires_path: str) -> Path:
        recipe = valid_setup_recipe()
        recipe["post"].append(
            {
                "id": "zen-link",
                "label": "Link the Zen Browser config",
                "argv": ["~/.dotfiles/zen/zen-sync", "link"],
                "default": True,
                "timeout_s": 120,
                "requires_path": requires_path,
                "requires_hint": "Install Zen and open it once first",
            }
        )
        path = self.env.root / "recipe-zen.json"
        path.write_text(json.dumps(recipe), encoding="utf-8")
        return path

    def test_plan_marks_unavailable_post_by_requires_path(self) -> None:
        # README 12c answer 3: a requires_path glob that matches nothing disables
        # the step with the plain hint.
        self.env.clone_dotfiles()
        path = self._recipe_with_zen("~/.zen/*/prefs.js")
        plan = ss.dispatch(["setup-plan", "--recipe", str(path)], None, str(self.state))
        by_id = {entry["id"]: entry for entry in plan["plan"]["post"]}
        zen = by_id["zen-link"]
        self.assertFalse(zen["available"])
        self.assertIn("~/.zen/*/prefs.js", zen["missing"])
        self.assertEqual(zen["reason"], "Install Zen and open it once first")
        self.assertFalse(zen["default"])

    def test_plan_available_when_requires_path_matches(self) -> None:
        self.env.clone_dotfiles()
        write(self.home / ".zen" / "abc" / "prefs.js", "x\n")
        path = self._recipe_with_zen("~/.zen/*/prefs.js")
        plan = ss.dispatch(["setup-plan", "--recipe", str(path)], None, str(self.state))
        by_id = {entry["id"]: entry for entry in plan["plan"]["post"]}
        self.assertTrue(by_id["zen-link"]["available"])
        self.assertEqual(by_id["zen-link"]["reason"], "")

    def test_recipe_rejects_bad_requires_path(self) -> None:
        recipe = copy.deepcopy(valid_setup_recipe())
        recipe["post"][0]["requires_path"] = 5
        with self.assertRaises(ss.CommandError) as ctx:
            ss.validate_setup_recipe(recipe)
        self.assertIn("requires_path must be a non-empty string", str(ctx.exception))

    def test_plan_marks_unavailable_post(self) -> None:
        self.env.clone_dotfiles()
        plan = self.plan()
        by_id = {entry["id"]: entry for entry in plan["plan"]["post"]}
        needy = by_id["needy"]
        self.assertFalse(needy["available"])
        self.assertEqual(needy["missing"], ["stow-sync-missing-tool"])
        self.assertFalse(needy["default"])
        hello = by_id["hello"]
        self.assertTrue(hello["available"])
        self.assertEqual(hello["missing"], [])

    def test_apply_skips_unavailable_post_with_reason(self) -> None:
        self.connect()
        self.env.install_script("needy", "#!/bin/sh\necho should-not-run\nexit 0\n")
        result = self.plan_and_apply(["--post", "needy"])
        self.assertTrue(result["ok"], result)
        entry = result["post"][0]
        self.assertEqual(entry["id"], "needy")
        self.assertEqual(entry["state"], "skipped")
        self.assertEqual(entry["reason"], "needs stow-sync-missing-tool")
        self.assertFalse(entry["ok"])

    def test_post_result_records_exit_and_last_line(self) -> None:
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\necho first\necho hello world\nexit 0\n")
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        entry = result["post"][0]
        self.assertEqual(entry["state"], "ran")
        self.assertEqual(entry["exit"], 0)
        self.assertEqual(entry["last_line"], "hello world")

    def test_post_failure_records_last_line(self) -> None:
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\necho boom >&2\nexit 3\n")
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        entry = result["post"][0]
        self.assertEqual(entry["state"], "failed")
        self.assertEqual(entry["exit"], 3)
        self.assertEqual(entry["last_line"], "boom")


class SetupReposTests(SetupTestBase):
    def repos(self) -> dict:
        return ss.dispatch(["setup-repos"], None, str(self.state))

    def test_lists_gh_repos(self) -> None:
        self.env.install_fake_gh_output(
            '[{"name":"dotfiles","url":"https://github.com/me/dotfiles","isPrivate":false},'
            ' {"name":"wallpapers","url":"https://github.com/me/wallpapers","isPrivate":true}]'
        )
        result = self.repos()
        self.assertTrue(result["ok"], result)
        self.assertEqual([r["name"] for r in result["repos"]], ["dotfiles", "wallpapers"])
        self.assertTrue(result["repos"][1]["private"])
        self.assertFalse(result["repos"][0]["private"])

    def test_missing_gh(self) -> None:
        with patch.object(ss.shutil, "which", return_value=None):
            result = self.repos()
        self.assertFalse(result["ok"])
        self.assertIn("not installed", result["error"])

    def test_gh_failure_is_reported(self) -> None:
        self.env.install_fake_gh_output("gh: not logged in", exit_code=1)
        result = self.repos()
        self.assertFalse(result["ok"])
        self.assertIn("not logged in", result["error"])

    def test_bad_json_is_reported(self) -> None:
        self.env.install_fake_gh_output("definitely not json", exit_code=0)
        result = self.repos()
        self.assertFalse(result["ok"])
        self.assertIn("parse", result["error"])


class SetupCandidatesTests(SetupTestBase):
    CANDIDATE_REPO_LIST = json.dumps(
        [
            {
                "name": "dotfiles",
                "url": "https://github.com/me/dotfiles",
                "isPrivate": False,
                "description": "my dotfiles",
                "repositoryTopics": [{"name": "dotfiles"}],
            },
            {
                "name": "OldDotfiles",
                "url": "https://github.com/me/OldDotfiles",
                "isPrivate": False,
                "description": "old backup",
                "repositoryTopics": [],
            },
            {
                "name": "myconf",
                "url": "https://github.com/me/myconf",
                "isPrivate": False,
                "description": "",
                "repositoryTopics": [],
            },
            {
                "name": "zsh-dots",
                "url": "https://github.com/me/zsh-dots",
                "isPrivate": False,
                "description": "",
                "repositoryTopics": [],
            },
            {
                "name": "TRJS",
                "url": "https://github.com/me/TRJS",
                "isPrivate": False,
                "description": "a web portfolio",
                "repositoryTopics": [],
            },
            {
                "name": "portfolio",
                "url": "https://github.com/me/portfolio",
                "isPrivate": False,
                "description": "a website",
                "repositoryTopics": [],
            },
            {
                "name": "notes",
                "url": "https://github.com/me/notes",
                "isPrivate": False,
                "description": "",
                "repositoryTopics": [],
            },
        ]
    )

    def routes(self, search: str | None = None) -> list[dict]:
        routes: list[dict] = [
            {"match": ["repo", "list"], "stdout": self.CANDIDATE_REPO_LIST, "exit": 0},
        ]
        if search is not None:
            routes.append({"match": ["search", "code"], "stdout": search, "exit": 0})
        else:
            routes.append({"match": ["search", "code"], "exit": 1})
        routes += [
            {"match": ["contents/.stow-sync/setup.json", "dotfiles"], "stdout": "{}", "exit": 0},
            {"match": ["contents/.stow-sync/setup.json"], "exit": 1},
            {"match": ["git/trees", "myconf"], "stdout": '{"tree":[{"path":"fish/.config/fish/config.fish"},{"path":"fish/.config"}]}', "exit": 0},
            {"match": ["git/trees", "zsh-dots"], "stdout": '{"tree":[{"path":".zshrc"},{"path":"README.md"}]}', "exit": 0},
            {"match": ["git/trees", "OldDotfiles"], "stdout": '{"tree":[{"path":"README.md"},{"path":"kitty/kitty.conf"},{"path":"nvim/init.lua"},{"path":"starship.toml"},{"path":"zshrc.txt"}]}', "exit": 0},
            {"match": ["git/trees", "TRJS"], "stdout": '{"tree":[{"path":"package.json"},{"path":"app/main.tsx"},{"path":".github/workflows/ci.yml"},{"path":".gitignore"}]}', "exit": 0},
            {"match": ["git/trees", "portfolio"], "stdout": '{"tree":[{"path":"README.md"},{"path":"src/main.js"},{"path":"package.json"}]}', "exit": 0},
            {"match": ["git/trees", "notes"], "stdout": '{"tree":[{"path":"README.md"}]}', "exit": 0},
            {"match": ["auth", "status"], "stdout": "Logged in to github.com account me (keyring)\n", "exit": 0},
        ]
        return routes

    def candidates(self) -> dict:
        return ss.dispatch(["setup-candidates"], None, str(self.state))

    def test_detection_groups_definitive_likely_and_others(self) -> None:
        self.env.install_fake_gh_routes(self.routes())
        result = self.candidates()
        self.assertTrue(result["ok"], result)
        self.assertEqual([r["name"] for r in result["definitive"]], ["dotfiles"])
        self.assertEqual([r["name"] for r in result["likely"]], ["myconf", "zsh-dots"])
        self.assertEqual(
            [r["name"] for r in result["others"]],
            ["OldDotfiles", "TRJS", "portfolio", "notes"],
        )
        self.assertIn("took_ms", result)
        self.assertFalse(result["partial"])
        self.assertEqual(result["owner"], "me")
        self.assertEqual(result["definitive"][0]["detail"], "setup recipe")
        # TRJS (a web portfolio) is not stow-like; OldDotfiles matches by name only.
        trjs = [r for r in result["others"] if r["name"] == "TRJS"][0]
        self.assertFalse(trjs["hint"])
        old = [r for r in result["others"] if r["name"] == "OldDotfiles"][0]
        self.assertTrue(old["hint"])

    def test_definitive_from_code_search(self) -> None:
        search = '[{"repository":{"nameWithOwner":"me/dotfiles","name":"dotfiles"}}]'
        self.env.install_fake_gh_routes(self.routes(search=search))
        result = self.candidates()
        self.assertTrue(result["ok"], result)
        self.assertEqual([r["name"] for r in result["definitive"]], ["dotfiles"])
        self.assertNotIn("myconf", [r["name"] for r in result["definitive"]])

    def test_missing_gh_reports_error(self) -> None:
        with gh_missing_patch():
            result = self.candidates()
        self.assertFalse(result["ok"])
        self.assertIn("not installed", result["error"])


class RepoShapeTests(unittest.TestCase):
    """Likely-dotfiles heuristic (README 12a/finding 50)."""

    def test_stow_shaped_repo_is_likely(self) -> None:
        self.assertTrue(
            ss._repo_looks_like_stow(
                ["fish/.config/fish/config.fish", "nvim/.config/nvim/init.lua", "README.md"]
            )
        )
        self.assertTrue(ss._repo_looks_like_stow([".zshrc", "README.md"]))
        self.assertTrue(ss._repo_looks_like_stow(["zsh/.zshrc", "README.md"]))
        self.assertTrue(ss._repo_looks_like_stow(["local/.local/share/x"]))

    def test_generic_web_project_is_not_likely(self) -> None:
        trjs = [
            "package.json",
            "app/main.tsx",
            "app/components/Scene.tsx",
            "app/lib/lang.ts",
            ".github/workflows/ci.yml",
            ".gitignore",
            ".env.example",
            ".eslintrc.json",
            "biome.json",
            "src/main.js",
        ]
        self.assertFalse(ss._repo_looks_like_stow(trjs))

    def test_olddotfiles_shaped_repo_is_not_likely(self) -> None:
        # Real pwn27sbx/OldDotfiles: per-app folders with direct config files, no
        # .config/.local anywhere and no shell dotfile (zshrc.txt, not .zshrc).
        old = [
            "README.md",
            "kitty/kitty.conf",
            "fastfetch/config.jsonc",
            "nvim/init.lua",
            "nvim/lua/config/lazy.lua",
            "starship.toml",
            "zshrc.txt",
            "nvim/.gitignore",
        ]
        self.assertFalse(ss._repo_looks_like_stow(old))

    def test_generic_project_dotfiles_do_not_count(self) -> None:
        self.assertFalse(
            ss._repo_looks_like_stow(
                [".gitignore", ".eslintrc.json", ".prettierrc", ".github/workflows/ci.yml", ".vscode/settings.json", ".env.local"]
            )
        )

    def test_non_list_is_not_likely(self) -> None:
        self.assertFalse(ss._repo_looks_like_stow(None))
        self.assertFalse(ss._repo_looks_like_stow([]))


class SetupRepoSizesTests(SetupTestBase):
    """GitHub download estimates (README 12c answer 2)."""

    def test_github_owner_repo_parses_urls(self) -> None:
        self.assertEqual(ss._github_owner_repo("https://github.com/me/dotfiles.git"), ("me", "dotfiles"))
        self.assertEqual(ss._github_owner_repo("git@github.com:me/wallpapers.git"), ("me", "wallpapers"))
        self.assertIsNone(ss._github_owner_repo("/tmp/local/repo.git"))

    def test_github_size_is_read_and_unknown_is_none(self) -> None:
        self.env.install_fake_gh_routes([
            {"match": ["repos/me/dotfiles"], "stdout": '{"size": 3072}', "exit": 0},
            {"match": ["repos/me/empty"], "stdout": '{"size": 0}', "exit": 0},
        ])
        self.assertEqual(
            ss._gh_repo_size_bytes("https://github.com/me/dotfiles.git", ss._gh_env()),
            3072 * 1024,
        )
        self.assertIsNone(ss._gh_repo_size_bytes("https://github.com/me/empty", ss._gh_env()))
        self.assertIsNone(ss._gh_repo_size_bytes("file:///tmp/x", ss._gh_env()))


class RunWithDeadlineTests(unittest.TestCase):
    def test_maps_all_items_when_fast(self) -> None:
        results, pending = ss._run_with_deadline(
            [1, 2, 3, 4, 5], lambda x: x * 2, time.monotonic() + 5, 4
        )
        self.assertEqual(dict(results), {1: 2, 2: 4, 3: 6, 4: 8, 5: 10})
        self.assertEqual(pending, [])

    def test_partial_results_when_deadline_is_missed(self) -> None:
        def slow(x):
            time.sleep(0.4)
            return x

        results, pending = ss._run_with_deadline(
            list(range(8)), slow, time.monotonic() + 0.2, 2
        )
        self.assertEqual(results, {})
        self.assertEqual(sorted(pending), list(range(8)))

    def test_worker_exception_is_unknown_not_fatal(self) -> None:
        def boom(x):
            if x == 2:
                raise RuntimeError("boom")
            return x

        results, pending = ss._run_with_deadline([1, 2, 3], boom, time.monotonic() + 5, 4)
        self.assertEqual(results[1], 1)
        self.assertIsNone(results[2])
        self.assertEqual(results[3], 3)


class SetupFixtureRemovalTests(SetupTestBase):
    """The pre-release checklist removes the hidden fixture hooks (README 11).

    Equivalent coverage: the real apply result renders the Report step (node
    `setupReport` tests plus the apply tests above); these tests pin that the
    removed commands/options no longer exist so they cannot creep back.
    """

    def test_setup_fixture_command_is_gone(self) -> None:
        path = self.env.root / "apply.json"
        path.write_text(json.dumps({"ok": True, "backup": "x"}), encoding="utf-8")
        result = ss.dispatch(["setup-fixture", "--path", str(path)], None, str(self.state))
        self.assertFalse(result["ok"])
        self.assertIn("unknown command", result["error"])

    def test_setup_fixture_is_not_in_commands(self) -> None:
        self.assertNotIn("setup-fixture", ss.COMMANDS)


class SetupApplyProgressTests(SetupTestBase):
    def test_apply_writes_progress_file(self) -> None:
        self.connect()
        self.env.install_script("hello", "#!/bin/sh\nexit 0\n")
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        path = self.state / "setup-progress.json"
        self.assertTrue(path.is_file(), "setup-progress.json was not written")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "apply")
        self.assertEqual(data["total"], len(data["items"]))
        self.assertEqual({item["kind"] for item in data["items"]}, {"package", "service", "post"})
        states = {item["state"] for item in data["items"]}
        self.assertFalse(states & {"waiting", "running"}, states)
        self.assertEqual(data["done"], data["total"])

    def test_apply_progress_is_read_only_safe(self) -> None:
        # A failed plan (stale token) never writes a progress file.
        self.env.clone_dotfiles()
        result = self.apply("nope")
        self.assertFalse(result["ok"])
        self.assertFalse((self.state / "setup-progress.json").exists())


class SetupStatusAfterApplyTests(SetupTestBase):
    def test_status_after_apply_reports_no_conflicts(self) -> None:
        # Regression for finding 47: a fresh status right after a successful
        # apply must not report the pre-apply conflicts.
        self.connect()
        result = self.plan_and_apply()
        self.assertTrue(result["ok"], result)
        status = ss.dispatch(["status"], None, str(self.state))
        self.assertTrue(status["ok"], status)
        for repo in status["repos"]:
            for package in repo.get("packages", []):
                self.assertNotEqual(package.get("health"), "conflicts", package)


class SetupOverlayOrderTests(unittest.TestCase):
    def test_confirm_card_is_declared_after_the_wizard(self) -> None:
        # Regression for finding 45: the confirm overlay must stack above the
        # wizard, so it is declared later in Panel.qml.
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertGreater(
            panel.index("ConfirmCard {"),
            panel.index("SetupWizard {"),
            "ConfirmCard must be declared after SetupWizard so it stacks on top",
        )


class ConfirmCardLayoutTests(unittest.TestCase):
    """Regression for finding 46: the wrapped sentence must sit on its own row
    above the buttons, and the card must reserve room for the button row so the
    text can never run under Cancel (README 11d.5)."""

    def test_card_height_reserves_the_button_row(self) -> None:
        source = (ROOT / "ConfirmCard.qml").read_text(encoding="utf-8")
        height_line = next(
            line
            for line in source.splitlines()
            if "chrome.implicitHeight" in line and "height:" not in line
        )
        self.assertIn("buttonRow.implicitHeight", height_line)
        # The message is declared before the buttons (title, sentence, buttons).
        self.assertLess(source.index("text: root.message"), source.index("id: buttonRow"))


class SetupGroupHeaderSourceTests(unittest.TestCase):
    """Finding 11d regression: every group count renders exactly once."""

    def test_header_renders_the_count_through_one_helper(self) -> None:
        header = (ROOT / "SetupGroupHeader.qml").read_text(encoding="utf-8")
        self.assertIn('import "Model.js" as Model', header)
        self.assertIn("Model.groupCountLabel(", header)
        # The header must not concatenate the raw count itself, which doubled it.
        self.assertNotIn("String(root.count)", header)

    def test_review_and_report_share_the_header(self) -> None:
        for name in ("SetupReview.qml", "SetupReport.qml"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("SetupGroupHeader {", source)


class SetupWizardFocusTests(unittest.TestCase):
    """Regression: while the URL field is focused the panel must not eat keys
    (README 12c fix)."""

    def test_url_field_focus_reaches_the_panel_gate(self) -> None:
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        picker = (ROOT / "SetupRepoPicker.qml").read_text(encoding="utf-8")
        connect = (ROOT / "SetupConnect.qml").read_text(encoding="utf-8")
        step = (ROOT / "SetupStep.qml").read_text(encoding="utf-8")
        # The picker reports the real field focus...
        self.assertIn("onActiveFocusChanged", picker)
        self.assertIn("urlFocusChanged", picker)
        # ...threaded through SetupConnect and SetupStep...
        self.assertIn("urlFocusChanged", connect)
        self.assertIn("urlFocusChanged", step)
        # ...into the panel gate, which is no longer hard-coded false.
        self.assertIn("contentActiveFocus: root.urlFocused", wizard)
        self.assertNotIn("contentActiveFocus: false", wizard)

    def test_stepper_draws_connector_lines(self) -> None:
        stepper = (ROOT / "SetupStepper.qml").read_text(encoding="utf-8")
        self.assertIn("connectorLeft", stepper)
        self.assertIn("connectorRight", stepper)


class SetupWizardSpacingTests(unittest.TestCase):
    """Finding 63: the wizard header and the repo picker follow the 4/8/12/16
    scale so the title, stepper and step content never feel cramped."""

    def test_header_vertical_rhythm(self) -> None:
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        # Title -> stepper is 12; stepper block -> step content is 16.
        self.assertIn("spacing: Style.space(12)", wizard)
        self.assertIn("anchors.topMargin: Style.space(16)", wizard)

    def test_stepper_dots_and_labels_are_spaced(self) -> None:
        stepper = (ROOT / "SetupStepper.qml").read_text(encoding="utf-8")
        self.assertIn("spacing: Style.space(8)", stepper)
        self.assertNotIn("spacing: 2", stepper)

    def test_repo_picker_section_gaps(self) -> None:
        picker = (ROOT / "SetupRepoPicker.qml").read_text(encoding="utf-8")
        # Both section columns ("Your setup repo" and "Looks like a dotfiles
        # repo") use an 8px label -> card gap.
        self.assertEqual(picker.count("spacing: Style.space(8)"), 2)


class SetupWizardFooterTests(unittest.TestCase):
    """Finding 68: Back and the primary share one vertical centre, so the Undo,
    Back and primary footer buttons all carry the same vertical padding."""

    def test_every_footer_button_has_the_same_vertical_padding(self) -> None:
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertEqual(wizard.count("verticalPadding: Style.space(8)"), 3)


class SetupApplyReportLayoutTests(unittest.TestCase):
    """Finding 72: the Apply status line and bar stay pinned above the scrolling
    list. Finding 73: in the undone Report the undo result comes first."""

    def test_apply_status_is_pinned_above_a_bounded_list(self) -> None:
        step = (ROOT / "SetupStep.qml").read_text(encoding="utf-8")
        self.assertIn("property real bodyHeight: 0", step)
        self.assertIn("id: applyHeader", step)
        self.assertIn("id: applyList", step)
        self.assertIn("clip: true", step)
        self.assertIn("function scrollBy(dy)", step)

    def test_wizard_passes_the_body_height_and_delegates_scroll(self) -> None:
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertIn("bodyHeight: bodyArea.height", wizard)
        self.assertIn("body.item.scrollBy", wizard)

    def test_undo_result_precedes_the_greyed_sections(self) -> None:
        report = (ROOT / "SetupReport.qml").read_text(encoding="utf-8")
        undo = report.index("// Undo result card")
        self.assertGreaterEqual(undo, 0)
        self.assertLess(undo, report.index("model: root.sections"))
        self.assertLess(undo, report.index("// Elide in the middle"))


class RepoSectionOverviewTests(unittest.TestCase):
    """Finding 76: on a not-set-up (or just-undone) machine the Overview shows
    only the not-set-up card and hides Fix packages / Needs fixing."""

    def test_overview_uses_the_overview_state_helper(self) -> None:
        source = (ROOT / "RepoSection.qml").read_text(encoding="utf-8")
        self.assertIn("Model.overviewState(root.statusData", source)
        self.assertIn("root.overview.showSetupCard", source)
        self.assertIn("root.overview.showManagement", source)
        self.assertIn("root.overview.showUpdateHint", source)
        self.assertIn("root.overview.updateHint", source)


class SetupReviewRowsTests(unittest.TestCase):
    """Finding 70: every Afterwards row shares one style; unavailable steps are
    greyed with their reason in place of the toggle."""

    def test_afterwards_uses_one_row_style(self) -> None:
        review = (ROOT / "SetupReview.qml").read_text(encoding="utf-8")
        self.assertIn("id: postRow", review)
        self.assertIn("ToggleSwitch {", review)
        self.assertIn("visible: modelData.available === false", review)
        self.assertIn("Model.setupToggleLabel(", review)
        # The old split card/disabled branches are gone.
        self.assertNotIn("id: disabledRow", review)
        self.assertNotIn("id: postToggle", review)


class SetupSmallFixesTests(unittest.TestCase):
    """Findings 62, 64 and 75: Check again only after the check finishes, the
    collapsed rows use a right chevron, and the confirm card bounds its text."""

    def test_check_again_hides_while_checking(self) -> None:
        check = (ROOT / "SetupCheck.qml").read_text(encoding="utf-8")
        connect = (ROOT / "SetupConnect.qml").read_text(encoding="utf-8")
        step = (ROOT / "SetupStep.qml").read_text(encoding="utf-8")
        self.assertIn("visible: !root.checking", check)
        self.assertIn("property bool checking: false", connect)
        self.assertIn("visible: !root.checking", connect)
        self.assertIn("checking: root.checking", step)

    def test_collapsed_rows_use_a_right_chevron(self) -> None:
        picker = (ROOT / "SetupRepoPicker.qml").read_text(encoding="utf-8")
        # Collapsed is \uf054 (right), expanded is \uf078 (down), for both rows.
        self.assertIn('iconText: root.showAll ? "\\uf078" : "\\uf054"', picker)
        self.assertIn('iconText: root.urlOpen ? "\\uf078" : "\\uf054"', picker)

    def test_confirm_card_chrome_clips_above_the_buttons(self) -> None:
        source = (ROOT / "ConfirmCard.qml").read_text(encoding="utf-8")
        self.assertIn(
            "Math.min(implicitHeight, inner.height - buttonRow.height - Style.space(12))",
            source,
        )
        chrome = source.index("id: chrome")
        body = source.index("id: bodyArea")
        self.assertIn("clip: true", source[chrome:body])


class SetupConnectRateTests(unittest.TestCase):
    """Finding 67: the active download card shows a speed and ETA line computed
    from two consecutive clone samples."""

    def test_connect_computes_and_renders_the_rate(self) -> None:
        connect = (ROOT / "SetupConnect.qml").read_text(encoding="utf-8")
        self.assertIn("Model.downloadRate(", connect)
        self.assertIn("Model.setupDownloadCards(root.connectEntries, root.clone, root.rate)", connect)
        self.assertIn("modelData.speed", connect)


class SettingsReadyGateTests(unittest.TestCase):
    """Regression for the real-config leak: the helper must never run before
    BarWidget.injectPanel() has injected settings (README 11a fix)."""
    def test_inject_panel_sets_settings_ready(self) -> None:
        barwidget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        self.assertIn("settingsReady", barwidget, "injectPanel must set settingsReady")

    def test_on_opened_changed_does_not_start_anything(self) -> None:
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        line = next(l for l in panel.splitlines() if "onOpenedChanged" in l)
        self.assertNotIn("ensureStarted", line)
        self.assertNotIn("refresh", line)

    def test_runner_gates_on_settings_ready(self) -> None:
        runner = (ROOT / "Runner.qml").read_text(encoding="utf-8")
        self.assertIn("settingsReady", runner)
        self.assertIn("Model.runnerMayStart", runner)


class SetupRealHomeRefusalTests(unittest.TestCase):
    """The backend refuses mutating setup commands on the real HOME unless the
    caller passes an explicit --state-dir or opts in (README 10.0 incident)."""

    def test_apply_and_undo_refuse_without_state_dir_or_optin(self) -> None:
        for argv in (["setup-apply", "--token", "x"], ["setup-undo", "--backup", "x"]):
            result = ss.dispatch(argv, None, None)
            self.assertFalse(result["ok"], argv)
            self.assertIn("state-dir", result["error"])

    def test_optin_env_allows_the_real_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"STOW_SYNC_ALLOW_REAL_SETUP": "1", "STOW_SYNC_STATE_DIR": tmp}
        ):
            result = ss.dispatch(["setup-apply", "--token", "x"], None, None)
        self.assertFalse(result["ok"])
        self.assertNotIn("state-dir", result.get("error", ""))

    def test_explicit_state_dir_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ss.dispatch(["setup-apply", "--token", "x"], None, tmp)
            self.assertFalse(result["ok"])
            self.assertNotIn("state-dir", result.get("error", ""))


class CloneProgressTests(SetupTestBase):
    def test_parse_git_clone_progress(self) -> None:
        text = (
            "Cloning into 'x'...\n"
            "remote: Enumerating objects: 100% (10/10), done.\r"
            "Receiving objects:  45% (1234/2742), 410.20 MiB | 5.2 MiB/s\r"
            "Receiving objects: 100% (2742/2742), 1.02 GiB | 8.0 MiB/s, done.\r"
            "Resolving deltas:  67% (2/3)\r"
        )
        progress = ss.parse_git_clone_progress(text)
        self.assertEqual(progress["phase"], "Resolving deltas")
        self.assertEqual(progress["percent"], 67)
        self.assertIsNone(ss.parse_git_clone_progress("no progress here"))

    def test_setup_clone_writes_progress(self) -> None:
        self.env.clone_dotfiles()
        result = ss.dispatch(["setup-clone", "--path", "~/wallpapers"], None, str(self.state))
        self.assertTrue(result["ok"], result)
        data = json.loads((self.state / "setup-progress.json").read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "clone")
        self.assertEqual(data["item"], "~/wallpapers")
        self.assertEqual(data["state"], "done")


class SetupPerformMoveTests(unittest.TestCase):
    def test_refuses_an_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dst = root / "dst"
            write(src, "src\n")
            write(dst, "dst\n")
            with self.assertRaises(ss.CommandError) as ctx:
                ss._setup_perform_move(str(src), str(dst))
            message = str(ctx.exception)
            self.assertIn(str(src), message)
            self.assertIn(str(dst), message)
            self.assertEqual(src.read_text(encoding="utf-8"), "src\n")
            self.assertEqual(dst.read_text(encoding="utf-8"), "dst\n")

    def test_refuses_a_cross_filesystem_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dst = root / "dst"
            write(src, "src\n")
            with patch.object(ss.os, "replace", side_effect=OSError(errno.EXDEV, "cross-device")):
                with self.assertRaises(ss.CommandError) as ctx:
                    ss._setup_perform_move(str(src), str(dst))
            self.assertIn("filesystem", str(ctx.exception))


class SetupProgressStreamingTests(SetupTestBase):
    """End-to-end live progress (README 12a findings 52/56): the progress file
    must carry intermediate states WHILE the long request runs."""

    def _poll_until(self, path: Path, stop: threading.Event, seen: list) -> None:
        while not stop.is_set():
            try:
                seen.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
            time.sleep(0.02)

    def test_clone_writes_intermediate_percent_while_running(self) -> None:
        self.env.install_fake_slow_git()
        progress = self.state / "setup-progress.json"
        seen: list = []
        stop = threading.Event()
        thread = threading.Thread(target=self._poll_until, args=(progress, stop, seen))
        thread.start()
        try:
            result = ss._setup_repo_state(
                str(self.home / ".dotfiles"),
                "https://example.invalid/dotfiles.git",
                False,
                timeout=10,
                state_dir=str(self.state),
                item="~/.dotfiles",
            )
        finally:
            stop.set()
            thread.join()
        self.assertEqual(result["state"], "cloned", result)
        intermediate = [
            entry.get("percent")
            for entry in seen
            if isinstance(entry.get("percent"), int) and 0 < entry["percent"] < 100
        ]
        self.assertTrue(intermediate, "no intermediate percent observed: " + repr(seen))

    def test_apply_writes_intermediate_item_states(self) -> None:
        self.connect()
        self.env.install_fake_slow_stow()
        self.env.install_script("hello", "#!/bin/sh\necho hi\nexit 0\n")
        progress = self.state / "setup-progress.json"
        seen: list = []
        stop = threading.Event()
        thread = threading.Thread(target=self._poll_until, args=(progress, stop, seen))
        plan = self.plan()
        thread.start()
        try:
            result = self.apply(plan["token"])
        finally:
            stop.set()
            thread.join()
        self.assertTrue(result["ok"], result)
        partial = [
            entry
            for entry in seen
            if isinstance(entry.get("done"), int)
            and isinstance(entry.get("total"), int)
            and 0 < entry["done"] < entry["total"]
        ]
        self.assertTrue(partial, "no intermediate apply state observed: " + repr(seen))


class CleanOutputTests(unittest.TestCase):
    """Post-step output cleaning (README 11d.2 / finding 42)."""

    def _fixture(self) -> str:
        with open(ROOT / "tests" / "fixtures" / "mise_progress.txt", encoding="utf-8", newline="") as handle:
            return handle.read()

    def test_last_line_keeps_the_final_summary_sentence(self) -> None:
        line = ss._last_nonempty_line(self._fixture())
        self.assertEqual(line, "mise 7/7 \u00b7 installed 6 tools \u00b7 1 already installed in 41.7s")
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\r", line)
        for glyph in "\u2588\u2589\u258a\u258b\u258c\u258d\u258e\u258f\u2591\u2592\u2593":
            self.assertNotIn(glyph, line)

    def test_clean_output_text_removes_each_artifact(self) -> None:
        self.assertEqual(ss.clean_output_text("\x1b[31mred\x1b[0m"), "red")
        self.assertEqual(ss.clean_output_text("early\rmiddle\rfinal"), "final")
        self.assertEqual(ss.clean_output_text("go \u2588\u2588\u2589\u2591 done"), "go done")
        self.assertEqual(ss.clean_output_text("  spaced   out  "), "spaced out")
        self.assertEqual(ss.clean_output_text(""), "")

    def test_last_line_handles_empty_and_caps_length(self) -> None:
        self.assertIsNone(ss._last_nonempty_line(""))
        self.assertIsNone(ss._last_nonempty_line("   \n \r\n"))
        self.assertEqual(len(ss._last_nonempty_line("x" * 500)), 200)


# --------------------------------------------------------------------------
# Pre-release hardening audit (README 11)
# --------------------------------------------------------------------------


class HardeningAuditTests(unittest.TestCase):
    """Every fix from the README 11 hardening audit, pinned by a test.

    Covers: atomic dir-fd writes that never follow a planted symlink, bounded
    and owner-checked reads, argv-safe clone URLs, recipe path containment and
    credential scrubbing in diagnostics.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="stow-sync-hard-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._home = patch.dict(os.environ, {"HOME": str(self.root)})
        self._home.start()
        self.addCleanup(self._home.stop)

    # --- atomic, directory-fd relative writes ------------------------------

    def test_atomic_write_replaces_a_symlink_leaf(self) -> None:
        target = self.root / "target.json"
        target.write_text('{"old": true}\n', encoding="utf-8")
        link = self.root / "link.json"
        link.symlink_to(target)
        ss._write_json_atomic(str(link), {"new": 1}, 0o600)
        self.assertFalse(link.is_symlink())
        self.assertEqual(json.loads(link.read_text(encoding="utf-8")), {"new": 1})
        # The symlink target was replaced, never written through.
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})

    def test_atomic_write_through_a_symlinked_parent_dir(self) -> None:
        real_dir = self.root / "real"
        real_dir.mkdir()
        link_dir = self.root / "linked"
        link_dir.symlink_to(real_dir)
        ss._write_json_atomic(str(link_dir / "f.json"), {"v": 2}, 0o600)
        self.assertEqual(
            json.loads((real_dir / "f.json").read_text(encoding="utf-8")), {"v": 2}
        )

    def test_atomic_write_is_owner_only_and_leaves_no_temp(self) -> None:
        path = self.root / "f.json"
        ss._write_json_atomic(str(path), {"a": 1}, 0o600)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in self.root.iterdir() if ".tmp" in p.name], [])

    # --- bounded, owner-checked reads --------------------------------------

    def test_read_text_bounded_refuses_a_symlink_leaf(self) -> None:
        target = self.root / "t.txt"
        target.write_text("hi", encoding="utf-8")
        link = self.root / "l.txt"
        link.symlink_to(target)
        with self.assertRaises(ss.CommandError):
            ss.read_text_bounded(str(link), 100)

    def test_read_text_bounded_follows_a_user_symlink_inside_home(self) -> None:
        target = self.root / "real.txt"
        target.write_text("hello", encoding="utf-8")
        link = self.root / "cfg.json"
        link.symlink_to(target)
        self.assertEqual(ss.read_text_bounded(str(link), 100, allow_symlink=True), "hello")

    def test_read_text_bounded_rejects_oversized(self) -> None:
        big = self.root / "big.txt"
        big.write_text("x" * 200, encoding="utf-8")
        with self.assertRaises(ss.CommandError):
            ss.read_text_bounded(str(big), 100)

    def test_read_text_bounded_missing_is_none(self) -> None:
        self.assertIsNone(ss.read_text_bounded(str(self.root / "nope"), 100))

    def test_read_text_bounded_rejects_a_directory(self) -> None:
        sub = self.root / "sub"
        sub.mkdir()
        with self.assertRaises(ss.CommandError):
            ss.read_text_bounded(str(sub), 100)

    def test_read_text_bounded_rejects_a_foreign_owner(self) -> None:
        owned = self.root / "owned.txt"
        owned.write_text("x", encoding="utf-8")
        with patch.object(ss.os, "geteuid", return_value=os.geteuid() + 12345):
            with self.assertRaises(ss.CommandError):
                ss.read_text_bounded(str(owned), 100)

    def test_config_read_through_a_symlinked_directory(self) -> None:
        # Mirrors the owner's machine: ~/.config/stow-sync is a dir symlink
        # into the dotfiles repo and config.json is a regular file inside.
        repo_dir = self.root / ".dotfiles" / "stow-sync" / ".config" / "stow-sync"
        repo_dir.mkdir(parents=True)
        (repo_dir / "config.json").write_text(
            json.dumps({"version": 1, "repos": [{"path": "~/.dotfiles"}]}), encoding="utf-8"
        )
        cfg = self.root / ".config" / "stow-sync"
        cfg.parent.mkdir(parents=True)
        cfg.symlink_to(repo_dir)
        config = ss.load_config()
        self.assertEqual(len(config["repos"]), 1)

    def test_config_symlink_leaf_inside_home_is_followed(self) -> None:
        real = self.root / "real-config.json"
        real.write_text(json.dumps({"version": 1, "repos": []}), encoding="utf-8")
        cfg = self.root / ".config" / "stow-sync"
        cfg.mkdir(parents=True)
        (cfg / "config.json").symlink_to(real)
        self.assertEqual(ss.load_config()["repos"], [])

    def test_config_symlink_outside_home_is_refused(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"version": 1, "repos": []}')
            outside = handle.name
        self.addCleanup(lambda: os.path.exists(outside) and os.unlink(outside))
        cfg = self.root / ".config" / "stow-sync"
        cfg.mkdir(parents=True)
        (cfg / "config.json").symlink_to(outside)
        with self.assertRaises(ss.CommandError):
            ss.load_config()

    def test_recipe_over_cap_is_refused(self) -> None:
        big = self.root / "recipe.json"
        big.write_text("{" + " " * (ss.MAX_RECIPE_BYTES + 10) + "}", encoding="utf-8")
        with self.assertRaises(ss.CommandError):
            ss.load_setup_recipe_file(str(big))

    # --- argv safety -------------------------------------------------------

    def test_validate_clone_url_allows_and_refuses(self) -> None:
        self.assertEqual(
            ss.validate_clone_url("https://github.com/a/b.git"), "https://github.com/a/b.git"
        )
        self.assertEqual(
            ss.validate_clone_url("git@github.com:a/b.git"), "git@github.com:a/b.git"
        )
        local = str(self.root / "x.git")
        self.assertEqual(ss.validate_clone_url(local), local)
        for bad in (
            "--upload-pack=/evil",
            "-x",
            "https://tok@github.com/a/b.git",
            "https://user:pw@github.com/a/b.git",
            "https://x y/z",
            "ftp://github.com/a/b",
        ):
            with self.assertRaises(ss.CommandError, msg=bad):
                ss.validate_clone_url(bad)

    def test_recipe_rejects_path_outside_home_and_unsafe_url(self) -> None:
        base = {
            "version": 1,
            "repos": [
                {
                    "path": "~/ok",
                    "url": "https://github.com/a/b.git",
                    "packages": "auto",
                    "order": 1,
                }
            ],
        }
        ss.validate_setup_recipe(copy.deepcopy(base))
        outside = copy.deepcopy(base)
        outside["repos"][0]["path"] = "/etc"
        with self.assertRaises(ss.CommandError):
            ss.validate_setup_recipe(outside)
        bad_url = copy.deepcopy(base)
        bad_url["repos"][0]["url"] = "--evil"
        with self.assertRaises(ss.CommandError):
            ss.validate_setup_recipe(bad_url)
        creds = copy.deepcopy(base)
        creds["repos"][0]["url"] = "https://tok@github.com/a/b.git"
        with self.assertRaises(ss.CommandError):
            ss.validate_setup_recipe(creds)

    def test_setup_connect_rejects_a_path_outside_home(self) -> None:
        result = ss.dispatch(
            ["setup-connect", "--url", "https://github.com/a/b.git", "--path", "/etc"],
            None,
            str(self.root / "state"),
        )
        self.assertFalse(result["ok"])
        self.assertIn("inside $HOME", result["error"])

    def test_scrub_credentials_removes_userinfo(self) -> None:
        cleaned = ss.scrub_credentials(
            "fatal: could not read from https://ghp_SECRET@github.com/a/b.git"
        )
        self.assertNotIn("ghp_SECRET", cleaned)
        self.assertIn("https://github.com/a/b.git", cleaned)
        result = subprocess.CompletedProcess(
            [], 1, b"", b"clone https://user:pw@host/x failed"
        )
        self.assertNotIn("user:pw", ss._short_error(result))
        self.assertNotIn("tok@", ss._push_error_text("error: https://tok@host/x"))

    def test_stdin_payload_over_cap_is_refused(self) -> None:
        payload = io.StringIO("x" * (ss.MAX_STDIN_BYTES + 1))
        with patch.object(ss.sys, "stdin", payload):
            with self.assertRaises(ss.CommandError):
                ss.read_stdin_json()


# --------------------------------------------------------------------------
# Unit 15 (fifth VM run) wiring checks
# --------------------------------------------------------------------------


class Unit15SourceTests(unittest.TestCase):
    """README Unit 15 wiring that the pure node tests cannot see."""

    def test_wizard_close_and_setup_mutations_refresh_the_overview(self) -> None:
        # Finding 78: refresh status + backups when Apply/Undo finishes and when
        # the wizard closes, so the Overview is never stale.
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("function refreshAfterSetup()", panel)
        self.assertIn("onClosed: { root.setupOpen = false; root.refreshAfterSetup() }", panel)
        self.assertIn('tag === "setup-undo" || tag === "setup-apply"', panel)
        self.assertIn('tag === "setup-apply" || tag === "setup-undo"', panel)

    def test_undo_failure_is_rendered_outside_error_text(self) -> None:
        # Finding 80: the undo failure survives a status refresh because it lives
        # in flow.undoError and is rendered by the backups view and the Report.
        flow = (ROOT / "SetupFlow.qml").read_text(encoding="utf-8")
        self.assertIn("property string undoError", flow)
        self.assertIn("flow.undoError = String(payload && payload.error", flow)
        backups = (ROOT / "SetupBackups.qml").read_text(encoding="utf-8")
        self.assertIn("Model.setupUndoSummary(root.undoResult)", backups)
        self.assertIn("root.undoError", backups)
        report = (ROOT / "SetupReport.qml").read_text(encoding="utf-8")
        self.assertIn("root.undoError", report)
        step = (ROOT / "SetupStep.qml").read_text(encoding="utf-8")
        self.assertIn("property string undoError", step)
        self.assertIn("undoError: root.undoError", step)
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertIn("undoError: flow.undoError", wizard)

    def test_header_replaces_the_floppy_with_the_undo_glyph(self) -> None:
        # Finding 83: md-undo with the "Undo setup" tooltip, Nerd Font verified.
        header = (ROOT / "Header.qml").read_text(encoding="utf-8")
        self.assertIn('iconText: "\\u{F054C}"', header)
        self.assertIn('tooltipText: "Undo setup"', header)
        self.assertNotIn("\\uf0c7", header)
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("onUndoSetupClicked: root.undoSetupFromHeader()", panel)

    def test_overview_groups_are_one_accordion(self) -> None:
        # Finding 84: one expanded key for the repo lanes and the group cards.
        section = (ROOT / "RepoSection.qml").read_text(encoding="utf-8")
        self.assertIn("property string expandedKey", section)
        self.assertIn("Model.accordionKey(", section)
        self.assertNotIn("expandedGroups", section)
        self.assertNotIn("expandedRepos", section)
        flow = (ROOT / "SetupFlow.qml").read_text(encoding="utf-8")
        self.assertIn("Model.setupAccordionToggle(", flow)
        report = (ROOT / "SetupReport.qml").read_text(encoding="utf-8")
        self.assertIn("Model.setupAccordionToggle(", report)

    def test_scroll_area_ends_above_the_footer(self) -> None:
        # Finding 85: the body is anchored to the footer top, not a computed
        # height that could run under the buttons.
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertIn("anchors.bottom: buttonRow.top", wizard)
        self.assertIn("anchors.bottomMargin: Style.space(12)", wizard)
        self.assertNotIn("inner.height - chrome.height - buttonRow.height", wizard)

    def test_footer_buttons_share_one_height_and_centre(self) -> None:
        # Finding 86: one shared height and one vertical centre for every step.
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertIn(
            "height: Math.max(undoFooterButton.implicitHeight, backFooterButton.implicitHeight, primaryFooterButton.implicitHeight)",
            wizard,
        )
        self.assertEqual(wizard.count("height: buttonRow.height"), 3)
        self.assertEqual(wizard.count("anchors.verticalCenter: parent.verticalCenter"), 3)


class Unit15bSourceTests(unittest.TestCase):
    """Sixth VM run (findings 87, 88, 85) wiring that QML must keep."""

    def test_header_undo_uses_the_panel_decision(self) -> None:
        # Finding 87: Panel called setupWizard.headerUndo(), which SetupWizard
        # never forwarded, so the click threw and nothing appeared. The decision
        # is now the pure Model.headerUndo over the panel's backups.
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("Model.headerUndo(setupWizard.backups)", panel)
        self.assertNotIn("setupWizard.headerUndo", panel)
        # The handler sets the confirm card state, and the overlay opens on it.
        self.assertIn('root.confirmKind = "setup-undo"', panel)
        self.assertIn('root.overlayMode = "confirm"', panel)
        self.assertIn('opened: root.overlayMode !== ""', panel)
        self.assertIn("onUndoSetupClicked: root.undoSetupFromHeader()", panel)
        header = (ROOT / "Header.qml").read_text(encoding="utf-8")
        self.assertIn("onClicked: root.undoSetupClicked()", header)
        # SetupFlow no longer carries a headerUndo the shell forgot to forward.
        flow = (ROOT / "SetupFlow.qml").read_text(encoding="utf-8")
        self.assertNotIn("function headerUndo()", flow)

    def test_header_undo_is_a_labelled_button(self) -> None:
        # Finding 88: a labelled button, not an icon-only glyph.
        header = (ROOT / "Header.qml").read_text(encoding="utf-8")
        self.assertIn('text: "Undo setup"', header)
        self.assertIn('tooltipText: "Undo setup"', header)
        self.assertIn('iconText: "\\u{F054C}"', header)

    def test_report_scroll_area_shows_a_cue(self) -> None:
        # Finding 85: a bottom fade + chevron when more content is below.
        wizard = (ROOT / "SetupWizard.qml").read_text(encoding="utf-8")
        self.assertIn("ScrollHint {", wizard)
        self.assertIn("flick: bodyArea", wizard)
        hint = (ROOT / "ScrollHint.qml").read_text(encoding="utf-8")
        self.assertIn("contentHeight > root.flick.height", hint)
        self.assertIn("Gradient {", hint)


if __name__ == "__main__":
    unittest.main()