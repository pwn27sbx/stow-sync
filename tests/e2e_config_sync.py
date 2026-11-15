#!/usr/bin/env python3
"""End-to-end check of config-sync awareness (S1-S3), driven like the panel.

Builds a throwaway world under a temp HOME and runs the real CLI against it:
a genuine Stow repo with three packages, a real config-sync clone at its
default path, a `.omarchy-config.json` marker with `machine_local`, and the
home files the owner's machine really has (terminal folders, a stray kitty
`*.bak.*`, a `*.bak` only config-sync skips, a symlinked parent, a secret in
an owned file, a `machine_local` path and one real crossing).

Then it drives the CLI exactly as the panel does — `status`, `status --short`,
`adopt --dry-run`, `skip --path`, `ignore` — and asserts every verdict, reason,
the Hidden group, the "Also carried by config-sync" group and the badge,
through `Model.js` for the panel-side facts. A second world without
config-sync proves the absence case still yields today's payload shape.

Read-only for the owner's machine: everything happens inside the temp root,
and every desktop command is a stub that logs a call and fails the run.

    python3 tests/e2e_config_sync.py [--keep]

Exits 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "scripts" / "stow_sync.py"
MODEL = REPO / "Model.js"
FIXTURE = REPO / "tests" / "fixtures" / "status-candidates.json"
CONFIG_SYNC_REASON = "Managed by config-sync"

ROWS: list[tuple[str, str, str, bool]] = []
FAILED: list[str] = []


# --------------------------------------------------------------------------
# Small helpers: assertions, git, stow, CLI
# --------------------------------------------------------------------------


def check(name: str, observed, expected) -> None:
    ok = observed == expected
    ROWS.append((name, _short(expected), _short(observed), ok))
    if not ok:
        FAILED.append(name)


def check_true(name: str, observed) -> None:
    check(name, bool(observed), True)


def _short(value, limit: int = 96) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def git_env(root: Path) -> dict[str, str]:
    """Git isolated from the host: no global config, identity, or hooks."""
    empty = root / "gitconfig-empty"
    empty.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Owner",
            "GIT_AUTHOR_EMAIL": "owner@example.com",
            "GIT_COMMITTER_NAME": "Owner",
            "GIT_COMMITTER_EMAIL": "owner@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty),
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def git(root: Path, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=git_env(root),
    )


def init_repo(root: Path, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True, env=git_env(root)
    )


def commit_all(root: Path, repo: Path, message: str) -> None:
    git(root, repo, "add", "-A")
    git(root, repo, "commit", "-m", message)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o644)


class World:
    """One temp HOME with a Stow repo, home files and (optionally) config-sync."""

    def __init__(self, config_sync: bool, seeded_baseline: bool = True) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="stow-sync-e2e-"))
        self.home = self.root / "home"
        self.home.mkdir()
        self.xdg = self.root / "xdg-data"
        self.xdg.mkdir()
        # The panel runs the CLI with no flags: the real default paths apply.
        self.config = self.home / ".config" / "stow-sync" / "config.json"
        self.state = self.home / ".local" / "state" / "stow-sync"
        self.state.mkdir(parents=True)
        self.stub = self.root / "stub-bin"
        self.stub.mkdir()
        self.stub_log = self.root / "desktop-calls.log"
        self._stub_desktop_commands()
        self.dotfiles = self.root / "dotfiles"
        self._build(config_sync, seeded_baseline)

    # The panel never talks to a desktop directly; any call is a defect here.
    def _stub_desktop_commands(self) -> None:
        for name in (
            "hyprctl",
            "omarchy-shell",
            "omarchy-restart-waybar",
            "omarchy-restart-hyprctl",
            "notify-send",
        ):
            path = self.stub / name
            path.write_text(
                "#!/bin/sh\n" 'printf "%s\\n" "$(basename "$0")" >> ' + str(self.stub_log) + "\n",
                encoding="utf-8",
            )
            path.chmod(0o755)

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "XDG_DATA_HOME": str(self.xdg),
                "PATH": str(self.stub) + os.pathsep + env.get("PATH", ""),
            }
        )
        env.pop("STOW_SYNC_STATE_DIR", None)
        env.pop("XDG_CONFIG_HOME", None)
        empty = self.root / "gitconfig-empty"
        if not empty.exists():
            empty.write_text("", encoding="utf-8")
        env["GIT_CONFIG_GLOBAL"] = str(empty)
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Owner"
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "owner@example.com"
        return env

    def _build(self, config_sync: bool, seeded_baseline: bool) -> None:
        home = self.home
        # A genuine Stow repo: three packages, all stowed, committed and clean.
        init_repo(self.root, self.dotfiles)
        write(self.dotfiles / "fish" / ".config" / "fish" / "config.fish", "set -g fish_greeting ''\n")
        write(self.dotfiles / "helpers" / ".local" / "bin" / "hyprglass-bar", "#!/bin/sh\nexec true\n")
        write(self.dotfiles / "tmux" / ".tmux.conf", "set -g base-index 1\n")
        commit_all(self.root, self.dotfiles, "seed packages")
        # A real machine already has these directories, so Stow links inside
        # them instead of folding `~/.config` into the repo.
        (home / ".config").mkdir(parents=True, exist_ok=True)
        (home / ".local" / "bin").mkdir(parents=True, exist_ok=True)
        for package in ("fish", "helpers", "tmux"):
            subprocess.run(
                ["stow", "-v", "-d", str(self.dotfiles), "-t", str(home), package],
                check=True,
                capture_output=True,
                text=True,
                env=self.env(),
            )

        # The owner's terminal folders: each holds only the file config-sync
        # carries, kitty also keeps a stray `*.bak.<suffix>` (not its material).
        write(home / ".config" / "alacritty" / "alacritty.toml", "font_size = 11\n")
        write(home / ".config" / "foot" / "foot.ini", "font=monospace:size=11\n")
        write(home / ".config" / "kitty" / "kitty.conf", "font_size 11\n")
        write(home / ".config" / "kitty" / "kitty.conf.bak.DIbKyz", "font_size 10\n")
        # `machine_local`: config-sync does not carry it here, so it stays a
        # normal new config even though the clone tracks the file.
        write(home / ".config" / "ghostty" / "config", "font-size = 11\n")
        write(home / ".config" / "newtool" / "app.conf", "theme = light\n")
        # A generated launcher shim: Junie CLI rewrites it, so Stow Sync must
        # recommend Ignore like the uv launchers.
        write(
            home / ".local" / "bin" / "junie",
            "#!/bin/bash\n#\n# JUNIE_MANAGED_SHIM\n#\nexec junie-real\n",
        )
        # Owned by config-sync *and* carrying a secret: `never` still wins.
        write(
            home / ".local" / "bin" / "leaky-helper",
            "#!/bin/sh\nTOKEN=ghp_" + "a1B2c3D4" * 5 + "\n",
        )
        # A symlinked parent: the folder lives elsewhere, config-sync still
        # carries the file inside it, and the comparison is lexical.
        folded = self.root / "folded" / "hypr"
        write(folded / "bindings.lua", "hl.bind('SUPER', 'Q', hl.dsp.window.close())\n")
        (home / ".config").mkdir(parents=True, exist_ok=True)
        (home / ".config" / "hypr").symlink_to(folded, target_is_directory=True)

        if config_sync:
            # Installed plugin plus a real clone at config-sync's default path.
            write(
                home / ".config" / "omarchy" / "plugins" / "gladimdim.config-sync" / "manifest.json",
                "{}\n",
            )
            clone = self.xdg / "omarchy-config-sync" / "repo"
            init_repo(self.root, clone)
            for rel in (
                "hypr/bindings.lua",
                "omarchy/hooks/post-update.d/my-hook",
                "bin/hyprglass-bar",
                "bin/leaky-helper",
                "terminals/alacritty.toml",
                "terminals/foot.ini",
                "terminals/kitty.conf",
                "terminals/ghostty.config",
            ):
                write(clone / rel, "carried\n")
            write(
                clone / ".omarchy-config.json",
                json.dumps(
                    {
                        "format": "omarchy-config",
                        "version": 1,
                        "synced_by": "gladimdim.config-sync",
                        "machine_local": ["terminals/ghostty.config"],
                    }
                )
                + "\n",
            )
            commit_all(self.root, clone, "config-sync")

        # The owner ignores the omarchy tree by hand; keep the panel noise-free
        # so the assertions describe config-sync's own effect.
        write(
            self.config,
            json.dumps(
                {
                    "version": 1,
                    "repos": [{"path": str(self.dotfiles), "target": "~", "packages": "auto"}],
                    "watch": ["~/.config/*", "~/.local/bin"],
                    "ignore": ["~/.config/omarchy", "~/.config/stow-sync"],
                    "fetch_minutes": 15,
                    "refresh_minutes": 5,
                    "notify_after_hours": 0,
                },
                indent=2,
            )
            + "\n",
        )
        # The machine's baseline from before config-sync was recognised: these
        # paths are already acknowledged, exactly like the owner's baseline
        # (2026-10-09) that hid the terminal folders behind an empty verdict.
        # The absent world starts from an empty baseline so every path is
        # judged exactly as it was before this feature existed.
        known = (
            [
                "~/.config/alacritty",
                "~/.config/foot",
                "~/.config/kitty",
                "~/.config/hypr",
                "~/.config/fish",
                "~/.local/bin/hyprglass-bar",
            ]
            if seeded_baseline
            else []
        )
        (self.state / "baseline.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "created": "2026-10-09T20:08:53+00:00",
                    "paths": known,
                }
            ),
            encoding="utf-8",
        )

    def cli(self, *args: str, stdin: str | None = None) -> dict:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=self.env(),
            cwd=str(self.root),
        )
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:  # a crash must be visible, never swallowed
            raise SystemExit(f"CLI produced no JSON for {args}: {exc}: {result.stderr}")
        payload["_exit"] = result.returncode
        return payload

    def cli_text(self, *args: str) -> str:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            capture_output=True,
            text=True,
            env=self.env(),
            cwd=str(self.root),
        )
        return result.stdout.strip()

    def cli_on_a_terminal(self, *args: str) -> dict:
        """The CLI with a terminal on stdin: it must answer, never wait."""
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                [sys.executable, str(CLI), *args],
                stdin=slave,
                capture_output=True,
                text=True,
                env=self.env(),
                cwd=str(self.root),
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "waited for input on a terminal"}
        finally:
            os.close(slave)
            os.close(master)
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise SystemExit(f"CLI produced no JSON on a terminal for {args}: {exc}")
        payload["_exit"] = result.returncode
        return payload

    def panel(self, payload: dict) -> dict:
        """The facts the panel derives, through the real Model.js."""
        script = _PANEL_SCRIPT
        payload_path = self.root / "status.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            ["node", "-e", script, str(REPO), str(payload_path)],
            capture_output=True,
            text=True,
            env=self.env(),
        )
        if result.returncode != 0:
            raise SystemExit("panel model failed: " + result.stderr)
        return json.loads(result.stdout)

    def assert_no_desktop_command(self, label: str) -> None:
        calls = self.stub_log.read_text(encoding="utf-8") if self.stub_log.exists() else ""
        check(label + ": no desktop command ran", calls, "")

    def close(self, keep: bool) -> None:
        if keep:
            print("world kept at " + str(self.root))
        else:
            shutil.rmtree(self.root, ignore_errors=True)


_PANEL_SCRIPT = r"""
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const repo = process.argv[1]
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"))
const source = fs.readFileSync(path.join(repo, "Model.js"), "utf8")
  .replace(/^\.pragma library\s*$/m, "")
const Model = { Math, Number, JSON, Array, String, Object, isFinite }
vm.createContext(Model)
vm.runInContext(source, Model, { filename: "Model.js" })
const groups = Model.overviewGroups(payload)
const out = {
  groups: groups.map(function (g) {
    return {
      key: g.key,
      title: g.title,
      items: (g.items || []).map(function (i) {
        var pick = Model.candidateRecommendation(i)
        var actions = Model.candidateRowActions(i)
        return {
          type: i.type,
          path: i.path,
          package: i.package,
          reason: String(i.reason || ""),
          action: i.action,
          label: String(pick.label || ""),
          chip: String(actions.chip || ""),
          adopt: String(actions.adopt || ""),
          ignore: String(actions.ignore || "")
        }
      })
    }
  }),
  badge: Model.badgeCount(payload),
  badgeText: Model.badgeText(payload),
  newCount: Model.newCandidateCount(payload),
  fresh: Model.recommendedCandidates(payload).map(function (c) { return c.path })
}
process.stdout.write(JSON.stringify(out))
"""


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def verdict_table(status: dict) -> dict[str, tuple[str, str]]:
    return {c["path"]: (str(c.get("verdict", "")), str(c.get("reason", ""))) for c in status["candidates"]}


def check_present_world(world: World) -> None:
    status = world.cli("status")
    check("status ok", status.get("ok"), True)
    verdicts = verdict_table(status)

    for path in ("~/.config/alacritty", "~/.config/foot", "~/.config/kitty"):
        check(path + " verdict", verdicts.get(path, ("<missing>", ""))[0], "ignore")
        check(path + " reason", verdicts.get(path, ("", "<missing>"))[1], CONFIG_SYNC_REASON)

    # The symlinked parent is owned too: the comparison is lexical, not realpath.
    check("~/.config/hypr is owned through a symlink", verdicts.get("~/.config/hypr", ("<missing>", ""))[0], "ignore")

    # `machine_local` is excluded from ownership, so it keeps a real verdict.
    check("~/.config/ghostty is machine_local", verdicts.get("~/.config/ghostty", ("<missing>", ""))[0], "upload")
    check(
        "~/.config/ghostty is not config-sync's",
        verdicts.get("~/.config/ghostty", ("", ""))[1] != CONFIG_SYNC_REASON,
        True,
    )

    # A secret inside an owned file stays `never`: ownership never lowers it.
    check("~/.local/bin/leaky-helper stays never", verdicts.get("~/.local/bin/leaky-helper", ("<missing>", ""))[0], "never")

    # A generated launcher shim is machine state, like the uv launchers.
    check("~/.local/bin/junie is ignored", verdicts.get("~/.local/bin/junie", ("<missing>", ""))[0], "ignore")
    check(
        "~/.local/bin/junie names its tool",
        "Junie CLI" in verdicts.get("~/.local/bin/junie", ("", ""))[1],
        True,
    )

    # The stowed helper is a crossing, not a candidate: Stow already manages it.
    check("the stowed helper is no candidate", "~/.local/bin/hyprglass-bar" in verdicts, False)

    # Badge and short line: only the two real new configs count.
    check("summary count", status["summary"]["count"], 2)
    check("status --short", world.cli_text("status", "--short"), "2 new config")

    # S3 crossing, read-only, with the package that carries it.
    check(
        "crossings",
        status.get("config_sync_crossings"),
        [
            {
                "path": "~/.local/bin/hyprglass-bar",
                "package": "helpers",
                "repo_rel": "helpers/.local/bin/hyprglass-bar",
            }
        ],
    )

    # The panel: Hidden group, crossings group, badge and count.
    panel = world.panel(status)
    check("panel group keys", [g["key"] for g in panel["groups"]], ["newConfigs", "hiddenConfigs", "configSync"])
    hidden = next(g for g in panel["groups"] if g["key"] == "hiddenConfigs")
    check("Hidden group title", hidden["title"], "Hidden")
    # The terminal folders are already acknowledged (known), and config-sync
    # owns them, so they are listed under Hidden exactly like an owned file:
    # "Recommended: Ignore" with the backend's "Managed by config-sync" reason.
    check("Hidden group paths", [i["path"] for i in hidden["items"]], [
        "~/.config/alacritty",
        "~/.config/foot",
        "~/.config/hypr",
        "~/.config/kitty",
        "~/.local/bin/junie",
        "~/.local/bin/leaky-helper",
    ])
    hidden_by_path = {i["path"]: i for i in hidden["items"]}
    for path in ("~/.config/alacritty", "~/.config/foot", "~/.config/hypr", "~/.config/kitty"):
        check("Hidden recommends Ignore for " + path, hidden_by_path[path]["label"], "Recommended: Ignore")
        check("Hidden names config-sync for " + path, hidden_by_path[path]["reason"], CONFIG_SYNC_REASON)
        check("Hidden keeps an Adopt anyway for " + path, hidden_by_path[path]["adopt"], "secondary")
        check("Hidden marks " + path + " ignored", hidden_by_path[path]["chip"], "Ignored")
    check("Hidden recommends Ignore for the shim", hidden_by_path["~/.local/bin/junie"]["label"], "Recommended: Ignore")
    check(
        "Hidden names the shim's tool",
        "Junie CLI" in hidden_by_path["~/.local/bin/junie"]["reason"],
        True,
    )
    # Nothing config-sync owns is offered as a new config.
    fresh_paths = [i["path"] for i in next(g for g in panel["groups"] if g["key"] == "newConfigs")["items"]]
    for path in ("~/.config/alacritty", "~/.config/foot", "~/.config/hypr", "~/.config/kitty", "~/.local/bin/junie"):
        check("panel offers no adopt for " + path, path in fresh_paths, False)
    carried = next(g for g in panel["groups"] if g["key"] == "configSync")
    check("crossings group title", carried["title"], "Also carried by config-sync")
    check("crossings group items", [(i["path"], i["package"], i["type"]) for i in carried["items"]],
          [("~/.local/bin/hyprglass-bar", "helpers", "crossing")])
    fresh = next(g for g in panel["groups"] if g["key"] == "newConfigs")
    check("New config files", sorted(i["path"] for i in fresh["items"]),
          ["~/.config/ghostty", "~/.config/newtool"])
    check("panel badge", panel["badge"], 2)
    check("panel badge text", panel["badgeText"], "2")
    check("panel new-config count", panel["newCount"], 2)
    check("panel recommendations", sorted(panel["fresh"]), ["~/.config/ghostty", "~/.config/newtool"])

    # `adopt --dry-run` as the row's Adopt button runs it: a plan, no move.
    adopt = world.cli(
        "adopt", "--repo", str(world.dotfiles), "--package", "newtool",
        "--path", "~/.config/newtool", "--dry-run",
    )
    check("adopt --dry-run ok", adopt.get("ok"), True)
    check("adopt --dry-run is dry", adopt.get("dry_run"), True)
    check("adopt --dry-run destination", adopt.get("moved_to"),
          str(world.dotfiles / "newtool" / ".config" / "newtool"))
    check("adopt --dry-run moved nothing", (world.home / ".config" / "newtool" / "app.conf").exists(), True)
    check("adopt --dry-run created no package", (world.dotfiles / "newtool").exists(), False)

    # `skip --path` as the panel's skip card runs it, then really writes it.
    skip_plan = world.cli("skip", "--path", "~/.config/ghostty", "--dry-run")
    check("skip --dry-run ok", skip_plan.get("ok"), True)
    check_true("skip --dry-run shows the config change", any(
        "skip_paths" in str(line) for line in skip_plan.get("lines", [])
    ))
    check("skip --dry-run wrote nothing", "machines" in json.loads(world.config.read_text(encoding="utf-8")), False)
    skipped = world.cli("skip", "--path", "~/.config/ghostty")
    check("skip ok", skipped.get("ok"), True)
    host = skipped.get("host")
    saved = json.loads(world.config.read_text(encoding="utf-8"))
    check("skip wrote the path", saved.get("machines", {}).get(host, {}).get("skip_paths"), ["~/.config/ghostty"])

    # `ignore` as the row's Ignore button runs it, then the candidate is gone.
    ignored = world.cli("ignore", stdin=json.dumps(["~/.config/newtool"]))
    check("ignore ok", ignored.get("ok"), True)
    check("ignore wrote the path", "~/.config/newtool" in json.loads(world.config.read_text(encoding="utf-8"))["ignore"], True)
    after = world.cli("status")
    check("ignored path is no candidate", "~/.config/newtool" in verdict_table(after), False)
    check("badge after ignore", after["summary"]["count"], 1)

    # CLI: paths as arguments, the way a human types them, instead of the
    # panel's stdin list; and an unknown option is an error, not a silent ok.
    pos = world.cli("ignore", "~/.config/foot", stdin="")
    check("ignore positional ok", pos.get("ok"), True)
    check(
        "ignore positional wrote the path",
        "~/.config/foot" in json.loads(world.config.read_text(encoding="utf-8"))["ignore"],
        True,
    )
    check("ignored folder is no candidate", "~/.config/foot" in verdict_table(world.cli("status")), False)
    back = world.cli("unignore", "~/.config/foot", stdin="")
    check("unignore positional ok", back.get("ok"), True)
    check(
        "unignore positional removed the path",
        "~/.config/foot" in json.loads(world.config.read_text(encoding="utf-8"))["ignore"],
        False,
    )
    check("folder is a candidate again", "~/.config/foot" in verdict_table(world.cli("status")), True)
    bad = world.cli("unignore", "--path", "~/.config/foot", stdin="")
    check("unknown option is an error", bad.get("ok"), False)
    check("unknown option names the flag", "--path" in str(bad.get("error", "")), True)
    check(
        "unknown option wrote nothing",
        "~/.config/foot" in json.loads(world.config.read_text(encoding="utf-8"))["ignore"],
        False,
    )
    # A human typing the command has a terminal on stdin; reading it would wait
    # for an EOF that never comes, so the arguments alone must decide.
    terminal = world.cli_on_a_terminal("ignore", "~/.config/ghostty")
    check("ignore on a terminal answers", terminal.get("ok"), True)
    check(
        "ignore on a terminal wrote the path",
        "~/.config/ghostty" in json.loads(world.config.read_text(encoding="utf-8"))["ignore"],
        True,
    )

    world.assert_no_desktop_command("present world")


def check_absent_world(world: World) -> None:
    status = world.cli("status")
    check("absent: status ok", status.get("ok"), True)
    # A5: the payload keeps today's keys (plus the notification count the
    # fixtures predate) and gains no config-sync key.
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    check("absent: today's payload keys", sorted(set(status) - set(fixture) - {"_exit"}),
          ["notifications_sent"])
    check("absent: no crossings key", "config_sync_crossings" in status, False)
    reasons = {c["reason"] for c in status["candidates"]}
    check("absent: no config-sync reason", CONFIG_SYNC_REASON in reasons, False)
    verdicts = verdict_table(status)
    for path in ("~/.config/alacritty", "~/.config/foot", "~/.config/kitty", "~/.config/hypr"):
        check("absent: " + path + " keeps a normal verdict", verdicts.get(path, ("<missing>", ""))[0], "upload")
    check("absent: badge counts them again", status["summary"]["count"], 6)
    panel = world.panel(status)
    check("absent: no crossings group", [g["key"] for g in panel["groups"]],
          ["newConfigs", "hiddenConfigs"])
    absent_hidden = next(g for g in panel["groups"] if g["key"] == "hiddenConfigs")
    # The shim is machine state whether or not config-sync is installed.
    check("absent: Hidden keeps the shim and the secret", [i["path"] for i in absent_hidden["items"]],
          ["~/.local/bin/junie", "~/.local/bin/leaky-helper"])
    check("absent: badge", panel["badge"], 6)
    world.assert_no_desktop_command("absent world")


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    present = World(config_sync=True)
    absent = World(config_sync=False, seeded_baseline=False)
    try:
        check_present_world(present)
        check_absent_world(absent)
    finally:
        present.close(keep)
        absent.close(keep)

    width = [max(len(row[i]) for row in ROWS) for i in range(3)]
    header = ("Check", "Expected", "Observed")
    print("| " + " | ".join(h.ljust(width[i]) for i, h in enumerate(header)) + " | Result |")
    print("|" + "|".join("-" * (w + 2) for w in width) + "|--------|")
    for name, expected, observed, ok in ROWS:
        print(
            "| " + name.ljust(width[0])
            + " | " + expected.ljust(width[1])
            + " | " + observed.ljust(width[2])
            + " | " + ("PASS" if ok else "FAIL") + " |"
        )
    passed = sum(1 for row in ROWS if row[3])
    print(f"\n{passed}/{len(ROWS)} checks passed")
    if FAILED:
        print("failed: " + ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
