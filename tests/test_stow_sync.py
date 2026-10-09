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


if __name__ == "__main__":
    unittest.main()