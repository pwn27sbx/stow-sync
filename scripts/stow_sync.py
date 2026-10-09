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
import fnmatch
import glob
import json
import os
import re
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
    """Size in bytes; recursive for directories, never following subdir links."""
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
    """Suggest a package for a candidate (README section 5.3)."""
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
    base = os.path.basename(path) if os.path.isdir(path) else os.path.basename(parent)
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
    repos = [_repo_status(repo_cfg, do_fetch) for repo_cfg in config.get("repos", [])]
    candidates = compute_candidates(config)
    baseline = load_baseline(
        resolve_state_dir(state_dir),
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


COMMANDS = {
    "version": cmd_version,
    "status": cmd_status,
    "baseline": cmd_baseline,
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
    return handler(argv[1:], config_path, state_dir)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        config_path, state_dir, rest = extract_global_args(args)
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
