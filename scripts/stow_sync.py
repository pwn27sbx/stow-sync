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

import concurrent.futures
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


def _write_json_atomic(
    path: str,
    data: dict[str, Any],
    mode: int = 0o600,
    prefix: str = ".baseline-",
    fsync: bool = False,
) -> None:
    """Write JSON to ``path`` atomically with a fixed permission mode.

    With ``fsync=True`` the temp file and its directory are flushed to disk
    before the atomic rename, so an append-and-fsync manifest survives a crash
    (README section 8a apply).
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        if fsync:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
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


# --------------------------------------------------------------------------
# Desktop notifications (README section 4 / 8, Unit 5): ``notify_after_hours``
# decides when a repo that has been pending continuously long enough gets one
# ``notify-send`` per calendar day. The decision is pure; the wiring lives in
# ``cmd_status`` only (never ``status --short``).
# --------------------------------------------------------------------------

NOTIFY_VERSION = 1
NOTIFY_FILENAME = "notify.json"


def notify_state_path(state_dir: str) -> str:
    """Path of the notification state file inside ``state_dir``."""
    return os.path.join(state_dir, NOTIFY_FILENAME)


def load_notify_state(state_dir: str) -> dict[str, dict[str, Any]]:
    """Read ``{repo path: {first_pending, last_notified}}``; ``{}`` when unreadable.

    The on-disk shape is ``{"version": 1, "repos": {...}}``; a read failure
    (missing file, bad JSON, wrong shape) yields an empty mapping so a fresh
    decision can simply rebuild it.
    """
    try:
        with open(notify_state_path(state_dir), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    repos = data.get("repos")
    if not isinstance(repos, dict):
        return {}
    clean: dict[str, dict[str, Any]] = {}
    for key, value in repos.items():
        if isinstance(key, str) and isinstance(value, dict):
            clean[key] = value
    return clean


def save_notify_state(state_dir: str, repos_state: dict[str, dict[str, Any]]) -> None:
    """Persist the notification state atomically (dir 0700, file 0600)."""
    os.makedirs(state_dir, 0o700, exist_ok=True)
    _write_json_atomic(
        notify_state_path(state_dir),
        {"version": NOTIFY_VERSION, "repos": repos_state},
        0o600,
        prefix=".notify-",
    )


def repo_pending(repo: dict[str, Any]) -> bool:
    """True when ``repo`` has work: changes, untracked, ahead/behind, bad health."""
    if repo.get("changes") or repo.get("untracked"):
        return True
    if repo.get("ahead", 0) > 0 or repo.get("behind", 0) > 0:
        return True
    for package in repo.get("packages", []) or []:
        if str(package.get("health", "ok")) != "ok":
            return True
    return False


def repo_pending_count(repo: dict[str, Any]) -> int:
    """Number of attention items in ``repo`` (for the notification body)."""
    count = len(repo.get("changes", []) or []) + len(repo.get("untracked", []) or [])
    if repo.get("ahead", 0) > 0:
        count += 1
    if repo.get("behind", 0) > 0:
        count += 1
    for package in repo.get("packages", []) or []:
        if str(package.get("health", "ok")) != "ok":
            count += len(package.get("pending_links", []) or [])
            count += len(package.get("conflicts", []) or [])
            count += len(package.get("dangling", []) or [])
    return count


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp; ``None`` for anything malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def notify_decision(
    repos: list[dict[str, Any]],
    prior_state: dict[str, dict[str, Any]],
    now_iso: str,
    after_hours: float,
) -> dict[str, Any]:
    """Decide which repos get a desktop notification now (pure).

    A repo is **pending** when it has changes/untracked files, is ahead/behind,
    or has a package whose ``health != "ok"`` (see :func:`repo_pending`). State
    per repo tracks ``first_pending`` and ``last_notified``; a repo that is no
    longer pending is dropped. ``after_hours <= 0`` disables sending entirely.
    A send is decided when the repo has been pending continuously for at least
    ``after_hours`` and was not already notified on the same calendar day.

    Returns ``{"sends": [<repo path>...], "state": {<repo path>: {...}}}``.
    """
    now = _parse_iso(now_iso) or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.now().astimezone().tzinfo)
    tries = float(after_hours)
    threshold = tries * 3600
    prior = prior_state if isinstance(prior_state, dict) else {}
    sends: list[str] = []
    state: dict[str, dict[str, Any]] = {}
    for repo in repos:
        path = repo.get("path")
        if not path:
            continue
        if not repo_pending(repo):
            continue
        entry = prior.get(path) if isinstance(prior.get(path), dict) else {}
        first = _parse_iso(entry.get("first_pending"))
        if first is not None and first.tzinfo is None:
            first = first.replace(tzinfo=now.tzinfo)
        if first is None:
            first = now
            first_iso = now_iso
        else:
            first_iso = entry["first_pending"]
        last = entry.get("last_notified")
        last_dt = _parse_iso(last)
        if last_dt is not None and last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=now.tzinfo)
        new_entry: dict[str, Any] = {
            "first_pending": first_iso,
            "last_notified": last if isinstance(last, str) else None,
        }
        if tries > 0 and (now - first).total_seconds() >= threshold:
            if last_dt is None or last_dt.date() != now.date():
                new_entry["last_notified"] = now_iso
                sends.append(str(path))
        state[str(path)] = new_entry
    return {"sends": sends, "state": state}


def spawn_notify(repo_path: str, count: int) -> None:
    """Fire one detached ``notify-send``; swallow every failure.

    A missing ``notify-send`` or any spawn error must never fail ``status``.
    """
    body = f"{repo_path}: {count} items need attention"
    try:
        subprocess.Popen(
            ["notify-send", "Stow Sync", body],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        pass


def update_notifications(
    repos: list[dict[str, Any]],
    state_dir: str,
    config: dict[str, Any],
) -> list[str]:
    """Read/decide/write notify state and spawn the decided notifications.

    Never raises: a state-file or ``notify-send`` failure leaves the caller's
    ``status`` at ``ok: true``. Returns the repo paths a send was decided for.
    """
    try:
        after = float(config.get("notify_after_hours", 0) or 0)
    except (TypeError, ValueError):
        after = 0.0
    try:
        prior = load_notify_state(state_dir)
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        decision = notify_decision(repos, prior, now_iso, after)
        try:
            save_notify_state(state_dir, decision["state"])
        except OSError:
            pass
        by_path = {repo.get("path"): repo for repo in repos}
        for path in decision["sends"]:
            spawn_notify(path, repo_pending_count(by_path.get(path, {})))
        return list(decision["sends"])
    except Exception:  # noqa: BLE001 - notifications must never fail status
        return []


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


def _drain_capped(
    pipe: Any,
    sink: list[bytes],
    max_output: int,
    overflow: threading.Event,
    on_chunk: Any = None,
) -> None:
    """Read a child pipe to EOF, keeping at most ``max_output`` bytes.

    Draining continues past the cap (discarding) so the child never blocks on
    a full pipe; the overflow flag lets the parent kill the process group.
    ``on_chunk`` (optional) receives every raw chunk as it arrives, so a caller
    can stream progress while the child still runs.
    """
    kept = 0
    total = 0
    try:
        while True:
            # read1 returns as soon as any bytes are available; read(n) would
            # block until n bytes or EOF, which would hide live progress.
            chunk = pipe.read1(65536)
            if not chunk:
                return
            total += len(chunk)
            if kept < max_output:
                take = chunk[: max_output - kept]
                sink.append(take)
                kept += len(take)
            if total > max_output:
                overflow.set()
            if on_chunk is not None:
                try:
                    on_chunk(chunk)
                except Exception:  # noqa: BLE001 - progress feedback is best-effort
                    pass
    except (OSError, ValueError):
        pass


def run_bounded(
    argv: list[str],
    timeout: float,
    max_output: int = MAX_OUTPUT,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    on_stderr: Any = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a child in its own process group with capped output.

    On timeout the whole group is killed and ``subprocess.TimeoutExpired`` is
    raised. On output overflow the group is killed and the returned result's
    stderr notes the truncation with a non-zero return code. ``on_stderr``
    (optional) receives every raw stderr chunk as it arrives, for live progress.
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
        threading.Thread(target=_drain_capped, args=(proc.stderr, err_chunks, max_output, overflow, on_stderr), daemon=True),
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


# Stow 2.4.1 emits two conflict forms. The first names both the source and the
# target ("neither a link nor a directory"); the second names only the target
# when it is a symlink Stow does not own ("existing target is not owned by
# stow"). Both are pinned verbatim in tests/fixtures/.
_CONFLICT_NOT_OWNED = re.compile(r"existing target is not owned by stow: (?P<target>.+)$")


def parse_conflict_entries(text: str, target_dir: str) -> list[dict[str, str]]:
    """Parse both Stow 2.4.1 conflict forms with a ``form`` tag.

    ``form`` is ``"over"`` for ``cannot stow X over existing target Y`` and
    ``"not-owned"`` for ``existing target is not owned by stow: Y``. Entries
    carry ``target``/``source`` as ``~``-relative display strings plus
    ``target_abs``/``source_abs`` for classification; ``source_abs`` is empty
    for the not-owned form.
    """
    entries: list[dict[str, str]] = []
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
        over = _CONFLICT_LINE.search(message)
        if over:
            source_abs = _resolve_under(target_dir, over.group("source"))
            target_abs = _resolve_under(target_dir, over.group("target"))
            entries.append(
                {
                    "form": "over",
                    "target": to_tilde(target_abs),
                    "target_abs": target_abs,
                    "source": to_tilde(source_abs),
                    "source_abs": source_abs,
                    "message": message,
                }
            )
            continue
        not_owned = _CONFLICT_NOT_OWNED.search(message)
        if not_owned:
            target_abs = _resolve_under(target_dir, not_owned.group("target"))
            entries.append(
                {
                    "form": "not-owned",
                    "target": to_tilde(target_abs),
                    "target_abs": target_abs,
                    "source": "",
                    "source_abs": "",
                    "message": message,
                }
            )
    return entries


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
    notifications_sent = update_notifications(repos, state, config)
    return {
        "ok": True,
        "repos": repos,
        "summary": compute_summary(repos, badge_count),
        "candidates": candidates,
        "baseline_error": baseline["error"],
        "notifications_sent": notifications_sent,
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


# --------------------------------------------------------------------------
# Unit 8a: "Set up this machine" backend (README section 8a)
#
# The opt-in one-click restore is split across seven commands: setup-prereqs,
# setup-connect, setup-clone, setup-plan, setup-apply, setup-undo and
# setup-backups. Everything runs against a temporary HOME in tests; the plan
# token is the only guard between a reviewed plan and a mutating apply
# (README section 8.1). Connect clones the dotfiles repo only; setup-clone
# clones one further recipe repo per request (README 10a.2).
# --------------------------------------------------------------------------

SETUP_RECIPE_VERSION = 1
SETUP_PLAN_FILENAME = "setup-plan.json"
SETUP_PLAN_TTL_SECONDS = 600
SETUP_BACKUPS_DIRNAME = "setup-backups"
SETUP_PROGRESS_FILENAME = "setup-progress.json"
SETUP_RECIPE_RELPATH = os.path.join(".stow-sync", "setup.json")
DEFAULT_SETUP_PATH = "~/.dotfiles"
SETUP_PLAN_ERROR = "The setup plan changed. Review it again."
# Prerequisite checks (README 10a.1). The pacman sync database path is a module
# constant so tests can point it at a missing file without touching the host.
PACMAN_SYNC_DB = "/var/lib/pacman/sync/core.db"
SETUP_GH_FIX = "gh auth login, then gh auth setup-git"

# Candidate detection (README 11c.1): a read-only probe of the user's GitHub
# repos. The definitive check (does `.stow-sync/setup.json` exist?) runs at
# concurrency 4 under a wall-clock deadline so a large account still answers
# fast, with partial results and no blocking.
CANDIDATES_DEADLINE_SECONDS = 10.0
CANDIDATES_CONCURRENCY = 4
CANDIDATES_API_TIMEOUT = 5.0
CANDIDATES_REPO_LIMIT = 100
# A Stow-package shape signal (README 12a/finding 50): shell/user dotfiles that
# mark a real dotfiles repo. Generic project dotfiles (.gitignore, .eslintrc,
# .prettierrc, .github/, .vscode/, .env*) never count.
_SHELL_DOTFILES = frozenset({".zshrc", ".bashrc", ".gitconfig", ".tmux.conf", ".vimrc"})
_SETUP_HINT_WORDS = ("dotfiles", "dotfile", "dots", "config", "stow")

_SETUP_TOP_KEYS = frozenset(
    {"version", "repos", "skip_packages", "services", "requires", "post", "notes"}
)
_SETUP_REPO_KEYS = frozenset({"path", "url", "packages", "order", "private"})
_SETUP_POST_KEYS = frozenset({"id", "label", "argv", "default", "timeout_s", "needs"})


def setup_recipe_file(repo_path: str) -> str:
    """Absolute path of the setup recipe inside a repo checkout."""
    return os.path.join(repo_path, SETUP_RECIPE_RELPATH)


def normalize_remote_url(url: Any) -> str:
    """Normalize a git URL for comparison: drop a trailing ``/`` and ``.git``."""
    text = str(url or "").strip()
    while text.endswith("/"):
        text = text[:-1]
    if text.endswith(".git"):
        text = text[:-4]
    return text.rstrip("/")


def _setup_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def validate_setup_recipe(data: Any) -> dict[str, Any]:
    """Strictly validate a setup recipe and return its normalized copy.

    Every failure raises :class:`CommandError` with a precise, distinct
    message (README section 8.2) so callers and tests can tell them apart.
    """
    if not isinstance(data, dict):
        raise CommandError("recipe: root must be an object")
    unknown = sorted(set(data) - _SETUP_TOP_KEYS)
    if unknown:
        raise CommandError("recipe: unknown key: " + unknown[0])
    if data.get("version") != SETUP_RECIPE_VERSION:
        raise CommandError("recipe: version must be 1")

    repos_raw = data.get("repos")
    if not isinstance(repos_raw, list):
        raise CommandError("recipe: repos must be a list")
    repos: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    for index, repo in enumerate(repos_raw):
        where = "repos[" + str(index) + "]"
        if not isinstance(repo, dict):
            raise CommandError("recipe: " + where + " must be an object")
        unknown = sorted(set(repo) - _SETUP_REPO_KEYS)
        if unknown:
            raise CommandError("recipe: " + where + " has unknown key: " + unknown[0])
        if not _setup_str(repo.get("path")):
            raise CommandError("recipe: " + where + ".path must be a non-empty string")
        if not _setup_str(repo.get("url")):
            raise CommandError("recipe: " + where + ".url must be a non-empty string")
        order = repo.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            raise CommandError("recipe: " + where + ".order must be an integer")
        if order in seen_orders:
            raise CommandError("recipe: duplicate order: " + str(order))
        seen_orders.add(order)
        packages = repo.get("packages")
        if packages == "auto":
            normalized_packages: Any = "auto"
        elif isinstance(packages, list):
            for name in packages:
                try:
                    validate_package_name(name)
                except CommandError:
                    raise CommandError(
                        "recipe: " + where + ".packages has an invalid package name: " + str(name)
                    )
            normalized_packages = list(packages)
        else:
            raise CommandError(
                "recipe: " + where + '.packages must be "auto" or a list of package names'
            )
        private = repo.get("private", False)
        if not isinstance(private, bool):
            raise CommandError("recipe: " + where + ".private must be a boolean")
        repos.append(
            {
                "path": repo["path"],
                "url": repo["url"],
                "packages": normalized_packages,
                "order": order,
                "private": private,
            }
        )

    skip_raw = data.get("skip_packages", [])
    if not isinstance(skip_raw, list):
        raise CommandError("recipe: skip_packages must be a list of package names")
    for name in skip_raw:
        try:
            validate_package_name(name)
        except CommandError:
            raise CommandError("recipe: skip_packages has an invalid package name: " + str(name))

    services_raw = data.get("services", [])
    if not isinstance(services_raw, list) or not all(isinstance(x, str) for x in services_raw):
        raise CommandError("recipe: services must be a list of strings")
    requires_raw = data.get("requires", [])
    if not isinstance(requires_raw, list) or not all(isinstance(x, str) for x in requires_raw):
        raise CommandError("recipe: requires must be a list of strings")
    notes_raw = data.get("notes", [])
    if not isinstance(notes_raw, list) or not all(isinstance(x, str) for x in notes_raw):
        raise CommandError("recipe: notes must be a list of strings")

    post_raw = data.get("post", [])
    if not isinstance(post_raw, list):
        raise CommandError("recipe: post must be a list")
    home = os.path.expanduser("~")
    posts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(post_raw):
        where = "post[" + str(index) + "]"
        if not isinstance(item, dict):
            raise CommandError("recipe: " + where + " must be an object")
        unknown = sorted(set(item) - _SETUP_POST_KEYS)
        if unknown:
            raise CommandError("recipe: " + where + " has unknown key: " + unknown[0])
        if not _setup_str(item.get("id")):
            raise CommandError("recipe: " + where + ".id must be a non-empty string")
        if item["id"] in seen_ids:
            raise CommandError("recipe: duplicate post id: " + item["id"])
        seen_ids.add(item["id"])
        if not isinstance(item.get("label"), str):
            raise CommandError("recipe: " + where + ".label must be a string")
        argv = item.get("argv")
        if not isinstance(argv, list) or not argv or not all(_setup_str(a) for a in argv):
            raise CommandError("recipe: " + where + ".argv must be a non-empty list of strings")
        expanded0 = os.path.expanduser(argv[0])
        if not os.path.isabs(expanded0) or not _under(os.path.normpath(expanded0), os.path.normpath(home)):
            raise CommandError(
                "recipe: " + where + ".argv[0] must resolve inside $HOME: " + argv[0]
            )
        default = item.get("default", False)
        if not isinstance(default, bool):
            raise CommandError("recipe: " + where + ".default must be a boolean")
        timeout_s = item.get("timeout_s", 300)
        if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise CommandError("recipe: " + where + ".timeout_s must be a positive integer")
        needs_raw = item.get("needs", [])
        if not isinstance(needs_raw, list) or not all(_setup_str(x) for x in needs_raw):
            raise CommandError(
                "recipe: " + where + ".needs must be a list of non-empty strings"
            )
        posts.append(
            {
                "id": item["id"],
                "label": item["label"],
                "argv": list(argv),
                "default": default,
                "timeout_s": timeout_s,
                "needs": list(needs_raw),
            }
        )

    return {
        "version": SETUP_RECIPE_VERSION,
        "repos": repos,
        "skip_packages": list(skip_raw),
        "services": list(services_raw),
        "requires": list(requires_raw),
        "post": posts,
        "notes": list(notes_raw),
    }


def load_setup_recipe_file(path: str) -> dict[str, Any]:
    """Read and strictly validate a recipe file, or raise :class:`CommandError`."""
    if not os.path.isfile(path):
        raise CommandError("recipe not found: " + to_tilde(path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError("recipe is not valid JSON: " + _shorten(str(exc)))
    return validate_setup_recipe(data)


def _git_origin_url(repo_path: str) -> str | None:
    """Return ``origin``'s URL, or ``None`` when the remote is absent."""
    result = run_git(repo_path, ["remote", "get-url", "origin"])
    if result.returncode != 0:
        return None
    return _decode(result.stdout).strip() or None


def _is_git_repo(path: str) -> bool:
    try:
        result = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and _decode(result.stdout).strip() == "true"


_AUTH_FAILURE_MARKERS = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "permission denied",
    "terminal prompts disabled",
    "repository not found",
    " 401",
    " 403",
)


def _is_auth_failure(text: str) -> bool:
    """True when git's failure text points at a missing GitHub login."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


def _clone_failure_text(path: str, url: str, private: bool, result: Any) -> str:
    """Map a clone failure to a short, human message (README section 8a.2)."""
    text = _short_error(result)
    basename = os.path.basename(os.path.normpath(path))
    name = basename.lstrip(".") or basename
    if _is_auth_failure(text):
        if private:
            return (
                f"The {name} repo is private. Run gh auth login and gh auth setup-git, "
                "then try again."
            )
        return (
            f"GitHub login is needed to clone {name}. Run gh auth login and "
            "gh auth setup-git, then try again."
        )
    return "Clone failed: " + text


def _setup_state_result(
    path: str,
    url: str,
    private: bool,
    state: str,
    error: str | None = None,
    auth_error: bool = False,
) -> dict[str, Any]:
    """One clone/verify result: ``state`` is ``cloned``, ``ready`` or ``error``.

    ``auth_error`` is true when the failure was a missing GitHub login, so the
    Connect step can show the fix and "Check again" (README 11c.3).
    """
    return {
        "path": to_tilde(path),
        "url": url,
        "private": private,
        "state": state,
        "error": error,
        "auth_error": auth_error,
    }


def _setup_repo_state(
    repo_path: str,
    url: str,
    private: bool,
    timeout: float = 300,
    state_dir: str | None = None,
    item: str | None = None,
) -> dict[str, Any]:
    """Clone one repo if missing and report a single ``state`` (README 10a.2).

    ``cloned`` (this call cloned it), ``ready`` (it already existed with the
    same remote) or ``error`` (with the private-repo auth message when the
    failure is an auth failure). Never raises for a clone failure. When
    ``state_dir``/``item`` are given, real ``git clone --progress`` output is
    parsed into ``setup-progress.json`` (README 11b.2).
    """
    if os.path.isdir(repo_path) and _is_git_repo(repo_path):
        origin = _git_origin_url(repo_path)
        if origin is None:
            return _setup_state_result(
                repo_path,
                url,
                private,
                "error",
                "existing repository has no origin remote: " + to_tilde(repo_path),
            )
        if normalize_remote_url(origin) != normalize_remote_url(url):
            return _setup_state_result(
                repo_path,
                url,
                private,
                "error",
                "existing repository has a different remote: " + to_tilde(repo_path),
            )
        return _setup_state_result(repo_path, url, private, "ready")
    if os.path.exists(repo_path):
        return _setup_state_result(
            repo_path,
            url,
            private,
            "error",
            "path exists but is not a git repository: " + to_tilde(repo_path),
        )
    parent = os.path.dirname(repo_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if state_dir and item:
        write_clone_progress(state_dir, item, None, "running")
    # Stream git's stderr so the panel sees a real percent while it clones
    # (README 12a/finding 52); previously the percent was only parsed after the
    # blocking clone finished.
    on_stderr: Any = None
    if state_dir and item:
        tail = {"text": "", "percent": None}

        def on_stderr(chunk: bytes) -> None:
            tail["text"] = (tail["text"] + _decode(chunk))[-4096:]
            found = parse_git_clone_progress(tail["text"])
            if found is not None and found["percent"] != tail["percent"]:
                tail["percent"] = found["percent"]
                write_clone_progress(state_dir, item, found, "running")

    result = run_bounded(
        build_git_argv(None, ["clone", "--progress", url, repo_path]),
        timeout,
        env=git_env(),
        on_stderr=on_stderr,
    )
    progress = parse_git_clone_progress(_decode(result.stderr))
    if result.returncode != 0:
        if state_dir and item:
            write_clone_progress(state_dir, item, progress, "failed")
        return _setup_state_result(
            repo_path,
            url,
            private,
            "error",
            _clone_failure_text(repo_path, url, private, result),
            auth_error=_is_auth_failure(_short_error(result)),
        )
    if state_dir and item:
        write_clone_progress(state_dir, item, progress, "done")
    return _setup_state_result(repo_path, url, private, "cloned")


def _setup_connect_recipe(path: str) -> tuple[Any, str | None]:
    """Read the recipe from a cloned dotfiles repo (``None`` + hint when absent)."""
    recipe_path = setup_recipe_file(path)
    if not os.path.isfile(recipe_path):
        hint = "No setup recipe found. Add " + to_tilde(recipe_path) + " to the repository."
        return None, hint
    try:
        with open(recipe_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError("recipe is not valid JSON: " + _shorten(str(exc)))
    return validate_setup_recipe(data), None


def cmd_setup_connect(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Clone the dotfiles repo only, then report the other repos to clone.

    Cloning is non-destructive and idempotent. The other recipe repos are
    returned (with url and privacy) so the caller clones them one request at a
    time with ``setup-clone`` and its longer timeout (README 10a.2).
    """
    url = opt_value(args, "--url")
    if not _setup_str(url):
        raise CommandError("missing --url")
    raw_path = opt_value(args, "--path") or DEFAULT_SETUP_PATH
    path = expand_path(raw_path)
    dotfiles_state = _setup_repo_state(
        path, url, False, timeout=300, state_dir=resolve_state_dir(state_dir), item=to_tilde(path)
    )
    if dotfiles_state["state"] == "error":
        return {
            "ok": False,
            "error": dotfiles_state["error"],
            "auth_error": dotfiles_state.get("auth_error", False),
        }

    recipe, hint = _setup_connect_recipe(path)

    repos: list[dict[str, Any]] = []
    if recipe is not None:
        target_norm = os.path.normpath(path)
        for repo in sorted(recipe["repos"], key=lambda item: item["order"]):
            repo_path = expand_path(repo["path"])
            if os.path.normpath(repo_path) == target_norm:
                continue
            repos.append(
                {"path": to_tilde(repo_path), "url": repo["url"], "private": repo["private"]}
            )

    # Real download estimates from GitHub, best-effort (README 12c answer 2).
    dotfiles_size: int | None = None
    if _which("gh") is not None:
        env = _gh_env()
        dotfiles_size = _gh_repo_size_bytes(url, env)
        for entry in repos:
            entry["size_bytes"] = _gh_repo_size_bytes(entry["url"], env)

    result: dict[str, Any] = {
        "ok": True,
        "state": dotfiles_state["state"],
        "path": to_tilde(path),
        "recipe": recipe,
        "repos": repos,
        "size_bytes": dotfiles_size,
    }
    if hint:
        result["hint"] = hint
    return result


def cmd_setup_clone(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Clone ONE recipe repo with the long clone timeout (README 10a.2)."""
    raw_path = opt_value(args, "--path")
    if not _setup_str(raw_path):
        raise CommandError("missing --path")
    repo_path = expand_path(raw_path)
    recipe = load_setup_recipe_file(_default_recipe_path())
    wanted = os.path.normpath(repo_path)
    entry: dict[str, Any] | None = None
    for repo in recipe["repos"]:
        if os.path.normpath(expand_path(repo["path"])) == wanted:
            entry = repo
            break
    if entry is None:
        raise CommandError("no recipe repo at " + to_tilde(repo_path))
    result: dict[str, Any] = {
        "ok": True,
        **_setup_repo_state(
            repo_path,
            entry["url"],
            entry["private"],
            timeout=900,
            state_dir=resolve_state_dir(state_dir),
            item=to_tilde(repo_path),
        ),
    }
    if _which("gh") is not None:
        result["size_bytes"] = _gh_repo_size_bytes(entry["url"], _gh_env())
    return result


def _is_github_url(url: str) -> bool:
    text = (url or "").strip().lower()
    return (
        text.startswith("https://github.com/")
        or text.startswith("http://github.com/")
        or text.startswith("git@github.com:")
    )


def _which(command: str) -> str | None:
    """``shutil.which`` behind a seam so tests can hide one command."""
    return shutil.which(command)


def _gh_env() -> dict[str, str]:
    """A gh/git environment with every interactive prompt disabled."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    env["NO_COLOR"] = "1"
    return env


_GH_ACCOUNT = re.compile(r"account\s+(?P<name>[A-Za-z0-9_.-]+)", re.IGNORECASE)


def _parse_gh_account(text: str) -> str | None:
    """The GitHub login from ``gh auth status`` output, or ``None``."""
    match = _GH_ACCOUNT.search(text or "")
    return match.group("name") if match else None


def _gh_auth_status() -> tuple[bool, str | None, str]:
    """Return ``(signed_in, account, detail)`` from ``gh auth status``.

    Never raises: a missing ``gh``, a timeout or a logged-out session is a
    plain "not signed in" result (README 11c.3).
    """
    try:
        result = run_bounded(["gh", "auth", "status"], 15, env=_gh_env())
    except subprocess.TimeoutExpired:
        return False, None, "not signed in"
    except OSError:
        return False, None, "not signed in"
    if result.returncode != 0:
        return False, None, "not signed in"
    account = _parse_gh_account(_decode(result.stdout) + "\n" + _decode(result.stderr))
    if account:
        return True, account, "signed in as " + account
    return True, None, "signed in"


def _setup_prereq_recipe(args: list[str]) -> dict[str, Any] | None:
    """The recipe to inspect for private repos, or ``None`` when unknown."""
    recipe_arg = opt_value(args, "--recipe")
    if recipe_arg:
        return load_setup_recipe_file(expand_path(recipe_arg))
    default = _default_recipe_path()
    if os.path.isfile(default):
        return load_setup_recipe_file(default)
    return None


def _prereq_which(cid: str, command: str, fix: str) -> dict[str, Any]:
    found = _which(command)
    detail = ("found at " + found) if found else (command + " is not installed")
    return {"id": cid, "ok": found is not None, "detail": detail, "fix": fix}


def _prereq_pacman_db() -> dict[str, Any]:
    present = os.path.isfile(PACMAN_SYNC_DB)
    if present:
        detail = "pacman sync database present"
    else:
        detail = (
            "No pacman sync database at "
            + PACMAN_SYNC_DB
            + "; Omarchy blocks a direct pacman -Syu"
        )
    return {"id": "pacman-db", "ok": present, "detail": detail, "fix": "omarchy update"}


def _prereq_gh_auth() -> dict[str, Any]:
    ok, _account, detail = _gh_auth_status()
    return {"id": "gh-auth", "ok": ok, "detail": detail, "fix": SETUP_GH_FIX}


def cmd_setup_prereqs(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read-only prerequisite check for the wizard (README 10a.1).

    Reports ``stow``, ``git``, the pacman sync database, and — only when a known
    recipe repo is private or the ``--url`` is a GitHub URL — ``gh`` and
    ``gh-auth``. ``ok_to_connect`` is true only when the blocking checks pass.
    """
    url = opt_value(args, "--url")
    recipe = _setup_prereq_recipe(args)
    needs_gh = False
    if recipe is not None:
        needs_gh = any(repo.get("private") for repo in recipe["repos"])
    if not needs_gh and _setup_str(url) and _is_github_url(url):
        needs_gh = True

    checks: list[dict[str, Any]] = [
        _prereq_which("stow", "stow", "omarchy pkg add stow"),
        _prereq_which("git", "git", "omarchy pkg add git"),
        _prereq_pacman_db(),
    ]
    # Finding 29: when gh is installed, always show a non-blocking GitHub login
    # row so a private repo is never discovered only after a failed clone.
    if needs_gh or _which("gh") is not None:
        checks.append(_prereq_which("gh", "gh", "omarchy pkg add github-cli"))
        checks.append(_prereq_gh_auth())

    by_id = {check["id"]: check for check in checks}
    blocking: list[str] = []
    if not by_id["stow"]["ok"]:
        blocking.append("stow")
    if not by_id["git"]["ok"]:
        blocking.append("git")
    # The pacman database only blocks when a tool still has to be installed.
    if blocking and not by_id["pacman-db"]["ok"]:
        blocking.append("pacman-db")
    # The login row blocks only when a private repo actually needs it.
    if needs_gh and not by_id["gh-auth"]["ok"]:
        blocking.append("gh-auth")

    return {
        "ok": True,
        "checks": checks,
        "needs_gh": needs_gh,
        "blocking": blocking,
        "ok_to_connect": not blocking,
    }


def cmd_setup_repos(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read-only list of the user's GitHub repos for the Connect picker.

    Runs ``gh repo list --limit 100 --json name,url,isPrivate`` with no prompt
    (README 10b.4/finding 11). Missing ``gh``, a failed call or unparseable
    output returns ``ok: false`` with a short message.
    """
    if _which("gh") is None:
        return {"ok": False, "error": "GitHub CLI (gh) is not installed."}
    env = _gh_env()
    try:
        result = run_bounded(
            ["gh", "repo", "list", "--limit", "100", "--json", "name,url,isPrivate"],
            60,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gh repo list timed out"}
    except OSError as exc:
        return {"ok": False, "error": _shorten(str(exc))}
    if result.returncode != 0:
        return {"ok": False, "error": _short_error(result)}
    try:
        data = json.loads(_decode(result.stdout) or "[]")
    except ValueError:
        return {"ok": False, "error": "could not parse the gh repo list output"}
    repos: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            url = str(item.get("url") or "")
            if name == "" or url == "":
                continue
            repos.append({"name": name, "url": url, "private": item.get("isPrivate") is True})
    return {"ok": True, "repos": repos}


def _gh_json(argv: list[str], timeout: float, env: dict[str, str] | None = None) -> tuple[Any, str | None]:
    """Run gh and parse its JSON stdout; returns ``(data, error)``."""
    try:
        result = run_bounded(argv, timeout, env=env or _gh_env())
    except subprocess.TimeoutExpired:
        return None, "timed out"
    except OSError as exc:
        return None, _shorten(str(exc))
    if result.returncode != 0:
        return None, _short_error(result)
    try:
        return json.loads(_decode(result.stdout) or "null"), None
    except ValueError:
        return None, "could not parse gh output"


def _setup_gh_repos(env: dict[str, str]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The user's repos with the fields candidate detection needs (README 11c.1)."""
    data, error = _gh_json(
        [
            "gh",
            "repo",
            "list",
            "--limit",
            str(CANDIDATES_REPO_LIMIT),
            "--json",
            "name,url,isPrivate,description,repositoryTopics",
        ],
        60,
        env,
    )
    if error is not None:
        return None, error
    repos: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            url = str(item.get("url") or "")
            if name == "" or url == "":
                continue
            topics = item.get("repositoryTopics")
            names: list[str] = []
            if isinstance(topics, list):
                for topic in topics:
                    if isinstance(topic, dict) and topic.get("name"):
                        names.append(str(topic["name"]))
                    elif isinstance(topic, str):
                        names.append(topic)
            repos.append(
                {
                    "name": name,
                    "url": url,
                    "private": item.get("isPrivate") is True,
                    "description": str(item.get("description") or ""),
                    "topics": names,
                }
            )
    return repos, None


def _repo_owner(url: str) -> str:
    """The owner segment of a GitHub repo URL, or an empty string."""
    match = re.search(r"github\.com[/:](?P<owner>[^/\s]+)/", url or "")
    return match.group("owner") if match else ""


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    """``(owner, repo)`` for a GitHub URL, or ``None`` when it is not one."""
    match = re.search(r"github\.com[/:](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$", url or "")
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    return (owner, repo) if owner and repo else None


def _gh_repo_size_bytes(url: str, env: dict[str, str], timeout: float = 5.0) -> int | None:
    """The repo's GitHub ``size`` in bytes, or ``None`` when unknown.

    README 12c answer 2: the download estimate comes from the GitHub API, and a
    number is only shown when it is real (never invented).
    """
    pair = _github_owner_repo(url)
    if pair is None:
        return None
    data, error = _gh_json(["gh", "api", f"repos/{pair[0]}/{pair[1]}"], timeout, env)
    if error is not None or not isinstance(data, dict):
        return None
    size_kb = data.get("size")
    if not isinstance(size_kb, int) or isinstance(size_kb, bool) or size_kb <= 0:
        return None
    return size_kb * 1024


def _repo_hint(repo: dict[str, Any]) -> bool:
    """Hint-only signal: the name, description or topics mention dotfiles."""
    haystack = " ".join(
        [str(repo.get("name") or ""), str(repo.get("description") or "")]
        + [str(topic) for topic in (repo.get("topics") or [])]
    ).lower()
    return any(word in haystack for word in _SETUP_HINT_WORDS)


def _repo_looks_like_stow(paths: Any) -> bool:
    """Likely signal from a repo tree: Stow-package shape (README 12a/finding 50).

    True when a top-level folder holds ``.config/`` or ``.local/``, or a
    shell/user dotfile sits at the root or inside a top-level folder. Generic
    project dotfiles never count, so a web project like TRJS is not flagged.
    """
    if not isinstance(paths, list):
        return False
    for path in paths:
        text = str(path or "")
        if text == "":
            continue
        parts = text.split("/")
        if len(parts) >= 2 and not parts[0].startswith(".") and parts[1] in (".config", ".local"):
            return True
        if len(parts) == 1 and text in _SHELL_DOTFILES:
            return True
        if len(parts) == 2 and not parts[0].startswith(".") and parts[1] in _SHELL_DOTFILES:
            return True
    return False


def _gh_search_recipe_repos(owner: str, env: dict[str, str], timeout: float) -> set[str] | None:
    """Best-effort ``gh search code`` for repos with a recipe; ``None`` on failure."""
    if owner == "":
        return None
    data, error = _gh_json(
        [
            "gh",
            "search",
            "code",
            ".stow-sync/setup.json",
            "--owner",
            owner,
            "--filename",
            "setup.json",
            "--json",
            "repository",
            "--limit",
            "100",
        ],
        timeout,
        env,
    )
    if error is not None or not isinstance(data, list):
        return None
    names: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        repo = item.get("repository")
        if isinstance(repo, dict):
            nwo = str(repo.get("nameWithOwner") or "")
            if "/" in nwo:
                names.add(nwo.split("/", 1)[1])
            elif repo.get("name"):
                names.add(str(repo["name"]))
    return names


def _gh_repo_has_recipe(owner: str, name: str, env: dict[str, str], timeout: float) -> bool | None:
    """True/False for ``.stow-sync/setup.json`` presence, ``None`` when unknown."""
    if owner == "":
        return None
    try:
        result = run_bounded(
            ["gh", "api", f"repos/{owner}/{name}/contents/.stow-sync/setup.json"],
            timeout,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return result.returncode == 0


def _gh_repo_tree_paths(owner: str, name: str, env: dict[str, str], timeout: float) -> Any:
    """Every path in the repo's HEAD tree, or ``None`` when unknown.

    One bounded read-only call gives the whole shape, so a top-level folder that
    holds ``.config/``/``.local/`` is visible without a call per folder
    (README 12a/finding 50).
    """
    if owner == "":
        return None
    data, error = _gh_json(
        ["gh", "api", f"repos/{owner}/{name}/git/trees/HEAD?recursive=1"], timeout, env
    )
    if error is not None or not isinstance(data, dict):
        return None
    tree = data.get("tree")
    if not isinstance(tree, list):
        return None
    return [str(item.get("path")) for item in tree if isinstance(item, dict) and item.get("path")]


def _run_with_deadline(
    items: list[Any],
    worker: Any,
    deadline: float,
    concurrency: int = CANDIDATES_CONCURRENCY,
) -> tuple[dict[Any, Any], list[Any]]:
    """Map ``worker`` over ``items`` with bounded concurrency and a deadline.

    Returns ``(results, pending)``: ``results`` maps an item to the worker's
    return value for every item that finished before ``deadline``; ``pending``
    lists everything that did not (partial results, README 11c.1). A worker
    exception becomes ``None`` for that item; the deadline is never exceeded.
    """
    results: dict[Any, Any] = {}
    pending: list[Any] = []
    if not items:
        return results, pending
    workers = max(1, int(concurrency))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        iterator = iter(items)
        inflight: dict[concurrent.futures.Future[Any], Any] = {}

        def top_up() -> None:
            while len(inflight) < workers and time.monotonic() < deadline:
                try:
                    item = next(iterator)
                except StopIteration:
                    return
                inflight[pool.submit(worker, item)] = item

        top_up()
        while inflight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, _ = concurrent.futures.wait(
                inflight, timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED
            )
            if not done:
                break
            for future in done:
                item = inflight.pop(future)
                try:
                    results[item] = future.result()
                except Exception:  # noqa: BLE001 - a failed probe is simply unknown
                    results[item] = None
            top_up()
        for future in inflight:
            future.cancel()
        pending = list(inflight.values()) + list(iterator)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results, pending


def cmd_setup_candidates(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read-only detection of the user's dotfiles-candidate repos (README 11c.1).

    Groups the account's repos into ``definitive`` (contains
    ``.stow-sync/setup.json``), ``likely`` (root has Stow-package shape) and
    ``others``. Returns within ``CANDIDATES_DEADLINE_SECONDS`` with partial
    results; ``hint`` flags name/description/topic matches.
    """
    if _which("gh") is None:
        return {"ok": False, "error": "GitHub CLI (gh) is not installed."}
    env = _gh_env()
    started = time.monotonic()
    repos, error = _setup_gh_repos(env)
    if repos is None:
        return {"ok": False, "error": error or "could not list your GitHub repos"}
    owner = _repo_owner(repos[0]["url"]) if repos else ""
    deadline = started + CANDIDATES_DEADLINE_SECONDS

    definitive: set[str] = set()
    search_timeout = max(0.5, min(CANDIDATES_API_TIMEOUT, deadline - time.monotonic()))
    found = _gh_search_recipe_repos(owner, env, search_timeout)
    if found:
        definitive.update(repo["name"] for repo in repos if repo["name"] in found)

    remaining = [repo for repo in repos if repo["name"] not in definitive]
    recipe_results, recipe_pending = _run_with_deadline(
        [(owner, repo["name"]) for repo in remaining],
        lambda pair: _gh_repo_has_recipe(pair[0], pair[1], env, CANDIDATES_API_TIMEOUT),
        deadline,
    )
    definitive.update(
        name for (owner_name, name), value in recipe_results.items() if value is True
    )

    shape_targets = [repo for repo in remaining if repo["name"] not in definitive]
    shape_results, shape_pending = _run_with_deadline(
        [(owner, repo["name"]) for repo in shape_targets],
        lambda pair: _gh_repo_tree_paths(pair[0], pair[1], env, CANDIDATES_API_TIMEOUT),
        deadline,
    )
    likely: set[str] = set()
    for (_owner_name, name), entries in shape_results.items():
        if _repo_looks_like_stow(entries):
            likely.add(name)

    def make_entry(repo: dict[str, Any], tier: str) -> dict[str, Any]:
        return {
            "name": repo["name"],
            "url": repo["url"],
            "private": bool(repo["private"]),
            "hint": _repo_hint(repo),
            "tier": tier,
            "detail": {"definitive": "setup recipe", "likely": "stow-like"}.get(tier, ""),
        }

    return {
        "ok": True,
        "owner": owner,
        "definitive": [make_entry(r, "definitive") for r in repos if r["name"] in definitive],
        "likely": [
            make_entry(r, "likely")
            for r in repos
            if r["name"] in likely and r["name"] not in definitive
        ],
        "others": [
            make_entry(r, "other")
            for r in repos
            if r["name"] not in definitive and r["name"] not in likely
        ],
        "took_ms": int((time.monotonic() - started) * 1000),
        "partial": bool(recipe_pending) or bool(shape_pending),
    }


def cmd_setup_fixture(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Hidden live-check hook: return a recorded JSON file verbatim, read-only.

    Mirrors ``setup-plan --fixture`` (README 8b/11): the panel uses it to render
    the Report step from a recorded apply result without ever running a setup on
    the real ``$HOME``. Removed before the marketplace submission.
    """
    path_arg = opt_value(args, "--path")
    if not _setup_str(path_arg):
        raise CommandError("missing --path")
    path = expand_path(path_arg)
    if not os.path.isfile(path):
        raise CommandError("fixture not found: " + to_tilde(path))
    if os.path.getsize(path) > MAX_RESPONSE_BYTES:
        raise CommandError("fixture is too large")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError("fixture is not valid JSON: " + _shorten(str(exc)))
    return {"ok": True, "data": data}


def _classify_conflict(entry: dict[str, str]) -> dict[str, Any]:
    """Classify one parsed stow conflict as identical / different / blocked."""
    base = {"target": entry["target"], "source": entry["source"], "message": entry["message"]}
    target = entry["target_abs"]
    if entry["form"] == "not-owned":
        return {**base, "kind": "blocked", "reason": "target is a symlink not owned by stow"}
    if os.path.islink(target):
        return {**base, "kind": "blocked", "reason": "target is a symlink"}
    if os.path.isdir(target):
        return {**base, "kind": "different"}
    source = entry.get("source_abs") or ""
    if source and os.path.isfile(source) and os.path.isfile(target):
        try:
            if sha256_file(target) == sha256_file(source):
                return {**base, "kind": "identical"}
        except OSError:
            pass
    return {**base, "kind": "different"}


def classify_setup_package(repo_path: str, target_dir: str, package: str) -> dict[str, Any]:
    """Dry-run one package and classify it: already / new / conflicts / blocked."""
    dry = stow_dry_run(repo_path, target_dir, package)
    text = _decode(dry.stderr)
    raw = parse_conflict_entries(text, target_dir)
    if not raw and dry.returncode == 0:
        pending = parse_pending_links(text, target_dir)
        if pending:
            return {"status": "new", "links": pending, "conflicts": []}
        return {"status": "already", "links": [], "conflicts": []}
    classified = [_classify_conflict(entry) for entry in raw]
    if not classified:
        return {
            "status": "blocked",
            "links": [],
            "conflicts": [
                {
                    "target": "",
                    "source": "",
                    "message": _short_error(dry),
                    "kind": "blocked",
                    "reason": "stow reported a failure it did not classify",
                }
            ],
        }
    blocked = [c for c in classified if c["kind"] == "blocked"]
    return {"status": "blocked" if blocked else "conflicts", "links": [], "conflicts": classified}


def _systemctl_state(unit: str) -> str | None:
    """``systemctl --user is-enabled`` state, or ``None`` when undetectable."""
    try:
        result = run_bounded(["systemctl", "--user", "is-enabled", unit], 10)
    except (subprocess.TimeoutExpired, OSError):
        return None
    state = _decode(result.stdout).strip()
    return state or "not-found"


def _build_setup_services(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for unit in recipe["services"]:
        state = _systemctl_state(unit)
        if state is None or state == "enabled":
            continue
        services.append({"unit": unit, "enabled": False, "state": state})
    return services


def _build_setup_requires(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name in recipe["requires"]:
        found = shutil.which(name)
        entries.append({"name": name, "found": found is not None, "path": found})
    return entries


def build_setup_plan(recipe: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic setup plan (README section 8a step 1)."""
    target_dir = os.path.expanduser("~")
    skip = set(recipe["skip_packages"])
    clone: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for repo in sorted(recipe["repos"], key=lambda item: item["order"]):
        repo_path = expand_path(repo["path"])
        if not os.path.isdir(repo_path):
            clone.append(
                {
                    "path": to_tilde(repo_path),
                    "url": repo["url"],
                    "order": repo["order"],
                    "private": repo["private"],
                }
            )
            continue
        if repo["packages"] == "auto":
            packages = detect_packages(repo_path)
        else:
            packages = list(repo["packages"])
        for package in packages:
            if package in skip:
                continue
            result = classify_setup_package(repo_path, target_dir, package)
            links.append(
                {
                    "repo": to_tilde(repo_path),
                    "package": package,
                    "status": result["status"],
                    "links": result["links"],
                    "conflicts": result["conflicts"],
                    "files_to_backup": sum(
                        1 for c in result["conflicts"] if c["kind"] in ("identical", "different")
                    ),
                }
            )
    services = _build_setup_services(recipe)
    requires = _build_setup_requires(recipe)
    post: list[dict[str, Any]] = []
    for entry in recipe["post"]:
        needs = list(entry.get("needs", []))
        missing = [name for name in needs if shutil.which(name) is None]
        available = not missing
        # An unavailable step is never enabled by default (README 10a.3), but it
        # stays in the plan so the Review can show it disabled with "needs X".
        post.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "argv": list(entry["argv"]),
                "timeout_s": entry["timeout_s"],
                "needs": needs,
                "available": available,
                "missing": missing,
                "default": bool(entry.get("default")) and available,
            }
        )
    summary = {
        "repos_to_clone": len(clone),
        "packages_to_link": sum(1 for l in links if l["status"] in ("new", "conflicts")),
        "files_to_backup": sum(l["files_to_backup"] for l in links),
        "blocked_packages": sum(1 for l in links if l["status"] == "blocked"),
        "services_to_enable": len(services),
        "missing_tools": sum(1 for r in requires if not r["found"]),
    }
    summary["nothing_to_do"] = (
        summary["repos_to_clone"] == 0
        and summary["packages_to_link"] == 0
        and summary["files_to_backup"] == 0
        and summary["blocked_packages"] == 0
    )
    return {
        "version": SETUP_RECIPE_VERSION,
        "clone": clone,
        "link": links,
        "services": services,
        "requires": requires,
        "post": post,
        "notes": list(recipe["notes"]),
        "summary": summary,
    }


def setup_plan_path(state_dir: str) -> str:
    return os.path.join(state_dir, SETUP_PLAN_FILENAME)


def _setup_plan_canonical(plan: dict[str, Any]) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def _setup_plan_token(canonical: str, created: str) -> str:
    return hashlib.sha256((canonical + "|" + created).encode("utf-8")).hexdigest()


def save_setup_plan(state_dir: str, recipe_path: str, plan: dict[str, Any]) -> tuple[str, str]:
    """Persist the plan token (dir 0700, file 0600, atomic) and return it."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    canonical = _setup_plan_canonical(plan)
    token = _setup_plan_token(canonical, created)
    os.makedirs(state_dir, 0o700, exist_ok=True)
    _write_json_atomic(
        setup_plan_path(state_dir),
        {
            "version": SETUP_RECIPE_VERSION,
            "token": token,
            "created": created,
            "canonical": canonical,
            "plan": plan,
            "recipe_path": recipe_path,
        },
        0o600,
        prefix=".setup-plan-",
    )
    return token, created


def _load_setup_plan(state_dir: str) -> dict[str, Any] | None:
    path = setup_plan_path(state_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _default_recipe_path() -> str:
    return setup_recipe_file(os.path.expanduser(os.path.join("~", ".dotfiles")))


def cmd_setup_plan(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Build the setup plan and store its 10-minute token (README 8.1/8a)."""
    fixture = opt_value(args, "--fixture")
    if _setup_str(fixture):
        # Hidden setupFixture setting (README 8b live check): read a recorded
        # plan, never write a token and never apply.
        try:
            with open(expand_path(fixture), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise CommandError("fixture read failed: " + _shorten(str(exc)))
        if not isinstance(data, dict):
            raise CommandError("fixture is not a plan object")
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        return {
            "ok": True,
            "token": "fixture",
            "created": None,
            "recipe": None,
            "plan": data,
            "summary": summary,
            "fixture": True,
        }
    recipe_arg = opt_value(args, "--recipe")
    recipe_path = expand_path(recipe_arg) if recipe_arg else _default_recipe_path()
    recipe = load_setup_recipe_file(recipe_path)
    plan = build_setup_plan(recipe)
    state = resolve_state_dir(state_dir)
    token, created = save_setup_plan(state, recipe_path, plan)
    return {
        "ok": True,
        "token": token,
        "created": created,
        "recipe": to_tilde(recipe_path),
        "plan": plan,
        "summary": plan["summary"],
    }


def _new_backup_id(state_dir: str) -> str:
    base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = os.path.join(state_dir, SETUP_BACKUPS_DIRNAME)
    candidate = base
    suffix = 1
    while os.path.exists(os.path.join(root, candidate)):
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _path_type_info(path: str) -> dict[str, Any]:
    st = os.lstat(path)
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        return {
            "type": "symlink",
            "mode": format(stat.S_IMODE(mode), "04o"),
            "sha256": None,
            "link_target": os.readlink(path),
        }
    if stat.S_ISDIR(mode):
        return {
            "type": "dir",
            "mode": format(stat.S_IMODE(mode), "04o"),
            "sha256": None,
            "link_target": None,
        }
    sha = sha256_file(path) if stat.S_ISREG(mode) else None
    return {
        "type": "file",
        "mode": format(stat.S_IMODE(mode), "04o"),
        "sha256": sha,
        "link_target": None,
    }


def _setup_perform_move(src: str, dst: str) -> None:
    """Move ``src`` onto ``dst`` on the same filesystem, preserving type/mode.

    Refuses when ``dst`` already exists: a ``shutil.move`` fallback would place
    the source *inside* an existing destination directory, so a backup would
    land at a nested wrong path and undo could not find it. A cross-filesystem
    move is refused too — the backup folder must live on the same filesystem as
    ``$HOME`` (README section 8a apply).
    """
    if os.path.lexists(dst):
        raise CommandError(
            "refusing to overwrite an existing path: " + dst + " (moving " + src + ")"
        )
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise CommandError(
                "cannot move across filesystems (backups must live on the same "
                "filesystem as $HOME): " + src + " -> " + dst
            )
        raise


def _setup_backup_one(
    manifest: dict[str, Any],
    manifest_path: str,
    backup_root: str,
    target_abs: str,
    home: str,
) -> dict[str, Any]:
    """Record one conflict move in the manifest, fsync, then perform the move.

    The manifest is written *before* the move so a crash mid-apply is undoable
    (README section 8a step 3).
    """
    rel = os.path.relpath(target_abs, home)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        raise CommandError("refusing to back up a path outside $HOME: " + target_abs)
    info = _path_type_info(target_abs)
    move = {
        "path": to_tilde(target_abs),
        "backup": rel,
        "type": info["type"],
        "mode": info["mode"],
        "sha256": info["sha256"],
        "link_target": info["link_target"],
    }
    if move not in manifest["moves"]:
        manifest["moves"].append(move)
    _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)
    backup_path = os.path.join(backup_root, "files", rel)
    _setup_perform_move(target_abs, backup_path)
    return move


def _setup_move_back(
    manifest: dict[str, Any],
    manifest_path: str,
    backup_root: str,
    move: dict[str, Any],
    target_abs: str,
) -> None:
    """Restore one backup, removing an apply-created symlink first."""
    backup_path = os.path.join(backup_root, "files", move["backup"])
    if os.path.islink(target_abs):
        os.unlink(target_abs)
    if os.path.lexists(backup_path):
        os.makedirs(os.path.dirname(target_abs) or ".", exist_ok=True)
        _setup_perform_move(backup_path, target_abs)
    if move in manifest["moves"]:
        manifest["moves"].remove(move)


def _setup_rollback_moves(
    manifest: dict[str, Any],
    manifest_path: str,
    backup_root: str,
    moves: list[dict[str, Any]],
) -> None:
    for move in reversed(moves):
        try:
            _setup_move_back(manifest, manifest_path, backup_root, move, expand_path(move["path"]))
        except OSError:
            continue
    _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)


def _is_apply_link(target: Any, repo_path: str) -> bool:
    path = expand_path(target) if isinstance(target, str) else ""
    if not path or not os.path.islink(path):
        return False
    real = os.path.realpath(path)
    return _under(real, os.path.realpath(repo_path))


def _path_matches_move(move: dict[str, Any], path: str) -> bool:
    if not os.path.lexists(path):
        return False
    kind = move.get("type")
    if kind == "symlink":
        return os.path.islink(path) and os.readlink(path) == move.get("link_target")
    if kind == "dir":
        return os.path.isdir(path) and not os.path.islink(path)
    if os.path.islink(path) or not os.path.isfile(path):
        return False
    recorded = move.get("sha256")
    return recorded is None or sha256_file(path) == recorded


def setup_progress_path(state_dir: str) -> str:
    return os.path.join(state_dir, SETUP_PROGRESS_FILENAME)


_CLONE_PROGRESS_RE = re.compile(
    r"(Receiving objects|Resolving deltas|Compressing objects|Counting objects|Enumerating objects):\s*(\d+)%"
    r"(?:\s*\((\d+)/(\d+)\))?(?:\s*,\s*([0-9.]+\s*[KMGT]?i?B))?"
)


def parse_git_clone_progress(text: str) -> dict[str, Any] | None:
    """Last progress tuple in ``git clone --progress`` stderr (README 11b.2).

    Git writes one ``\\r``-updated line per phase, e.g.
    ``Receiving objects:  45% (1234/2742), 410.20 MiB | 5.2 MiB/s``. Returns the
    last seen ``{phase, percent, size}``, or ``None`` when there is none.
    """
    last: dict[str, Any] | None = None
    for chunk in re.split(r"[\r\n]", text or ""):
        match = _CLONE_PROGRESS_RE.search(chunk)
        if match:
            last = {
                "phase": match.group(1),
                "percent": int(match.group(2)),
                "size": (match.group(5) or "").strip(),
            }
    return last


def write_clone_progress(
    state_dir: str, item: str, progress: dict[str, Any] | None, state: str
) -> None:
    """Write one repo's clone progress to ``setup-progress.json`` (README 11b.2)."""
    finished = state in ("done", "failed")
    payload = {
        "version": 1,
        "phase": "clone",
        "item": str(item),
        "done": 1 if state == "done" else 0,
        "total": 1,
        "percent": (progress or {}).get("percent"),
        "size": (progress or {}).get("size", ""),
        "state": str(state),
        "items": [{"kind": "clone", "id": str(item), "state": str(state)}],
    }
    try:
        os.makedirs(state_dir, 0o700, exist_ok=True)
        _write_json_atomic(setup_progress_path(state_dir), payload, 0o600, prefix=".progress-")
    except OSError:
        pass
    _ = finished


def _refuse_real_setup(state_dir: str | None, command: str) -> dict[str, Any] | None:
    """Refuse a mutating setup command on the real HOME unless opted in.

    Defence in depth for incident 2026-10-10 (README 10.0): the panel passes an
    explicit ``--state-dir`` (test or configured) or sets
    ``STOW_SYNC_ALLOW_REAL_SETUP=1`` on its real request path. A stray call with
    neither must never touch the real HOME.
    """
    if state_dir is None and os.environ.get("STOW_SYNC_ALLOW_REAL_SETUP") != "1":
        return {
            "ok": False,
            "error": command
            + " needs an explicit --state-dir (or STOW_SYNC_ALLOW_REAL_SETUP=1)",
        }
    return None


def write_setup_progress(
    state_dir: str, phase: str, current: str, items: list[dict[str, Any]]
) -> None:
    """Atomically write per-item setup progress (README 11a.4).

    The panel watches this file to tick the Apply checklist as items finish. A
    write failure is never fatal — progress is best-effort UI feedback.
    """
    finished = ("done", "failed", "skipped")
    done = sum(1 for item in items if item.get("state") in finished)
    payload = {
        "version": 1,
        "phase": str(phase),
        "item": str(current),
        "done": done,
        "total": len(items),
        "items": [
            {
                "kind": str(item.get("kind", "")),
                "id": str(item.get("id", "")),
                "state": str(item.get("state", "waiting")),
            }
            for item in items
        ],
    }
    try:
        os.makedirs(state_dir, 0o700, exist_ok=True)
        _write_json_atomic(setup_progress_path(state_dir), payload, 0o600, prefix=".progress-")
    except OSError:
        pass


def _selected_post_commands(plan: dict[str, Any], args: list[str]) -> list[dict[str, Any]]:
    override = opt_value(args, "--post")
    if override is not None:
        wanted = [part.strip() for part in override.split(",") if part.strip()]
        by_id = {entry["id"]: entry for entry in plan["post"]}
        return [by_id[i] for i in wanted if i in by_id]
    return [entry for entry in plan["post"] if entry.get("default")]


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# Progress-bar block glyphs a tool like mise prints inline (README 11d.2).
_PROGRESS_GLYPHS = frozenset("\u2588\u2589\u258a\u258b\u258c\u258d\u258e\u258f\u2591\u2592\u2593")


def clean_output_text(text: str, limit: int = 200) -> str:
    """Strip ANSI codes, CR segments and progress-bar glyphs from one line.

    A tool that redraws progress with ``\\r`` leaves several segments; only the
    last one is meaningful, so everything before the final ``\\r`` is dropped
    (README 11d.2 / finding 42). Runs of whitespace collapse to one space.
    """
    cleaned = _ANSI_RE.sub("", text or "")
    if "\r" in cleaned:
        cleaned = cleaned.rsplit("\r", 1)[-1]
    cleaned = "".join(ch for ch in cleaned if ch not in _PROGRESS_GLYPHS)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def _last_nonempty_line(text: str, limit: int = 200) -> str | None:
    """The last non-empty cleaned line of a process' output, capped at ``limit``."""
    for raw in reversed((text or "").splitlines()):
        cleaned = clean_output_text(raw, limit)
        if cleaned:
            return cleaned
    return None


def _run_setup_post(
    plan: dict[str, Any], args: list[str], home: str, on_step: Any = None
) -> list[dict[str, Any]]:
    """Run the selected post steps, skipping any whose ``needs`` are missing.

    Every result carries ``state`` (``ran``/``failed``/``skipped``), ``exit``
    and ``last_line`` so the UI can show what each step actually did (README
    10a.3/10a.4). ``on_step(id, state)`` is called as each step starts and
    finishes so the caller can stream progress (README 11a.4).
    """
    results: list[dict[str, Any]] = []
    for entry in _selected_post_commands(plan, args):
        if entry.get("available") is False:
            missing = entry.get("missing") or []
            reason = ("needs " + ", ".join(missing)) if missing else "unavailable"
            results.append(
                {
                    "id": entry["id"],
                    "ok": False,
                    "state": "skipped",
                    "exit": None,
                    "last_line": None,
                    "reason": reason,
                    "error": None,
                }
            )
            if on_step:
                on_step(entry["id"], "skipped")
            continue
        if on_step:
            on_step(entry["id"], "running")
        argv = [expand_path(part) for part in entry["argv"]]
        timeout = entry.get("timeout_s", 300)
        try:
            result = run_bounded(argv, timeout, cwd=home, env=os.environ.copy())
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "id": entry["id"],
                    "ok": False,
                    "state": "failed",
                    "exit": None,
                    "last_line": None,
                    "reason": None,
                    "error": f"post command timed out after {timeout}s",
                }
            )
            if on_step:
                on_step(entry["id"], "failed")
            continue
        except OSError as exc:
            results.append(
                {
                    "id": entry["id"],
                    "ok": False,
                    "state": "failed",
                    "exit": None,
                    "last_line": None,
                    "reason": None,
                    "error": _shorten(str(exc)),
                }
            )
            if on_step:
                on_step(entry["id"], "failed")
            continue
        combined = _decode(result.stdout) + "\n" + _decode(result.stderr)
        ok = result.returncode == 0
        results.append(
            {
                "id": entry["id"],
                "ok": ok,
                "state": "ran" if ok else "failed",
                "exit": result.returncode,
                "last_line": _last_nonempty_line(combined),
                "reason": None,
                "error": None if ok else _short_error(result),
            }
        )
        if on_step:
            on_step(entry["id"], "done" if ok else "failed")
    return results


def cmd_setup_apply(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Apply a reviewed plan, backing up every conflict first (README 8a)."""
    refusal = _refuse_real_setup(state_dir, "setup-apply")
    if refusal is not None:
        return refusal
    token_arg = opt_value(args, "--token")
    state = resolve_state_dir(state_dir)
    stored = _load_setup_plan(state)
    if not token_arg or not stored:
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    required = ("token", "created", "canonical", "plan")
    if any(not stored.get(key) for key in required) or not isinstance(stored.get("plan"), dict):
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    try:
        created_dt = datetime.fromisoformat(str(stored["created"]))
    except (TypeError, ValueError):
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created_dt).total_seconds()
    if age < 0 or age > SETUP_PLAN_TTL_SECONDS:
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    if token_arg != stored["token"]:
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    if _setup_plan_token(str(stored["canonical"]), str(stored["created"])) != stored["token"]:
        return {"ok": False, "error": SETUP_PLAN_ERROR}

    recipe_path = stored.get("recipe_path") or opt_value(args, "--recipe")
    if not _setup_str(recipe_path):
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    try:
        recipe = load_setup_recipe_file(expand_path(recipe_path))
        fresh_plan = build_setup_plan(recipe)
    except CommandError:
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    if _setup_plan_canonical(fresh_plan) != stored["canonical"]:
        return {"ok": False, "error": SETUP_PLAN_ERROR}
    plan = stored["plan"]

    # Per-item progress for the panel's live Apply checklist (README 11a.4).
    progress_items: list[dict[str, Any]] = []
    for link in plan.get("link", []):
        progress_items.append(
            {"kind": "package", "id": link["repo"] + " \u00b7 " + link["package"], "state": "waiting"}
        )
    for service in plan.get("services", []):
        progress_items.append({"kind": "service", "id": service["unit"], "state": "waiting"})
    for post_step in _selected_post_commands(plan, args):
        progress_items.append({"kind": "post", "id": post_step["id"], "state": "waiting"})

    def mark_progress(kind: str, item_id: str, item_state: str) -> None:
        for item in progress_items:
            if item["kind"] == kind and item["id"] == item_id:
                item["state"] = item_state
        write_setup_progress(state, "apply", item_id, progress_items)

    write_setup_progress(state, "apply", "", progress_items)

    home = os.path.expanduser("~")
    backup_id = _new_backup_id(state)
    backup_root = os.path.join(state, SETUP_BACKUPS_DIRNAME, backup_id)
    os.makedirs(backup_root, 0o700, exist_ok=True)
    manifest_path = os.path.join(backup_root, "manifest.json")
    manifest: dict[str, Any] = {
        "version": 1,
        "id": backup_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "home": home,
        "target": "~",
        "moves": [],
        "packages": [],
        "services": [],
        "post": [],
    }
    _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)

    # Apply never clones: a repo must already be on disk from Connect, so the
    # reviewed plan is the only thing that runs. A repo still missing at apply
    # time is reported and left untouched (README section 8a apply).
    skipped: list[dict[str, Any]] = []
    for entry in plan.get("clone", []):
        skipped.append(
            {
                "path": entry["path"],
                "url": entry.get("url"),
                "status": "repo-missing",
                "reason": "Run Connect again",
            }
        )

    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for link in plan.get("link", []):
        repo_path = expand_path(link["repo"])
        target_dir = home
        pid = link["repo"] + " \u00b7 " + link["package"]
        if link["status"] == "already":
            skipped.append({"repo": link["repo"], "package": link["package"], "status": "already"})
            packages.append(
                {"repo": link["repo"], "package": link["package"], "state": "already"}
            )
            mark_progress("package", pid, "done")
            continue
        if link["status"] == "blocked":
            skipped.append(
                {
                    "repo": link["repo"],
                    "package": link["package"],
                    "status": link["status"],
                    "conflicts": link["conflicts"],
                }
            )
            packages.append(
                {"repo": link["repo"], "package": link["package"], "state": "blocked"}
            )
            mark_progress("package", pid, "failed")
            continue
        mark_progress("package", pid, "running")
        pkg_moves: list[dict[str, Any]] = []
        for conflict in link.get("conflicts", []):
            if conflict["kind"] == "blocked":
                continue
            target_abs = expand_path(conflict["target"])
            pkg_moves.append(_setup_backup_one(manifest, manifest_path, backup_root, target_abs, home))
        try:
            real = stow_real(repo_path, target_dir, link["package"])
            stow_error: str | None = None if real.returncode == 0 else _short_error(real)
        except subprocess.TimeoutExpired:
            stow_error = "stow timed out"
        if stow_error is not None:
            _setup_rollback_moves(manifest, manifest_path, backup_root, pkg_moves)
            failed.append({"repo": link["repo"], "package": link["package"], "error": stow_error})
            packages.append(
                {"repo": link["repo"], "package": link["package"], "state": "failed"}
            )
            manifest["packages"].append(
                {"repo": link["repo"], "package": link["package"], "status": "failed"}
            )
            _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)
            mark_progress("package", pid, "failed")
            continue
        actions = parse_stow_actions(_decode(real.stderr), target_dir)
        applied.append(
            {
                "repo": link["repo"],
                "package": link["package"],
                "status": "applied",
                "actions": actions,
                "files_backed_up": len(pkg_moves),
            }
        )
        packages.append({"repo": link["repo"], "package": link["package"], "state": "applied"})
        manifest["packages"].append(
            {
                "repo": link["repo"],
                "package": link["package"],
                "status": "applied",
                "targets": [move["path"] for move in pkg_moves],
            }
        )
        _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)
        mark_progress("package", pid, "done")

    services_results: list[dict[str, Any]] = []
    if plan.get("services"):
        try:
            run_bounded(["systemctl", "--user", "daemon-reload"], 30)
        except (subprocess.TimeoutExpired, OSError):
            pass
        for service in plan["services"]:
            unit = service["unit"]
            error: str | None = None
            mark_progress("service", unit, "running")
            try:
                result = run_bounded(["systemctl", "--user", "enable", "--now", unit], 60)
                ok = result.returncode == 0
                if not ok:
                    error = _short_error(result)
            except subprocess.TimeoutExpired:
                ok = False
                error = "systemctl timed out"
            except OSError as exc:
                ok = False
                error = _shorten(str(exc))
            services_results.append(
                {"unit": unit, "ok": ok, "state": "enabled" if ok else "failed", "error": error}
            )
            manifest["services"].append({"unit": unit, "ok": ok})
            mark_progress("service", unit, "done" if ok else "failed")
    _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)

    config_targets = {os.path.normpath(default_config_path())}
    if config_path:
        config_targets.add(os.path.normpath(expand_path(config_path)))
    replaced = {os.path.normpath(expand_path(move["path"])) for move in manifest["moves"]}
    config_reloaded = False
    if replaced & config_targets:
        try:
            load_config(config_path)
            config_reloaded = True
        except (OSError, ValueError):
            config_reloaded = False

    post_results = _run_setup_post(
        plan, args, home, on_step=lambda pid, state: mark_progress("post", pid, state)
    )
    manifest["post"] = [{"id": entry["id"], "ok": entry["ok"]} for entry in post_results]
    _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)

    moved = [
        {"path": move["path"], "backup": os.path.join(backup_root, "files", move["backup"])}
        for move in manifest["moves"]
    ]
    return {
        "ok": True,
        "backup": backup_id,
        "backup_dir": backup_root,
        "applied": applied,
        "failed": failed,
        "skipped": skipped,
        "packages": packages,
        "moved": moved,
        "services": services_results,
        "post": post_results,
        "notes": list(plan.get("notes", [])),
        "config_reloaded": config_reloaded,
        "summary": {
            "applied": len(applied),
            "failed": len(failed),
            "skipped": len(skipped),
            "backups": len(manifest["moves"]),
        },
    }


def cmd_setup_undo(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Un-stow this apply's packages and restore every backup (README 8a)."""
    refusal = _refuse_real_setup(state_dir, "setup-undo")
    if refusal is not None:
        return refusal
    backup_id = opt_value(args, "--backup")
    if not _setup_str(backup_id):
        raise CommandError("missing --backup")
    state = resolve_state_dir(state_dir)
    backup_root = os.path.join(state, SETUP_BACKUPS_DIRNAME, backup_id)
    manifest_path = os.path.join(backup_root, "manifest.json")
    if not os.path.isfile(manifest_path):
        return {"ok": False, "error": "unknown backup: " + str(backup_id)}
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": "cannot read backup: " + _shorten(str(exc))}
    home = manifest.get("home") or os.path.expanduser("~")
    target_dir = expand_path(manifest.get("target", "~")) or home
    if manifest.get("undone"):
        return {"ok": False, "error": "already undone: " + str(backup_id)}

    # Undo must disable every service the apply enabled BEFORE unstowing, or the
    # `*.wants` symlink is left dangling once the unit is unstowed (finding 28).
    services_disabled: list[dict[str, Any]] = []
    for service in manifest.get("services", []):
        unit = service.get("unit")
        if not unit:
            continue
        error: str | None = None
        try:
            result = run_bounded(["systemctl", "--user", "disable", "--now", unit], 60)
            ok = result.returncode == 0
            if not ok:
                error = _short_error(result)
        except subprocess.TimeoutExpired:
            ok = False
            error = "systemctl timed out"
        except OSError as exc:
            ok = False
            error = _shorten(str(exc))
        services_disabled.append({"unit": unit, "ok": ok, "error": error})

    unstowed: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    refused_paths: set[str] = set()
    for pkg in manifest.get("packages", []):
        if pkg.get("status") != "applied":
            continue
        repo_path = expand_path(pkg["repo"])
        bad = [t for t in pkg.get("targets", []) if not _is_apply_link(t, repo_path)]
        if bad:
            refused.append(
                {"repo": pkg["repo"], "package": pkg["package"], "paths": bad}
            )
            for path in bad:
                refused_paths.add(os.path.normpath(expand_path(path)))
            continue
        try:
            result = run_bounded(
                ["stow", "-D", "-v", "-d", repo_path, "-t", target_dir, pkg["package"]],
                30,
                env=stow_env(),
            )
        except subprocess.TimeoutExpired:
            refused.append({"repo": pkg["repo"], "package": pkg["package"], "error": "stow timed out"})
            continue
        if result.returncode != 0:
            refused.append(
                {"repo": pkg["repo"], "package": pkg["package"], "error": _short_error(result)}
            )
            continue
        unstowed.append({"repo": pkg["repo"], "package": pkg["package"]})

    restored: list[str] = []
    errors: list[dict[str, Any]] = []
    for move in manifest.get("moves", []):
        target_abs = expand_path(move["path"])
        if os.path.normpath(target_abs) in refused_paths:
            errors.append({"path": move["path"], "error": "destination is not this apply's symlink"})
            continue
        backup_path = os.path.join(backup_root, "files", move["backup"])
        try:
            if not os.path.lexists(backup_path):
                if os.path.islink(target_abs):
                    raise CommandError("backup is missing")
                continue
            if os.path.islink(target_abs):
                os.unlink(target_abs)
            if os.path.lexists(target_abs):
                if _path_matches_move(move, target_abs):
                    restored.append(move["path"])
                    continue
                raise CommandError("destination changed")
            os.makedirs(os.path.dirname(target_abs) or ".", exist_ok=True)
            _setup_perform_move(backup_path, target_abs)
            if not _path_matches_move(move, target_abs):
                raise CommandError("restored bytes differ")
            restored.append(move["path"])
        except (OSError, CommandError) as exc:
            errors.append({"path": move["path"], "error": _shorten(str(exc))})

    if services_disabled:
        try:
            run_bounded(["systemctl", "--user", "daemon-reload"], 30)
        except (subprocess.TimeoutExpired, OSError):
            pass
    if not refused and not errors:
        manifest["undone"] = True
        _write_json_atomic(manifest_path, manifest, 0o600, prefix=".manifest-", fsync=True)

    return {
        "ok": True,
        "backup": backup_id,
        "unstowed": unstowed,
        "refused": refused,
        "restored": restored,
        "errors": errors,
        "services_disabled": services_disabled,
    }


def cmd_setup_backups(
    args: list[str],
    config_path: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """List the backups under ``<state_dir>/setup-backups`` (read-only)."""
    state = resolve_state_dir(state_dir)
    root = os.path.join(state, SETUP_BACKUPS_DIRNAME)
    backups: list[dict[str, Any]] = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            manifest_path = os.path.join(root, name, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            backups.append(
                {
                    "id": name,
                    "created": data.get("created"),
                    "undone": bool(data.get("undone", False)),
                    "counts": {
                        "packages": len(data.get("packages", [])),
                        "moved": len(data.get("moves", [])),
                        "services": len(data.get("services", [])),
                    },
                }
            )
    return {"ok": True, "backups": backups}


COMMANDS = {
    "version": cmd_version,
    "setup-prereqs": cmd_setup_prereqs,
    "setup-repos": cmd_setup_repos,
    "setup-candidates": cmd_setup_candidates,
    "setup-fixture": cmd_setup_fixture,
    "setup-connect": cmd_setup_connect,
    "setup-clone": cmd_setup_clone,
    "setup-plan": cmd_setup_plan,
    "setup-apply": cmd_setup_apply,
    "setup-undo": cmd_setup_undo,
    "setup-backups": cmd_setup_backups,
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
