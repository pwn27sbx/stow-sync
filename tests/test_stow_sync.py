#!/usr/bin/env python3
"""Unit tests for the Stow Sync backend.

All tests use real ``git`` against throwaway repositories created under a
temporary directory, never the owner's real dotfiles repos. The git
environment is isolated from the host's global config, identity and hooks.
"""

from __future__ import annotations

import errno
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
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


if __name__ == "__main__":
    unittest.main()