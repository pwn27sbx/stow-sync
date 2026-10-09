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
import errno
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "0.1.0"

# Per-stream output cap for a child process; the response as a whole is capped
# at 2 MB by the writer.
MAX_OUTPUT = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Diff command caps (README section 5): 400 lines or 32 KB, whichever first.
DIFF_MAX_LINES = 400
DIFF_MAX_BYTES = 32 * 1024


class CommandError(Exception):
    """A user-facing command failure; carried to ``ok: false, error``."""


def _shorten(text: str, limit: int = 300) -> str:
    """Collapse whitespace and cap a human-readable error string."""
    collapsed = " ".join(str(text).split())
    return collapsed[:limit]


# Userinfo inside a scheme:// URL (``user:pass@`` or ``token@``). The
# conventional SSH username ``git@`` is not a credential and is preserved.
_CREDENTIAL_URL = re.compile(
    r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<userinfo>[^@/]+)@(?P<rest>.+)$"
)


def sanitize_url(url: Any) -> str:
    """Strip embedded credentials from a git URL for display (README Unit 4d).

    ``https://user:token@host/x`` and ``https://token@host/x`` become
    ``https://host/x``. A bare ``git@host:path`` (scp form) and
    ``ssh://git@host/x`` keep their conventional SSH username.
    """
    text = "" if url is None else str(url)
    match = _CREDENTIAL_URL.match(text)
    if not match:
        return text
    userinfo = match.group("userinfo")
    if ":" in userinfo or userinfo != "git":
        return match.group("scheme") + match.group("rest")
    return text


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


# --------------------------------------------------------------------------
# State dir and first-run baseline (README section 5.3b items 2-6)
# --------------------------------------------------------------------------

BASELINE_VERSION = 1
BASELINE_FILENAME = "baseline.json"


def resolve_state_dir(explicit: str | None = None) -> str:
    """Resolve the plugin state dir (README section 4 / 5.3b).

    Precedence: an explicit ``--state-dir`` value, then the
    ``STOW_SYNC_STATE_DIR`` environment variable, then
    ``~/.local/state/stow-sync`` (honoring ``HOME``).
    """
    if explicit:
        return expand_path(explicit)
    env_value = os.environ.get("STOW_SYNC_STATE_DIR")
    if env_value:
        return expand_path(env_value)
    return os.path.expanduser(os.path.join("~", ".local", "state", "stow-sync"))


def baseline_path(state_dir: str) -> str:
    """Path of the baseline file inside ``state_dir``."""
    return os.path.join(state_dir, BASELINE_FILENAME)


def _baseline_error(prefix: str, exc: BaseException) -> str:
    detail = str(exc) or exc.__class__.__name__
    return (prefix + ": " + detail)[:200]


def _write_json_atomic(path: str, data: dict[str, Any], mode: int = 0o600) -> None:
    """Write JSON to ``path`` atomically with a fixed permission mode."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".baseline-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_baseline(state_dir: str, paths: list[str]) -> str:
    """Write a fresh baseline of ``paths`` and return its ``created`` stamp."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data = {
        "version": BASELINE_VERSION,
        "created": created,
        "paths": sorted(str(path) for path in paths),
    }
    os.makedirs(state_dir, 0o700, exist_ok=True)
    _write_json_atomic(baseline_path(state_dir), data, 0o600)
    return created


def load_baseline(
    state_dir: str,
    candidate_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Load the baseline, creating it once with the current candidates.

    Returns ``{"paths": set[str], "created": str | None, "error": str | None}``.
    A missing file is created atomically (dir 0700, file 0600) containing the
    supplied candidate paths. Any read/write failure sets ``error`` and yields
    an empty path set; it never raises (status must stay ``ok: true``).
    """
    result: dict[str, Any] = {"paths": set(), "created": None, "error": None}
    path = baseline_path(state_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            raw_paths = data.get("paths", []) if isinstance(data, dict) else []
            result["paths"] = {str(p) for p in raw_paths if isinstance(p, str)}
            result["created"] = data.get("created") if isinstance(data, dict) else None
        except (OSError, ValueError, TypeError) as exc:
            result["error"] = _baseline_error("baseline read failed", exc)
            result["paths"] = set()
        return result

    try:
        created = write_baseline(state_dir, list(candidate_paths or []))
    except OSError as exc:
        result["error"] = _baseline_error("baseline write failed", exc)
        return result
    result["paths"] = {str(path) for path in (candidate_paths or [])}
    result["created"] = created
    return result


# --------------------------------------------------------------------------
# Publish stamps (README section 8, Unit 4d): the last successful push time
# per repo, kept in the plugin's own state dir.
# --------------------------------------------------------------------------

PUBLISH_FILENAME = "publish.json"


def publish_path(state_dir: str) -> str:
    """Path of the publish stamp file inside ``state_dir``."""
    return os.path.join(state_dir, PUBLISH_FILENAME)


def load_publish_times(state_dir: str) -> dict[str, str]:
    """Read ``{repo path: iso}`` from ``publish.json``; ``{}`` when unreadable."""
    try:
        with open(publish_path(state_dir), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def record_publish(state_dir: str, repo_path: str, when: str | None = None) -> str:
    """Refresh the last successful publish stamp for ``repo_path`` (0600).

    ``status`` stays read-only; only a successful ``push`` calls this.
    """
    stamp = when or datetime.now().astimezone().isoformat(timespec="seconds")
    times = load_publish_times(state_dir)
    times[os.path.normpath(repo_path)] = stamp
    os.makedirs(state_dir, 0o700, exist_ok=True)
    _write_json_atomic(publish_path(state_dir), times, 0o600)
    return stamp


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
    stdin: str | None = None,
    max_output: int = MAX_OUTPUT,
) -> subprocess.CompletedProcess[bytes]:
    """Run git with the shared hooks/color/env hardening.

    ``stdin`` is forwarded verbatim (used for ``git commit -F -``), and
    ``max_output`` overrides the per-stream cap.
    """
    return run_bounded(
        build_git_argv(repo, args),
        timeout,
        max_output=max_output,
        cwd=str(cwd) if cwd else None,
        env=git_env(),
        stdin=stdin,
    )


def resolve_repo(config: dict[str, Any], repo_arg: str | None) -> dict[str, Any]:
    """Match ``--repo R`` against the configured ``repos[].path`` (expanded).

    Commands may only touch configured repos. Raises :class:`CommandError`
    when the argument is missing or does not name a configured repo.
    """
    if not repo_arg:
        raise CommandError("missing --repo")
    wanted = os.path.normpath(expand_path(repo_arg))
    for repo in config.get("repos", []):
        if not isinstance(repo, dict):
            continue
        path = repo.get("path", "")
        if not isinstance(path, str) or not path:
            continue
        if os.path.normpath(expand_path(path)) == wanted:
            found = dict(repo)
            found["path"] = os.path.normpath(expand_path(path))
            return found
    raise CommandError("unknown repo: " + str(repo_arg))


def validate_repo_relpath(path: Any) -> str:
    """Return a safe repo-relative path, or raise :class:`CommandError`.

    Rejects non-strings, empty values, NUL bytes, absolute paths, ``~``
    prefixes, and any ``..`` component (README section 5.2: absolute, ``..``,
    NUL, outside the repo).
    """
    if not isinstance(path, str) or not path:
        raise CommandError("empty path")
    if "\x00" in path:
        raise CommandError("path contains a NUL byte")
    if path.startswith("~"):
        raise CommandError("path must be repo-relative: " + path)
    if os.path.isabs(path):
        raise CommandError("absolute path not allowed: " + path)
    normalized = path.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise CommandError("path escapes the repo: " + path)
    clean = os.path.normpath(normalized)
    if clean in (".", "") or clean == ".." or clean.startswith("../"):
        raise CommandError("path escapes the repo: " + path)
    return clean


def opt_value(args: list[str], flag: str) -> str | None:
    """Return the value of ``--flag VALUE`` or ``--flag=VALUE`` in ``args``."""
    for index, token in enumerate(args):
        if token == flag and index + 1 < len(args):
            return args[index + 1]
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return None



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


# Severity for the summary's "worst" state. Repo states keep their README
# section 5.1 relative order; package-derived states (README section 5.1:
# conflicts -> "conflict", plus "dangling" and "pending") are interleaved.
_STATE_RANK = {
    "clean": 0,
    "behind": 10,
    "ahead": 20,
    "pending": 25,
    "no-upstream": 30,
    "dirty": 40,
    "detached": 50,
    "dangling": 55,
    "diverged": 60,
    "conflict": 65,
    "operation": 70,
    "missing": 80,
}

# Package ``health`` value -> summary state name.
_HEALTH_STATE = {
    "conflicts": "conflict",
    "dangling": "dangling",
    "pending": "pending",
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


# --------------------------------------------------------------------------
# Stow health (README section 5.1) and candidates (README section 5.3)
# --------------------------------------------------------------------------

# A candidate whose recursive size exceeds this is skipped.
MAX_CANDIDATE_SIZE = 50 * 1024 * 1024

# Compiled-executable magic numbers; a regular file starting with one of these
# is never a candidate (README section 5.3b item 1).
ELF_MAGIC = b"\x7fELF"
MACHO_MAGICS = frozenset(
    (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
    )
)

_CONFLICT_LINE = re.compile(
    r"cannot stow (?P<source>.+?) over existing target (?P<target>.+?) since"
)


def stow_env() -> dict[str, str]:
    """Environment for every stow child: stable locale, inherited ``HOME``."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    return env


def stow_dry_run(
    repo_dir: str,
    target_dir: str,
    package: str,
    timeout: float = 20,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``stow -n -v -d <repo> -t <target> <package>``.

    Stow writes all diagnostics to stderr; stdout stays empty.
    """
    argv = [
        "stow",
        "-n",
        "-v",
        "-d",
        str(repo_dir),
        "-t",
        str(target_dir),
        str(package),
    ]
    return run_bounded(argv, timeout, env=stow_env())


def stow_real(
    repo_dir: str,
    target_dir: str,
    package: str,
    timeout: float = 30,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``stow -v -d <repo> -t <target> <package>`` (mutating)."""
    argv = [
        "stow",
        "-v",
        "-d",
        str(repo_dir),
        "-t",
        str(target_dir),
        str(package),
    ]
    return run_bounded(argv, timeout, env=stow_env())


def parse_pending_links(text: str, target_dir: str) -> list[dict[str, str]]:
    """Parse ``LINK: <target> => <source>`` lines from a stow dry run.

    The target path is relative to ``target_dir``; the source path is a symlink
    target relative to the directory that holds the link (that is how stow
    renders it), so it is resolved against ``dirname(target)``.
    """
    links: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("LINK: "):
            continue
        body = line[len("LINK: "):]
        if " => " not in body:
            continue
        target_rel, source_rel = body.split(" => ", 1)
        target_abs = os.path.normpath(os.path.join(target_dir, target_rel.strip()))
        source_abs = os.path.normpath(
            os.path.join(os.path.dirname(target_abs), source_rel.strip())
        )
        links.append({"target": to_tilde(target_abs), "source": to_tilde(source_abs)})
    return links


def parse_conflicts(text: str, target_dir: str) -> list[dict[str, str]]:
    """Parse the ``would cause conflicts`` block from a stow dry run.

    Both the source and the target in ``cannot stow X over existing target Y``
    are rendered relative to ``target_dir``.
    """
    conflicts: list[dict[str, str]] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("WARNING! stowing") and "would cause conflicts" in line:
            in_block = True
            continue
        if in_block and line.strip() == "All operations aborted.":
            in_block = False
            continue
        if not in_block:
            continue
        stripped = line.strip()
        if not stripped.startswith("* "):
            continue
        message = stripped[2:]
        match = _CONFLICT_LINE.search(message)
        if not match:
            continue
        source_abs = _resolve_under(target_dir, match.group("source"))
        target_abs = _resolve_under(target_dir, match.group("target"))
        conflicts.append(
            {
                "target": to_tilde(target_abs),
                "source": to_tilde(source_abs),
                "message": message,
            }
        )
    return conflicts


def _resolve_under(base: str, rel: str) -> str:
    return os.path.normpath(os.path.join(base, rel))


# A stow ``-v`` line is ``ACTION: body`` (LINK, UNLINK, MKDIR, RMDIR, ...).
_STOW_ACTION_LINE = re.compile(r"^(?P<action>[A-Z]+): (?P<body>.*)$")


def parse_stow_actions(text: str, target_dir: str) -> list[dict[str, str]]:
    """Parse ``stow -v`` output into an ``actions[]`` list.

    ``LINK`` lines carry both ``target`` and ``source`` (both ``~``-relative);
    every other action carries only ``target``.
    """
    actions: list[dict[str, str]] = []
    for line in text.splitlines():
        match = _STOW_ACTION_LINE.match(line)
        if not match:
            continue
        name = match.group("action")
        if name == "WARNING":
            continue
        body = match.group("body")
        if name == "LINK" and " => " in body:
            target_rel, source_rel = body.split(" => ", 1)
            target_abs = os.path.normpath(os.path.join(target_dir, target_rel.strip()))
            source_abs = os.path.normpath(
                os.path.join(os.path.dirname(target_abs), source_rel.strip())
            )
            actions.append(
                {"action": "LINK", "target": to_tilde(target_abs), "source": to_tilde(source_abs)}
            )
        else:
            target_abs = os.path.normpath(os.path.join(target_dir, body.strip()))
            actions.append({"action": name, "target": to_tilde(target_abs)})
    return actions


def validate_package_name(name: Any) -> str:
    """Return a safe stow package name, or raise :class:`CommandError`."""
    if not isinstance(name, str) or not name:
        raise CommandError("missing package")
    if "/" in name or "\\" in name or ".." in name or name.startswith("~"):
        raise CommandError("invalid package name: " + name)
    return name


def _under(path: str, base: str) -> bool:
    """True when ``path`` is ``base`` or lies inside it (lexically)."""
    path = os.path.normpath(path)
    base = os.path.normpath(base)
    return path == base or path.startswith(base + os.sep)


def _any_under(path: str, bases: list[str]) -> bool:
    return any(_under(path, base) for base in bases)


def _package_target_dirs(repo_dir: str, target_dir: str, package: str) -> set[str]:
    """Target directories the package maps a regular file into.

    Derived from the package's source tree: the parent under ``target_dir`` of
    every regular file the package would link.
    """
    pkg_root = os.path.join(repo_dir, package)
    parents: set[str] = set()
    if not os.path.isdir(pkg_root):
        return parents
    for dirpath, _dirnames, filenames in os.walk(pkg_root):
        for name in filenames:
            src = os.path.join(dirpath, name)
            if os.path.islink(src) or not os.path.isfile(src):
                continue
            rel = os.path.relpath(src, pkg_root)
            parents.add(os.path.dirname(os.path.join(target_dir, rel)))
    return parents


def scan_dangling(repo_dir: str, target_dir: str, package: str) -> list[dict[str, str]]:
    """Depth-1 symlinks into ``repo_dir`` whose source no longer exists.

    Stow's own dry run says nothing about a broken link, so this is an explicit
    filesystem scan of every target directory the package maps into.
    """
    repo_real = os.path.realpath(repo_dir)
    dangling: list[dict[str, str]] = []
    for parent in sorted(_package_target_dirs(repo_dir, target_dir, package)):
        if not os.path.isdir(parent):
            continue
        try:
            names = sorted(os.listdir(parent))
        except OSError:
            continue
        for name in names:
            entry = os.path.join(parent, name)
            if not os.path.islink(entry) or os.path.exists(entry):
                continue
            real = os.path.realpath(entry)
            if not _under(real, repo_real):
                continue
            dangling.append({"target": to_tilde(entry), "source": to_tilde(real)})
    return dangling


def package_health(
    repo_dir: str,
    target_dir: str,
    package: str,
    timeout: float = 20,
) -> dict[str, Any]:
    """Health of one package: pending links, conflicts and dangling links."""
    result = stow_dry_run(repo_dir, target_dir, package, timeout)
    text = _decode(result.stderr)
    pending = parse_pending_links(text, target_dir)
    conflicts = parse_conflicts(text, target_dir)
    dangling = scan_dangling(repo_dir, target_dir, package)
    health = "ok"
    if conflicts:
        health = "conflicts"
    elif dangling:
        health = "dangling"
    elif pending:
        health = "pending"
    return {
        "name": package,
        "health": health,
        "pending_links": pending,
        "conflicts": conflicts,
        "dangling": dangling,
    }


def _package_health_safe(repo_path: str, target_dir: str, name: str) -> dict[str, Any]:
    """``package_health`` that never lets one bad package fail the whole status."""
    try:
        return package_health(repo_path, target_dir, name)
    except Exception as exc:  # noqa: BLE001 - status must stay JSON-shaped
        return {
            "name": name,
            "health": "ok",
            "pending_links": [],
            "conflicts": [],
            "dangling": [],
            "error": (str(exc) or "stow failed")[:200],
        }


def _has_glob(value: str) -> bool:
    return any(char in value for char in "*?[")


def _candidate_size(path: str) -> int:
    """Size in bytes; recursive for directories, never following subdir links.

    The walk stops as soon as the running total exceeds ``MAX_CANDIDATE_SIZE``:
    an over-cap directory is discarded either way, and walking a multi-gigabyte
    tree (e.g. a browser profile) in full made ``status --short`` miss its
    prompt budget. The returned value for an over-cap directory is therefore a
    lower bound greater than the cap, which is all the caller needs.
    """
    if os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    if os.path.isdir(path):
        total = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
                if total > MAX_CANDIDATE_SIZE:
                    return total
        return total
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _is_ignored(path: str, patterns: list[str]) -> bool:
    tilde_path = to_tilde(path)
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        if fnmatch.fnmatch(tilde_path, to_tilde(pattern)) or fnmatch.fnmatch(path, pattern):
            return True
    return False


def _inside_stowed_dir(path: str, repo_reals: list[str]) -> bool:
    """True when the path resolves into a repo or an ancestor links into one."""
    if _any_under(os.path.realpath(path), repo_reals):
        return True
    parent = os.path.dirname(path)
    while parent and parent != os.path.dirname(parent):
        if os.path.islink(parent) and _any_under(os.path.realpath(parent), repo_reals):
            return True
        parent = os.path.dirname(parent)
    return False


def suggest_package(path: str, repo_reals: list[str]) -> str:
    """Suggest a package for a candidate (README section 5.3).

    A directory candidate (e.g. ``~/.config/stow-sync``) suggests its own
    lowercased basename: the sibling rule only helps a regular file that a
    package already stows next to it, and scanning ``~/.config`` would
    otherwise hijack every directory with whatever stowed app sorts first
    (``cava``). A regular file keeps the sibling rule, then falls back to its
    parent's basename (``user`` -> ``systemd``).
    """
    if os.path.isdir(path):
        base = os.path.basename(path)
    else:
        parent = os.path.dirname(path)
        try:
            siblings = sorted(os.listdir(parent))
        except OSError:
            siblings = []
        for name in siblings:
            sibling = os.path.join(parent, name)
            if sibling == path or not os.path.islink(sibling):
                continue
            real = os.path.realpath(sibling)
            for repo in repo_reals:
                if _under(real, repo):
                    segment = os.path.relpath(real, repo).split(os.sep, 1)[0]
                    if segment and segment != "..":
                        return segment
        base = os.path.basename(parent)
    base = base.lower()
    if base == "user":
        return "systemd"
    return base


def is_compiled_binary(path: str) -> bool:
    """True when ``path`` is a regular file starting with ELF/Mach-O magic.

    Reads at most 4 bytes through ``O_NOFOLLOW`` (symlinks, sockets, FIFOs and
    unreadable files return False) and never raises.
    """
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return False
    except OSError:
        return False
    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        head = os.read(fd, 4)
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    return head == ELF_MAGIC or head in MACHO_MAGICS


def _build_candidate(
    path: str,
    group: str,
    repo_reals: list[str],
    ignore_patterns: list[str],
) -> dict[str, Any] | None:
    """Return a candidate dict, or None when the path must be skipped."""
    if os.path.islink(path):
        if not os.path.exists(path):
            return None  # broken link
        if _any_under(os.path.realpath(path), repo_reals):
            return None  # already stowed into a configured repo
    if _inside_stowed_dir(path, repo_reals):
        return None
    if not (os.path.islink(path) or os.path.isfile(path) or os.path.isdir(path)):
        return None  # socket / FIFO / device
    if is_compiled_binary(path):
        return None  # compiled executable, never an owner-made config
    if _is_ignored(path, ignore_patterns):
        return None
    size = _candidate_size(path)
    if size > MAX_CANDIDATE_SIZE:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return {
        "path": to_tilde(path),
        "type": "dir" if os.path.isdir(path) else "file",
        "size": size,
        "mtime": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"),
        "group": group,
        "suggested_package": suggest_package(path, repo_reals),
    }


def compute_candidates(
    config: dict[str, Any],
    baseline_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Top-level candidate list from the config's ``watch`` entries.

    A plain directory contributes its direct children as ``watched``; a glob
    entry contributes each match as ``other``. Depth is always 1. Every
    candidate carries ``known`` (its path is in ``baseline_paths``).
    """
    baseline = baseline_paths or set()
    repo_reals = [
        os.path.realpath(expand_path(repo.get("path", "")))
        for repo in config.get("repos", [])
        if isinstance(repo, dict) and repo.get("path")
    ]
    ignore_patterns = [p for p in config.get("ignore", []) if isinstance(p, str)]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in config.get("watch", []):
        if not isinstance(entry, str):
            continue
        watch_path = expand_path(entry)
        paths: list[tuple[str, str]] = []
        if _has_glob(watch_path):
            paths = [(match, "other") for match in sorted(glob.glob(watch_path))]
        else:
            if not os.path.isdir(watch_path):
                continue
            try:
                names = sorted(os.listdir(watch_path))
            except OSError:
                continue
            paths = [(os.path.join(watch_path, name), "watched") for name in names]
        for raw_path, group in paths:
            norm = os.path.normpath(raw_path)
            if norm in seen:
                continue
            seen.add(norm)
            candidate = _build_candidate(norm, group, repo_reals, ignore_patterns)
            if candidate is not None:
                candidate["known"] = candidate["path"] in baseline
                candidates.append(candidate)
    return candidates


def compute_badge(candidates: list[dict[str, Any]]) -> int:
    """Badge count: number of candidates that are not in the baseline.

    README section 5.3b item 4: the badge counts only ``known: false``
    candidates, regardless of group.
    """
    return sum(1 for candidate in candidates if not candidate.get("known"))



# Bounded walk of a package's source tree so a pathological package can never
# stall ``status`` (README Unit 4d ``stowed_files``).
MAX_STOWED_FILE_SCAN = 20000


def package_file_count(repo_path: str, package: str) -> int:
    """Number of regular source files a package would link (bounded)."""
    if not package:
        return 0
    pkg_root = os.path.join(repo_path, package)
    if not os.path.isdir(pkg_root):
        return 0
    count = 0
    for dirpath, _dirnames, filenames in os.walk(pkg_root):
        for name in filenames:
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            count += 1
            if count >= MAX_STOWED_FILE_SCAN:
                return count
    return count


def _git_output(repo_path: str, args: list[str], timeout: float = 20) -> str | None:
    """Run git and return decoded stdout, or ``None`` on any failure."""
    try:
        result = run_git(repo_path, args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return _decode(result.stdout)


# Cap on the incoming commit list (README Unit 4d overview "Incoming" group).
INCOMING_COMMITS_LIMIT = 20


def repo_info(repo_path: str, upstream: str) -> dict[str, Any]:
    """Remote URL, HEAD metadata and the bounded incoming commit list.

    All reads are read-only and best-effort: a fresh repo with no commits, or
    no origin, yields empty values rather than an error.
    """
    info: dict[str, Any] = {
        "remote_url": "",
        "head": "",
        "head_subject": "",
        "head_time": None,
        "incoming_commits": [],
    }
    remote = _git_output(repo_path, ["remote", "get-url", "origin"])
    if remote is not None:
        info["remote_url"] = sanitize_url(remote.strip())
    log = _git_output(repo_path, ["log", "-1", "--pretty=%h%x1f%s%x1f%cI"])
    if log:
        parts = log.rstrip("\n").split("\x1f")
        if len(parts) >= 3:
            info["head"] = parts[0]
            info["head_subject"] = parts[1]
            info["head_time"] = parts[2] if parts[2] else None
    if upstream:
        incoming = _git_output(
            repo_path,
            ["log", f"--max-count={INCOMING_COMMITS_LIMIT}", "--pretty=%h%x1f%s", "HEAD.." + upstream],
        )
        for line in (incoming or "").splitlines():
            if not line:
                continue
            tokens = line.split("\x1f", 1)
            if len(tokens) == 2:
                info["incoming_commits"].append({"hash": tokens[0], "subject": tokens[1]})
    return info


def _repo_status(
    repo_cfg: dict[str, Any],
    do_fetch: bool = False,
    publish_times: dict[str, str] | None = None,
) -> dict[str, Any]:
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
        "remote_url": "",
        "head": "",
        "head_subject": "",
        "head_time": None,
        "incoming_commits": [],
        "stowed_packages": 0,
        "stowed_files": 0,
        "last_publish": None,
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
    packages_cfg = repo_cfg.get("packages", "auto")
    if packages_cfg == "auto":
        package_names = detect_packages(path)
    elif isinstance(packages_cfg, list):
        package_names = [str(name) for name in packages_cfg]
    else:
        package_names = []
    target_dir = expand_path(repo_cfg.get("target", "~") or "~")
    entry.update(
        {
            "branch": status["branch"],
            "upstream": status["upstream"],
            "ahead": status["ahead"],
            "behind": status["behind"],
            "changes": status["changes"],
            "untracked": status["untracked"],
            "operation": operation,
            "packages": [
                _package_health_safe(path, target_dir, name) for name in package_names
            ],
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
    info = repo_info(path, status["upstream"])
    healthy = [p for p in entry["packages"] if str(p.get("health", "ok")) == "ok"]
    entry.update(
        {
            "remote_url": info["remote_url"],
            "head": info["head"],
            "head_subject": info["head_subject"],
            "head_time": info["head_time"],
            "incoming_commits": info["incoming_commits"],
            "stowed_packages": len(healthy),
            "stowed_files": sum(
                package_file_count(path, str(p.get("name", ""))) for p in healthy
            ),
            "last_publish": (publish_times or {}).get(os.path.normpath(path)),
        }
    )
    return entry


def compute_summary(repos: list[dict[str, Any]], badge_count: int = 0) -> dict[str, Any]:
    """Worst repo/package state plus the count of actionable items.

    ``count`` = changes + untracked + (ahead>0) + (behind>0) + pending_links +
    conflicts + dangling + badge_count (README section 5.1).
    """
    states: list[str] = []
    count = 0
    for repo in repos:
        states.append(repo.get("state", "clean"))
        count += len(repo.get("changes", []))
        count += len(repo.get("untracked", []))
        if repo.get("ahead", 0) > 0:
            count += 1
        if repo.get("behind", 0) > 0:
            count += 1
        for package in repo.get("packages", []):
            count += len(package.get("pending_links", []))
            count += len(package.get("conflicts", []))
            count += len(package.get("dangling", []))
            mapped = _HEALTH_STATE.get(package.get("health", "ok"))
            if mapped:
                states.append(mapped)
    count += badge_count
    if not states:
        return {"state": "clean", "count": count}
    worst = max(states, key=lambda state: _STATE_RANK.get(state, 0))
    return {"state": worst, "count": count}


def cmd_status(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read-only status for every configured repo (``--fetch`` optional).

    The only write ``status`` may do is the first-run baseline, and only to the
    plugin's own state dir (README section 5.3b item 2).
    """
    do_fetch = "--fetch" in args
    config = load_config(config_path)
    state = resolve_state_dir(state_dir)
    publish_times = load_publish_times(state)
    repos = [
        _repo_status(repo_cfg, do_fetch, publish_times)
        for repo_cfg in config.get("repos", [])
    ]
    candidates = compute_candidates(config)
    baseline = load_baseline(
        state,
        [candidate["path"] for candidate in candidates],
    )
    known = baseline["paths"]
    for candidate in candidates:
        candidate["known"] = candidate["path"] in known
    badge_count = compute_badge(candidates)
    return {
        "ok": True,
        "repos": repos,
        "summary": compute_summary(repos, badge_count),
        "candidates": candidates,
        "baseline_error": baseline["error"],
    }


def cmd_baseline(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Re-snapshot every current candidate as known (``--dry-run`` support)."""
    dry_run = "--dry-run" in args
    config = load_config(config_path)
    candidates = compute_candidates(config)
    paths = sorted(candidate["path"] for candidate in candidates)
    if dry_run:
        return {"ok": True, "dry_run": True, "paths": len(paths), "created": None}
    try:
        created = write_baseline(resolve_state_dir(state_dir), paths)
    except OSError as exc:
        return {"ok": False, "error": _baseline_error("baseline write failed", exc)}
    return {"ok": True, "dry_run": False, "paths": len(paths), "created": created}


def cmd_version(
    _args: list[str],
    _config_path: str | None = None,
    _state_dir: str | None = None,
) -> dict[str, Any]:
    """Report the backend version."""
    return {"ok": True, "version": VERSION}


# --------------------------------------------------------------------------
# diff (README section 5, read-only)
# --------------------------------------------------------------------------


def _cap_diff(text: str) -> tuple[str, bool]:
    """Cap a diff at ``DIFF_MAX_LINES`` or ``DIFF_MAX_BYTES``, whichever first."""
    truncated = False
    lines = text.splitlines(keepends=True)
    if len(lines) > DIFF_MAX_LINES:
        text = "".join(lines[:DIFF_MAX_LINES])
        truncated = True
    data = text.encode("utf-8")
    if len(data) > DIFF_MAX_BYTES:
        text = data[:DIFF_MAX_BYTES].decode("utf-8", "ignore")
        truncated = True
    return text, truncated


def _diff_text(repo_path: str, rel_path: str) -> tuple[str, bool]:
    """Return ``(text, truncated)`` for the unstaged diff, else the cached one."""
    result = run_git(repo_path, ["diff", "--no-color", "--", rel_path], timeout=20)
    if result.returncode != 0:
        raise CommandError(_short_error(result))
    text = _decode(result.stdout)
    if not text:
        cached = run_git(
            repo_path, ["diff", "--no-color", "--cached", "--", rel_path], timeout=20
        )
        if cached.returncode != 0:
            raise CommandError(_short_error(cached))
        text = _decode(cached.stdout)
    return _cap_diff(text)


def cmd_diff(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read-only diff for one repo-relative path (README section 5)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    rel_path = validate_repo_relpath(opt_value(args, "--path"))
    text, truncated = _diff_text(repo["path"], rel_path)
    return {"ok": True, "text": text, "truncated": truncated}


# --------------------------------------------------------------------------
# Secret scan and commit (README section 6)
# --------------------------------------------------------------------------

# Named rules; the matched VALUE is never returned, only the rule/path/line.
SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{60,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    (
        "assignment",
        re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    ),
]

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_SECRET_DIFF_CAP = 2 * 1024 * 1024

# Git prefixes the paths in a diff with a one-character component: the classic
# ``a/``/``b/`` or the mnemonic ``i/`` (index), ``w/`` (worktree), ``c/``
# (commit), ``o/`` (object), ``1/``/``2/`` (merge sides). Always strip one.
_DIFF_PREFIX_CHARS = frozenset("abciow12")


def iter_added_lines(diff_text: str):
    """Yield ``(path, line_number, text)`` for every added line of a diff."""
    path = ""
    new_line = 0
    in_hunk = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        if line.startswith("@@"):
            match = _HUNK_HEADER.match(line)
            if match:
                new_line = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            if line.startswith("+++ "):
                target = line[4:].strip()
                if len(target) >= 2 and target[1] == "/" and target[0] in _DIFF_PREFIX_CHARS:
                    target = target[2:]
                path = target
            continue
        if line.startswith("\\ "):
            continue
        if line.startswith("+"):
            yield path, new_line, line[1:]
            new_line += 1
        elif line.startswith("-"):
            continue
        elif line.startswith(" "):
            new_line += 1


def scan_secrets(diff_text: str) -> list[dict[str, Any]]:
    """Find secret-looking added lines; never includes the matched value."""
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for path, line_no, text in iter_added_lines(diff_text):
        for rule, pattern in SECRET_RULES:
            if not pattern.search(text):
                continue
            key = (path, line_no, rule)
            if key in seen:
                continue
            seen.add(key)
            found.append({"path": path, "line": line_no, "rule": rule})
    return found


def read_stdin_json() -> Any:
    """Read and parse a JSON payload from stdin; ``None`` when empty."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if raw is None or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise CommandError("invalid JSON on stdin: " + _shorten(str(exc)))


def cmd_commit(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Stage selected paths, scan for secrets, and commit (README section 6)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    payload = read_stdin_json()
    if not isinstance(payload, dict):
        raise CommandError("commit expects a JSON object on stdin")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise CommandError("commit message must not be empty")
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise CommandError("no paths selected")
    repo_path = repo["path"]
    rel_paths: list[str] = []
    for raw in raw_paths:
        rel = validate_repo_relpath(raw)
        if not os.path.lexists(os.path.join(repo_path, rel)):
            raise CommandError("path not found in repo: " + rel)
        rel_paths.append(rel)
    added = run_git(repo_path, ["add", "--", *rel_paths], timeout=20)
    if added.returncode != 0:
        raise CommandError(_short_error(added))
    staged = run_git(
        repo_path, ["diff", "--cached", "-U0"], timeout=20, max_output=_SECRET_DIFF_CAP
    )
    secrets = scan_secrets(_decode(staged.stdout))
    if secrets and not payload.get("allow_secrets"):
        return {
            "ok": False,
            "error": "Secret detected in staged changes; commit blocked.",
            "secrets": secrets,
        }
    committed = run_git(
        repo_path, ["commit", "-F", "-"], timeout=30, stdin=message.rstrip("\n") + "\n"
    )
    if committed.returncode != 0:
        raise CommandError(_short_error(committed))
    rev = run_git(repo_path, ["rev-parse", "--short", "HEAD"], timeout=20)
    short_hash = _decode(rev.stdout).strip()
    return {"ok": True, "commit": short_hash, "secrets": []}


# --------------------------------------------------------------------------
# push and pull (README section 5)
# --------------------------------------------------------------------------


def _push_error_text(text: str) -> str:
    """Map a failed push to short human text (README section 5.2)."""
    lowered = text.lower()
    if (
        "non-fast-forward" in lowered
        or "fetch first" in lowered
        or "rejected" in lowered
        or "behind" in lowered
    ):
        return "Push rejected: the remote has new commits. Pull first."
    short = _shorten(text)
    return short or "Push failed."


def cmd_push(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Push the current branch; a remote rejection is non-fatal (README section 5)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    try:
        result = run_git(repo["path"], ["push"], timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": True, "push_error": "Push timed out after 300s."}
    if result.returncode == 0:
        try:
            record_publish(resolve_state_dir(state_dir), repo["path"])
        except OSError:
            pass  # a stamp failure must never fail a successful push
        return {"ok": True, "pushed": True}
    text = _decode(result.stderr) + "\n" + _decode(result.stdout)
    return {"ok": True, "push_error": _push_error_text(text)}


def cmd_pull(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Fast-forward-only pull that refuses dirty/diverged/no-upstream repos."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    repo_path = repo["path"]
    try:
        status = git_status(repo_path)
    except Exception as exc:  # noqa: BLE001 - report as a refusal, not a crash
        return {"ok": False, "error": _shorten(str(exc)) or "git status failed"}
    if not status["upstream"]:
        return {"ok": False, "error": "No upstream branch is configured."}
    if status["ahead"] > 0 and status["behind"] > 0:
        return {
            "ok": False,
            "error": "Local and remote have diverged; resolve manually before pulling.",
        }
    if status["changes"] or status["untracked"]:
        return {
            "ok": False,
            "error": "Worktree has uncommitted changes; commit or stash them first.",
        }
    try:
        result = run_git(repo_path, ["pull", "--ff-only"], timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Pull timed out after 300s."}
    if result.returncode != 0:
        return {"ok": False, "error": _short_error(result)}
    return {"ok": True, "pulled": True}


# --------------------------------------------------------------------------
# restow (README section 5)
# --------------------------------------------------------------------------


def cmd_restow(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Dry-run stow first; on conflicts refuse, else restow (README section 5)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    package = validate_package_name(opt_value(args, "--package"))
    dry_run = "--dry-run" in args
    repo_path = repo["path"]
    target_dir = expand_path(repo.get("target", "~") or "~")
    dry = stow_dry_run(repo_path, target_dir, package)
    dry_text = _decode(dry.stderr)
    conflicts = parse_conflicts(dry_text, target_dir)
    if conflicts:
        return {
            "ok": False,
            "error": "Stow conflict: " + _shorten(conflicts[0]["message"]),
            "conflicts": conflicts,
        }
    if dry_run:
        return {"ok": True, "dry_run": True, "actions": parse_stow_actions(dry_text, target_dir)}
    real = stow_real(repo_path, target_dir, package)
    if real.returncode != 0:
        raise CommandError(_short_error(real))
    return {
        "ok": True,
        "dry_run": False,
        "actions": parse_stow_actions(_decode(real.stderr), target_dir),
    }


# --------------------------------------------------------------------------
# adopt (README section 5.3)
# --------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    """SHA-256 hex digest of a regular file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _move_path(src: str, dst: str, rename: Any = os.rename) -> None:
    """Move ``src`` to ``dst``; fall back to copy + verify + unlink on EXDEV.

    ``rename`` is injectable so tests can force the cross-device path.
    """
    try:
        rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    if os.path.isdir(src):
        shutil.copytree(src, dst, symlinks=True)
        shutil.rmtree(src)
        return
    shutil.copy2(src, dst)
    if sha256_file(dst) != sha256_file(src):
        try:
            os.unlink(dst)
        except OSError:
            pass
        raise CommandError("copy verification failed for " + src)
    os.unlink(src)


def _rollback_adopt(abs_path: str, dest: str, rename: Any) -> None:
    """Undo a partial adopt: drop a link stow made, then move ``dest`` back."""
    try:
        if os.path.islink(abs_path):
            os.unlink(abs_path)
    except OSError:
        pass
    try:
        if os.path.lexists(dest) and not os.path.lexists(abs_path):
            _move_path(dest, abs_path, rename)
    except OSError:
        pass


def _adopt_verified(abs_path: str, dest: str, original_sha: str | None) -> bool:
    """True when ``abs_path`` is a symlink to ``dest`` with the original bytes."""
    if not os.path.islink(abs_path):
        return False
    if os.path.realpath(abs_path) != os.path.realpath(dest):
        return False
    if original_sha is not None:
        try:
            if sha256_file(abs_path) != original_sha:
                return False
        except OSError:
            return False
    return True


def is_in_watch_area(path: str, config: dict[str, Any]) -> bool:
    """True when ``path`` is a direct child of a watch dir or matches a glob."""
    norm = os.path.normpath(path)
    for entry in config.get("watch", []):
        if not isinstance(entry, str):
            continue
        watch = expand_path(entry)
        if _has_glob(watch):
            if fnmatch.fnmatch(norm, watch) or fnmatch.fnmatch(to_tilde(norm), to_tilde(watch)):
                return True
        elif os.path.dirname(norm) == os.path.normpath(watch):
            return True
    return False


def cmd_adopt(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
    rename: Any = os.rename,
) -> dict[str, Any]:
    """Adopt a watched path into a package without ``stow --adopt`` (section 5.3)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    package = validate_package_name(opt_value(args, "--package"))
    raw_path = opt_value(args, "--path")
    if not raw_path:
        raise CommandError("missing --path")
    abs_path = os.path.normpath(expand_path(raw_path))
    dry_run = "--dry-run" in args
    home = os.path.expanduser("~")
    if abs_path == home or not _under(abs_path, home):
        raise CommandError("adopt path must be under HOME: " + raw_path)
    if not is_in_watch_area(abs_path, config):
        raise CommandError("adopt path is not inside a configured watch area: " + raw_path)
    if not os.path.lexists(abs_path):
        raise CommandError("path does not exist: " + to_tilde(abs_path))
    if os.path.islink(abs_path):
        raise CommandError("path is already a symlink: " + to_tilde(abs_path))
    target_dir = expand_path(repo.get("target", "~") or "~")
    repo_path = repo["path"]
    rel = os.path.relpath(abs_path, target_dir)
    if rel.startswith(".."):
        raise CommandError("adopt path is outside the repo target: " + raw_path)
    dest = os.path.join(repo_path, package, rel)
    moved_to = to_tilde(dest)
    if os.path.lexists(dest):
        raise CommandError("destination already exists: " + moved_to)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "moved_to": moved_to,
            "actions": [{"action": "LINK", "target": to_tilde(abs_path), "source": moved_to}],
        }
    original_sha = sha256_file(abs_path) if os.path.isfile(abs_path) else None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    _move_path(abs_path, dest, rename)
    dry = stow_dry_run(repo_path, target_dir, package)
    conflicts = parse_conflicts(_decode(dry.stderr), target_dir)
    if conflicts:
        _rollback_adopt(abs_path, dest, rename)
        return {
            "ok": False,
            "error": "Stow conflict: " + _shorten(conflicts[0]["message"]),
            "conflicts": conflicts,
        }
    real = stow_real(repo_path, target_dir, package)
    if real.returncode != 0:
        _rollback_adopt(abs_path, dest, rename)
        return {"ok": False, "error": _short_error(real)}
    if not _adopt_verified(abs_path, dest, original_sha):
        _rollback_adopt(abs_path, dest, rename)
        return {"ok": False, "error": "Adopt verification failed; rolled back."}
    return {
        "ok": True,
        "moved_to": moved_to,
        "actions": parse_stow_actions(_decode(real.stderr), target_dir),
    }


# --------------------------------------------------------------------------
# ignore / unignore (README section 5)
# --------------------------------------------------------------------------


def normalize_path_list(payload: Any) -> list[str]:
    """Normalize stdin into a deduped list of ``~``-relative paths."""
    if isinstance(payload, str):
        items: list[Any] = [payload]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("paths", [])
        items = raw if isinstance(raw, list) else [raw]
    else:
        items = []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item:
            continue
        norm = to_tilde(expand_path(item))
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def _read_raw_config(path: str) -> dict[str, Any]:
    """Read the on-disk config verbatim (defaults created first if missing)."""
    if not os.path.exists(path):
        load_config(path)
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _write_config_atomic(path: str, data: dict[str, Any]) -> None:
    """Atomically replace the config file, preserving its permission mode."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _update_ignore(args: list[str], config_path: str | None, add: bool) -> dict[str, Any]:
    paths = normalize_path_list(read_stdin_json())
    config_file = expand_path(config_path) if config_path else default_config_path()
    raw = _read_raw_config(config_file)
    ignore = [p for p in raw.get("ignore", []) if isinstance(p, str)]
    for path in paths:
        if add:
            if path not in ignore:
                ignore.append(path)
        else:
            ignore = [p for p in ignore if p != path]
    raw["ignore"] = ignore
    _write_config_atomic(config_file, raw)
    return {"ok": True, "ignore": ignore}


def cmd_ignore(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Add paths to the config ``ignore`` list (README section 5)."""
    return _update_ignore(args, config_path, True)


def cmd_unignore(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Remove exact matches from the config ``ignore`` list (README section 5)."""
    return _update_ignore(args, config_path, False)


# --------------------------------------------------------------------------
# suggest-message (README section 5.4)
# --------------------------------------------------------------------------


def _file_names_summary(paths: list[str]) -> str:
    """Up to three basenames, then ``+N more``."""
    names = [os.path.basename(path) for path in paths]
    shown = names[:3]
    text = ", ".join(shown)
    extra = len(names) - len(shown)
    if extra > 0:
        text += f", +{extra} more"
    return text


def suggest_message(paths: list[str], statuses: dict[str, str]) -> str:
    """Pure commit-message suggestion (README section 5.4)."""
    clean_paths = [str(p) for p in paths if isinstance(p, str) and p]
    if not clean_paths:
        return "chore: update files"
    packages: list[str] = []
    for path in clean_paths:
        package = _package_of(path)
        if package not in packages:
            packages.append(package)
    only_additions = all(
        statuses.get(path, "modified") in ("added", "untracked") for path in clean_paths
    )
    if len(packages) == 1:
        package = packages[0]
        if only_additions:
            return f"feat({package}): add {_file_names_summary(clean_paths)}"
        return f"chore({package}): update {_file_names_summary(clean_paths)}"
    shown = packages[:2]
    extra = len(packages) - len(shown)
    suffix = f", +{extra} more" if extra > 0 else ""
    return "chore: update " + ", ".join(shown) + suffix


def _suggest_path_items(payload: Any) -> list[Any]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        raw = payload.get("paths", [])
        return raw if isinstance(raw, list) else [raw]
    return []


def _to_repo_relpath(raw: Any, repo_path: str) -> str:
    """Map a ``~``-relative/absolute path to a repo-relative one, or validate."""
    if not isinstance(raw, str) or not raw:
        raise CommandError("empty path")
    if raw.startswith("~") or os.path.isabs(raw):
        expanded = os.path.normpath(expand_path(raw))
        rel = os.path.relpath(expanded, repo_path)
        if rel == ".." or rel.startswith(".." + os.sep):
            raise CommandError("path is outside the repo: " + raw)
        return rel.replace(os.sep, "/")
    return validate_repo_relpath(raw)


def _repo_status_map(repo_path: str) -> dict[str, str]:
    """Map repo-relative path -> status kind (untracked included)."""
    try:
        status = git_status(repo_path)
    except Exception:  # noqa: BLE001 - a missing status just yields no hints
        return {}
    result: dict[str, str] = {}
    for change in status["changes"]:
        result[change["path"]] = change["kind"]
    for entry in status["untracked"]:
        result[entry["path"]] = "untracked"
    return result


def cmd_suggest_message(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Suggest a commit message for the given paths (README section 5.4)."""
    config = load_config(config_path)
    repo = resolve_repo(config, opt_value(args, "--repo"))
    repo_path = repo["path"]
    payload = read_stdin_json()
    rel_paths = [
        _to_repo_relpath(item, repo_path) for item in _suggest_path_items(payload)
    ]
    statuses = _repo_status_map(repo_path)
    return {"ok": True, "message": suggest_message(rel_paths, statuses)}


# --------------------------------------------------------------------------
# status --short (README section 7)
# --------------------------------------------------------------------------


def cmd_status_short(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> str:
    """One plain Starship line; empty when clean (README section 7).

    Shares the JSON ``status`` baseline logic (§5.3b): the first run in a fresh
    state dir creates baseline.json from the current candidates, so pre-existing
    files are known. Skips stow health for speed; the baseline is the only write.
    """
    config = load_config(config_path)
    segments: list[str] = []
    for repo_cfg in config.get("repos", []):
        raw_path = repo_cfg.get("path", "") if isinstance(repo_cfg, dict) else ""
        path = expand_path(raw_path) if raw_path else ""
        if not path or _git_dir(path) is None:
            continue
        try:
            status = git_status(path)
        except Exception:  # noqa: BLE001 - one bad repo must not blank the line
            continue
        parts: list[str] = []
        if status["changes"]:
            parts.append(f"{len(status['changes'])} changed")
        if status["untracked"]:
            parts.append(f"{len(status['untracked'])} untracked")
        if status["ahead"] > 0:
            parts.append(f"{status['ahead']} unpushed")
        if status["behind"] > 0:
            parts.append(f"{status['behind']} behind")
        if not parts:
            continue
        basename = os.path.basename(os.path.normpath(path))
        name = basename.lstrip(".") or basename
        segments.append(f"{name}: " + ", ".join(parts))
    candidates = compute_candidates(config)
    baseline = load_baseline(resolve_state_dir(state_dir), [c["path"] for c in candidates])
    known = baseline["paths"]
    for candidate in candidates:
        candidate["known"] = candidate["path"] in known
    unknown = compute_badge(candidates)
    if unknown > 0:
        segments.append(f"{unknown} new config")
    return " · ".join(segments)


COMMANDS = {
    "version": cmd_version,
    "status": cmd_status,
    "baseline": cmd_baseline,
    "diff": cmd_diff,
    "commit": cmd_commit,
    "push": cmd_push,
    "pull": cmd_pull,
    "restow": cmd_restow,
    "adopt": cmd_adopt,
    "ignore": cmd_ignore,
    "unignore": cmd_unignore,
    "suggest-message": cmd_suggest_message,
}


def extract_global_args(argv: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Pull the global ``--config`` and ``--state-dir`` flags out of an argv.

    Returns ``(config_path_or_None, state_dir_or_None, remaining_args)``. Both
    ``--flag PATH`` and ``--flag=PATH`` are accepted.
    """
    config_path: str | None = None
    state_dir: str | None = None
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
        if token == "--state-dir":
            if index + 1 < len(argv):
                state_dir = argv[index + 1]
                index += 2
                continue
            index += 1
            continue
        if token.startswith("--state-dir="):
            state_dir = token[len("--state-dir="):]
            index += 1
            continue
        rest.append(token)
        index += 1
    return config_path, state_dir, rest


def dispatch(
    argv: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Route one already-parsed argument vector to its command handler."""
    name = argv[0] if argv else ""
    handler = COMMANDS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown command: " + (name or "<none>")}
    try:
        return handler(argv[1:], config_path, state_dir)
    except CommandError as exc:
        return {"ok": False, "error": _shorten(str(exc))}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": _shorten("command timed out: " + str(exc))}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        config_path, state_dir, rest = extract_global_args(args)
        if rest and rest[0] == "status" and "--short" in rest[1:]:
            # Starship integration: one plain line, not JSON (README section 7).
            text = cmd_status_short(rest[1:], config_path, state_dir)
            if text:
                sys.stdout.write(text + "\n")
            return 0
        result = dispatch(rest, config_path, state_dir)
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
