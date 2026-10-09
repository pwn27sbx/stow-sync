#!/usr/bin/env python3
"""Stow Sync backend helper.

Every invocation prints exactly one JSON object to stdout:

    {"ok": true, ...} or {"ok": false, "error": "<short human text>"}

Unit 1 implements the read-only core: config loading, bounded process
execution, git hardening, the porcelain v2 ``-z`` parser, repo state and the
``status`` command. Mutating commands arrive in later units. ``main()`` wraps
everything so a failure never leaks a traceback to the panel.
"""

from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any

VERSION = "0.1.0"

# Per-stream output cap for a child process; the response as a whole is capped
# at 2 MB by the writer.
MAX_OUTPUT = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Defaults from the handoff README section 4. Stored verbatim (with ``~``);
# they are expanded in memory when a config is loaded.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "repos": [
        {"path": "~/.dotfiles", "target": "~", "packages": "auto"},
        {"path": "~/wallpapers", "target": "~", "packages": ["walls"]},
    ],
    "watch": [
        "~/.config/systemd/user",
        "~/.local/bin",
        "~/.config/*",
    ],
    "ignore": [
        "~/.config/hypr", "~/.config/omarchy",
        "~/.config/systemd/user/*.wants",
        "~/.config/BraveSoftware", "~/.config/chromium", "~/.config/google-chrome*",
        "~/.config/microsoft-edge*", "~/.config/Code", "~/.config/Electron", "~/.config/dconf",
        "~/.config/pulse", "~/.config/libreoffice",
    ],
    "fetch_minutes": 15,
    "refresh_minutes": 5,
    "notify_after_hours": 0,
}


def default_config_path() -> str:
    """Return ``~/.config/stow-sync/config.json`` honoring ``HOME``."""
    return os.path.expanduser(os.path.join("~", ".config", "stow-sync", "config.json"))


def expand_path(value: str) -> str:
    """Expand a leading ``~`` using the current ``HOME``."""
    return os.path.expanduser(value)


def to_tilde(abs_path: str) -> str:
    """Replace the ``HOME`` prefix with ``~`` for display."""
    home = os.path.expanduser("~")
    if abs_path == home:
        return "~"
    prefix = home + os.sep
    if abs_path.startswith(prefix):
        return "~" + abs_path[len(home):]
    return abs_path


def expand_config_paths(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``config`` with ``~`` expanded on every path field."""
    result = copy.deepcopy(config)
    for repo in result.get("repos", []):
        for key in ("path", "target"):
            if isinstance(repo.get(key), str):
                repo[key] = expand_path(repo[key])
    for key in ("watch", "ignore"):
        result[key] = [expand_path(p) if isinstance(p, str) else p for p in result.get(key, [])]
    return result


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load the user config, creating it with defaults when missing.

    An existing file is never modified; it is returned unchanged on disk.
    The returned config has ``~`` expanded on every path field.
    """
    path = expand_path(config_path) if config_path else default_config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    else:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = copy.deepcopy(DEFAULT_CONFIG)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    return expand_config_paths(data)


def _package_ignores_everything(package_path: str) -> bool:
    """True when the package's own ``.stow-local-ignore`` ignores everything.

    The ignore file holds one extended-regex pattern per line; ``.*`` matches
    every name, so such a package is not a Stow package (e.g. ``odd/``).
    """
    ignore_file = os.path.join(package_path, ".stow-local-ignore")
    if not os.path.isfile(ignore_file):
        return False
    try:
        with open(ignore_file, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return False
    for line in lines:
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern == ".*":
            return True
    return False


def detect_packages(repo_path: str) -> list[str]:
    """List top-level directories of ``repo_path`` that are Stow packages.

    Skips dot-directories and any package whose own ``.stow-local-ignore``
    ignores everything.
    """
    try:
        names = sorted(os.listdir(repo_path))
    except OSError:
        return []
    packages: list[str] = []
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(repo_path, name)
        if not os.path.isdir(full):
            continue
        if _package_ignores_everything(full):
            continue
        packages.append(name)
    return packages


def _drain_capped(pipe: Any, sink: list[bytes], max_output: int, overflow: threading.Event) -> None:
    """Read a child pipe to EOF, keeping at most ``max_output`` bytes.

    Draining continues past the cap (discarding) so the child never blocks on
    a full pipe; the overflow flag lets the parent kill the process group.
    """
    kept = 0
    total = 0
    try:
        while True:
            chunk = pipe.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if kept < max_output:
                take = chunk[: max_output - kept]
                sink.append(take)
                kept += len(take)
            if total > max_output:
                overflow.set()
    except (OSError, ValueError):
        pass


def run_bounded(
    argv: list[str],
    timeout: float,
    max_output: int = MAX_OUTPUT,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a child in its own process group with capped output.

    On timeout the whole group is killed and ``subprocess.TimeoutExpired`` is
    raised. On output overflow the group is killed and the returned result's
    stderr notes the truncation with a non-zero return code.
    """
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        start_new_session=True,
    )

    def kill_group() -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()

    overflow = threading.Event()
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    readers = [
        threading.Thread(target=_drain_capped, args=(proc.stdout, out_chunks, max_output, overflow), daemon=True),
        threading.Thread(target=_drain_capped, args=(proc.stderr, err_chunks, max_output, overflow), daemon=True),
    ]
    for thread in readers:
        thread.start()
    if stdin is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def close_pipes() -> None:
        for pipe in (proc.stdout, proc.stderr, proc.stdin):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass

    deadline = time.monotonic() + timeout
    truncated = False
    while True:
        try:
            proc.wait(timeout=0.05)
            break
        except subprocess.TimeoutExpired:
            pass
        if overflow.is_set():
            truncated = True
            kill_group()
            proc.wait()
            break
        if time.monotonic() >= deadline:
            kill_group()
            proc.wait()
            for thread in readers:
                thread.join(timeout=2)
            close_pipes()
            raise subprocess.TimeoutExpired(argv, timeout)
    for thread in readers:
        thread.join(timeout=5)
    close_pipes()

    returncode = proc.returncode
    out = b"".join(out_chunks)
    err = b"".join(err_chunks)
    if truncated:
        note = b"\n[output truncated: process exceeded its output limit and was stopped]"
        err = (err + note).strip()
        if returncode == 0:
            returncode = 1
    return subprocess.CompletedProcess(argv, returncode, out, err)


def git_env() -> dict[str, str]:
    """Environment for every git child: non-interactive and locale-stable."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes"
    env["LC_ALL"] = "C"
    return env


def build_git_argv(repo: str | None, args: list[str]) -> list[str]:
    """Build ``git [-C repo] -c core.hooksPath= -c color.ui=false <args>``."""
    argv = ["git"]
    if repo is not None:
        argv += ["-C", str(repo)]
    argv += ["-c", "core.hooksPath=", "-c", "color.ui=false"]
    argv += list(args)
    return argv


def run_git(
    repo: str | None,
    args: list[str],
    timeout: float = 20,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git with the shared hooks/color/env hardening."""
    return run_bounded(
        build_git_argv(repo, args),
        timeout,
        cwd=str(cwd) if cwd else None,
        env=git_env(),
    )


_STATUS_KIND = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "typechange",
    "U": "unmerged",
    "?": "untracked",
    "!": "ignored",
}


def _kind_for_xy(x: str, y: str) -> str:
    for code in (x, y):
        kind = _STATUS_KIND.get(code)
        if kind:
            return kind
    return "unknown"


def _package_of(path: str) -> str:
    """Package is the first path segment."""
    return path.split("/", 1)[0]


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def parse_porcelain_v2(data: bytes) -> dict[str, Any]:
    """Parse ``git status --porcelain=v2 --branch -z --untracked-files=all``.

    In ``-z`` mode every record is NUL-terminated; a rename record (``2``) has
    its ORIGINAL path as a separate NUL field that is consumed with the record.
    """
    branch = ""
    detached = False
    upstream = ""
    ahead = 0
    behind = 0
    changes: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []

    fields = data.split(b"\x00")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue

        if field.startswith(b"# "):
            header = _decode(field[2:])
            if header.startswith("branch.head "):
                branch = header[len("branch.head "):]
                detached = branch == "(detached)"
            elif header.startswith("branch.upstream "):
                upstream = header[len("branch.upstream "):]
            elif header.startswith("branch.ab "):
                tokens = header[len("branch.ab "):].split()
                if len(tokens) == 2:
                    ahead = int(tokens[0].lstrip("+"))
                    behind = abs(int(tokens[1]))
            continue

        record = field[:1]
        if record == b"?":
            path = _decode(field[2:])
            untracked.append({"path": path, "package": _package_of(path)})
            continue
        if record == b"!":
            continue
        if record == b"1":
            parts = field.split(b" ", 8)
            if len(parts) < 9:
                continue
            xy = _decode(parts[1])
            path = _decode(parts[8])
            changes.append(_change(path, xy, _kind_for_xy(xy[0:1], xy[1:2])))
            continue
        if record == b"2":
            parts = field.split(b" ", 9)
            if len(parts) < 10:
                continue
            xy = _decode(parts[1])
            path = _decode(parts[9])
            if index < len(fields):
                # The original path is a separate NUL field of this record.
                index += 1
            changes.append(_change(path, xy, _kind_for_xy(xy[0:1], xy[1:2])))
            continue
        if record == b"u":
            parts = field.split(b" ", 10)
            if len(parts) < 11:
                continue
            xy = _decode(parts[1])
            path = _decode(parts[10])
            changes.append(_change(path, xy, "unmerged"))
            continue

    return {
        "branch": branch,
        "detached": detached,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "changes": changes,
        "untracked": untracked,
    }


def _change(path: str, xy: str, kind: str) -> dict[str, str]:
    return {
        "path": path,
        "package": _package_of(path),
        "x": xy[0:1] or " ",
        "y": xy[1:2] or " ",
        "kind": kind,
    }


def _git_dir(repo_path: str) -> str | None:
    """Return the repository's git dir, following a ``gitdir:`` pointer file."""
    dot_git = os.path.join(repo_path, ".git")
    if os.path.isdir(dot_git):
        return dot_git
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, "r", encoding="utf-8") as handle:
                content = handle.read().strip()
        except OSError:
            return None
        if content.startswith("gitdir:"):
            target = content[len("gitdir:"):].strip()
            if not os.path.isabs(target):
                target = os.path.join(repo_path, target)
            return os.path.normpath(target)
    return None


def git_status(repo_path: str) -> dict[str, Any]:
    """Read branch/upstream/ahead/behind/changes/untracked for a repo."""
    result = run_git(
        repo_path,
        ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"],
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(_short_error(result))
    return parse_porcelain_v2(result.stdout)


def detect_operation(repo_path: str) -> str | None:
    """Return the in-progress git operation (merge/rebase/cherry-pick) or None."""
    git_dir = _git_dir(repo_path)
    if git_dir is None:
        return None
    if os.path.exists(os.path.join(git_dir, "MERGE_HEAD")):
        return "merge"
    if os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(
        os.path.join(git_dir, "rebase-apply")
    ):
        return "rebase"
    if os.path.exists(os.path.join(git_dir, "CHERRY_PICK_HEAD")):
        return "cherry-pick"
    return None


# state precedence, first match wins (README section 5.1)
STATE_PRECEDENCE = (
    "missing",
    "operation",
    "detached",
    "no-upstream",
    "diverged",
    "dirty",
    "ahead",
    "behind",
    "clean",
)


def compute_state(
    *,
    exists: bool,
    operation: str | None,
    detached: bool,
    upstream: str,
    ahead: int,
    behind: int,
    changes: list[Any],
    untracked: list[Any],
) -> str:
    """Apply the README section 5.1 state precedence, first match wins."""
    if not exists:
        return "missing"
    if operation:
        return "operation"
    if detached:
        return "detached"
    if not upstream:
        return "no-upstream"
    if ahead > 0 and behind > 0:
        return "diverged"
    if changes or untracked:
        return "dirty"
    if ahead > 0:
        return "ahead"
    if behind > 0:
        return "behind"
    return "clean"


# Severity for the summary's "worst" state.
_STATE_RANK = {
    "clean": 0,
    "behind": 1,
    "ahead": 2,
    "no-upstream": 3,
    "dirty": 4,
    "detached": 5,
    "diverged": 6,
    "operation": 7,
    "missing": 8,
}


def _short_error(result: subprocess.CompletedProcess[bytes]) -> str:
    text = result.stderr or result.stdout or b""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = " ".join(str(text).split())
    if not text:
        return "git command failed"
    return text[:300]


def _fetch_origin(repo_path: str) -> tuple[str | None, str | None]:
    """Run ``git fetch --prune origin`` (120 s). Returns (fetch_error, last_fetch)."""
    try:
        result = run_git(repo_path, ["fetch", "--prune", "origin"], timeout=120)
    except subprocess.TimeoutExpired:
        return ("git fetch timed out after 120s", None)
    if result.returncode != 0:
        return (_short_error(result), None)
    return (None, datetime.now().astimezone().isoformat(timespec="seconds"))


def _package_placeholders(repo_path: str) -> list[dict[str, Any]]:
    """Package entries with Unit 1 placeholder health; Unit 2 fills these in."""
    return [
        {"name": name, "health": "ok", "pending_links": [], "conflicts": [], "dangling": []}
        for name in detect_packages(repo_path)
    ]


def _repo_status(repo_cfg: dict[str, Any], do_fetch: bool = False) -> dict[str, Any]:
    raw_path = repo_cfg.get("path", "")
    path = expand_path(raw_path) if raw_path else ""
    entry: dict[str, Any] = {
        "path": to_tilde(path) if path else "",
        "exists": False,
        "branch": "",
        "upstream": "",
        "ahead": 0,
        "behind": 0,
        "state": "missing",
        "changes": [],
        "untracked": [],
        "packages": [],
        "operation": None,
        "last_fetch": None,
        "fetch_error": None,
    }
    if not path or _git_dir(path) is None:
        return entry
    entry["exists"] = True
    if do_fetch:
        entry["fetch_error"], entry["last_fetch"] = _fetch_origin(path)
    try:
        status = git_status(path)
    except Exception as exc:  # noqa: BLE001 - one bad repo must not fail the command
        entry["fetch_error"] = entry["fetch_error"] or (str(exc) or "git status failed")
        entry["state"] = "missing"
        return entry
    operation = detect_operation(path)
    entry.update(
        {
            "branch": status["branch"],
            "upstream": status["upstream"],
            "ahead": status["ahead"],
            "behind": status["behind"],
            "changes": status["changes"],
            "untracked": status["untracked"],
            "operation": operation,
            "packages": _package_placeholders(path),
            "state": compute_state(
                exists=True,
                operation=operation,
                detached=status["detached"],
                upstream=status["upstream"],
                ahead=status["ahead"],
                behind=status["behind"],
                changes=status["changes"],
                untracked=status["untracked"],
            ),
        }
    )
    return entry


def compute_summary(repos: list[dict[str, Any]]) -> dict[str, Any]:
    """Worst repo state plus the count of actionable items (Unit 1 subset)."""
    if not repos:
        return {"state": "clean", "count": 0}
    worst = max(repos, key=lambda repo: _STATE_RANK.get(repo.get("state", "clean"), 0))
    count = 0
    for repo in repos:
        count += len(repo.get("changes", []))
        count += len(repo.get("untracked", []))
        if repo.get("ahead", 0) > 0:
            count += 1
        if repo.get("behind", 0) > 0:
            count += 1
    return {"state": worst["state"], "count": count}


def cmd_status(args: list[str], config_path: str | None = None) -> dict[str, Any]:
    """Read-only status for every configured repo (``--fetch`` optional)."""
    do_fetch = "--fetch" in args
    config = load_config(config_path)
    repos = [_repo_status(repo_cfg, do_fetch) for repo_cfg in config.get("repos", [])]
    return {
        "ok": True,
        "repos": repos,
        "summary": compute_summary(repos),
        "candidates": [],
    }


def cmd_version(_args: list[str], _config_path: str | None = None) -> dict[str, Any]:
    """Report the backend version."""
    return {"ok": True, "version": VERSION}


COMMANDS = {
    "version": cmd_version,
    "status": cmd_status,
}


def extract_global_config(argv: list[str]) -> tuple[str | None, list[str]]:
    """Pull the global ``--config <path>`` flag out of an argument vector.

    Returns ``(config_path_or_None, remaining_args)``. Both ``--config PATH``
    and ``--config=PATH`` are accepted.
    """
    config_path: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--config":
            if index + 1 < len(argv):
                config_path = argv[index + 1]
                index += 2
                continue
            index += 1
            continue
        if token.startswith("--config="):
            config_path = token[len("--config="):]
            index += 1
            continue
        rest.append(token)
        index += 1
    return config_path, rest


def dispatch(argv: list[str], config_path: str | None = None) -> dict[str, Any]:
    """Route one already-parsed argument vector to its command handler."""
    name = argv[0] if argv else ""
    handler = COMMANDS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown command: " + (name or "<none>")}
    return handler(argv[1:], config_path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        config_path, rest = extract_global_config(args)
        result = dispatch(rest, config_path)
    except Exception as exc:  # noqa: BLE001 - CLI must never print a traceback to QML
        result = {"ok": False, "error": (str(exc) or exc.__class__.__name__)}
    text = json.dumps(result, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        result = {"ok": False, "error": "response exceeds the 2 MB limit"}
        text = json.dumps(result, ensure_ascii=False)
    sys.stdout.write(text + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
