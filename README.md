# Stow Sync (`pwnsxb.stow-sync`)

An Omarchy bar plugin that watches your GNU Stow dotfiles repositories and tells
you, at a glance, whether they are committed, pushed, up to date, fully stowed
and complete.

## Why

If you manage your dotfiles with GNU Stow, "is everything saved?" is several
questions at once:

- Are there uncommitted changes or untracked files?
- Are commits waiting to be uploaded, or is the remote ahead?
- Is every package actually stowed, or are some links pending, conflicting or
  dangling?
- Were new config files created on this machine that were never added to a
  package?

A Starship prompt segment can show one of those (e.g. "uncommitted changes"),
but not all of them, and usually only for one repo. Stow Sync answers all of
them for every configured repository in one panel, with a bar badge that only
counts things that actually need your attention.

It is the Stow counterpart to the config-sync plugin: config-sync handles the
Omarchy-side config tree, Stow Sync handles your Stow repos.

## Install

Published plugin:

```bash
omarchy plugin add https://github.com/pwn27sbx/omarchy-stow-sync --enable --yes
```

From a local checkout (development):

```bash
omarchy plugin add /home/$USER/Projects/omarchy-stow-sync --enable --yes
```

Place it in the bar:

```bash
omarchy plugin enable pwnsxb.stow-sync --section right
```

After installing, left-click the branch icon to open the panel. Right-click
refreshes with a fetch.

## First run

The first call to `status` creates two things:

1. **Config** — `~/.config/stow-sync/config.json`, written once with the default
   repositories (`~/.dotfiles` and `~/wallpapers`). An existing file is **never
   overwritten**; edit it by hand or with the panel's **Edit** button.
2. **State dir** — `~/.local/state/stow-sync/`, owned by the plugin and written
   atomically with mode `0600`:
   - `baseline.json` — the first-run snapshot of files that already existed, so
     pre-existing tools and plugin files are not reported as "new".
   - `publish.json` — the time of the last successful Publish per repo.
   - `notify.json` — the continuous-pending clock used by `notify_after_hours`.

The plugin's own config file lives under `~/.config/stow-sync/`, so it also
shows up as a candidate until you adopt or ignore it. That is intended.

## Configuration

`~/.config/stow-sync/config.json`:

```json
{
  "version": 1,
  "repos": [
    { "path": "~/.dotfiles", "target": "~", "packages": "auto" },
    { "path": "~/wallpapers", "target": "~", "packages": ["walls"] }
  ],
  "watch": [
    "~/.config/systemd/user",
    "~/.local/bin",
    "~/.config/*"
  ],
  "ignore": [
    "~/.config/hypr", "~/.config/omarchy",
    "~/.config/systemd/user/*.wants",
    "~/.config/BraveSoftware", "~/.config/chromium", "~/.config/google-chrome*",
    "~/.config/microsoft-edge*", "~/.config/Code", "~/.config/Electron", "~/.config/dconf",
    "~/.config/pulse", "~/.config/libreoffice"
  ],
  "fetch_minutes": 15,
  "refresh_minutes": 5,
  "notify_after_hours": 0
}
```

| Key | Type | Meaning |
| --- | --- | --- |
| `version` | number | Config schema version. Currently `1`. |
| `repos` | array | The Stow repositories to watch. Each entry has `path`, `target` and `packages` (below). |
| `repos[].path` | string | Repository root. `~` is expanded against `HOME`. |
| `repos[].target` | string | Directory the repo is stowed into (normally `~`). `~` is expanded. |
| `repos[].packages` | `"auto"` or array | `"auto"` detects every top-level Stow package (directories that are not hidden and do not ignore everything). An array lists packages explicitly, e.g. `["walls"]`. |
| `watch` | array | Directories or globs checked for new config files. A plain directory reports its direct children; a glob such as `~/.config/*` reports each direct child. Depth is always 1. |
| `ignore` | array | Paths or globs (`fnmatch`) excluded from the candidate scan. |
| `fetch_minutes` | number | How often the panel runs `git fetch --prune` in the background. |
| `refresh_minutes` | number | How often the panel re-runs `status`. |
| `notify_after_hours` | number | `0` disables desktop notifications. `N > 0` sends one `notify-send` when a repo has had pending items continuously for at least `N` hours, at most once per repo per calendar day. The continuous-pending clock is stored in `notify.json`; a repo that becomes clean clears its entry. |

## Safety model

Stow Sync is intentionally read-only by default and asks before it changes
anything.

- **Read-only status.** `status` and `status --short` never mutate a repository
  or the config. `status --fetch` only runs `git fetch --prune` (it updates
  remote-tracking refs, never the working tree). Stow health checks use
  `stow -n` (dry runs) only.
- **The only writes the plugin makes on its own** are the config file (created
  once, never overwritten) and its own state directory
  `~/.local/state/stow-sync/` (`baseline.json`, `publish.json`, `notify.json`).
  State writes are atomic and `0600`, and the directory is `0700`. Nothing is
  ever written to a repository or to your tracked config unless you press a
  mutating action.
- **Confirm cards.** Every mutating action (Publish, Upload, Update, Restow,
  Adopt, Ignore) opens a confirm card that names exactly what will happen — the
  paths, the package and the repository involved — before anything runs.
- **Secret scan.** Before a commit, the staged diff is scanned for private keys
  and common token/password patterns. If anything matches, the commit is
  blocked and the matched value is never shown; you can review the file and
  line, or explicitly choose to commit anyway.
- **Refusals instead of guesses.** Pull is `--ff-only` and refuses a dirty
  worktree, untracked files, a diverged branch or a missing upstream. Restow
  runs a dry run first and refuses on conflicts. Adopt refuses when the
  destination already exists and rolls back if stowing conflicts. There is no
  discard or revert action.
- **Git hygiene.** Git runs with prompts disabled, hooks bypassed for
  inspection commands, and a bounded, killable process group, so a hung command
  can never freeze the bar.

## Notifications

Set `notify_after_hours` to a value greater than zero to be reminded when a
repository has been pending for a while:

- A repo counts as **pending** when it has changes or untracked files, is ahead
  or behind its upstream, or has a package that needs fixing.
- The clock starts when it first becomes pending and resets when it becomes
  clean.
- Once it has been pending continuously for at least `notify_after_hours`, one
  desktop notification is sent per repo per calendar day.
- `0` disables notifications entirely. A missing `notify-send` is ignored and
  never affects the panel.

## Starship integration

`status --short` prints a single plain line (empty when everything is clean) for
a Starship prompt segment:

```toml
[custom.dotfiles]
description = "Stow repos with pending work"
command = "python3 ~/.config/omarchy/plugins/pwnsxb.stow-sync/scripts/stow_sync.py status --short"
when = "python3 ~/.config/omarchy/plugins/pwnsxb.stow-sync/scripts/stow_sync.py status --short | grep -q ."
format = " [◆](bold white) [](fg:red)[  $output ](bg:red fg:black bold)[](fg:red) "
```

Stow Sync never edits `~/.config/starship.toml` for you; add the snippet above
yourself if you want the segment.

## Keyboard

| Key | Action |
| --- | --- |
| Left click | Toggle the panel |
| Right click | Refresh with fetch |
| `1`–`3` or `←` `→` | Switch tabs |
| `↑` `↓` | Move the cursor / scroll |
| `Enter` | Activate (open the diff for the focused change) |
| `Tab` | Next tab |
| `r` | Refresh with fetch |
| `p` | Publish (or the primary action) |
| `u` | Update (pull `--ff-only`) |
| `i` | Hide the focused change row |
| `Esc` | Close the panel / go back |

## Requirements

Shipped with Omarchy: `python3`, `git`, `stow`. `notify-send` is optional and
only needed when `notify_after_hours` is greater than zero. The helper never
prompts for credentials; git runs with terminal prompts and SSH batch mode
disabled, so authentication failures surface as a message instead of freezing
the bar.

## Removal

```bash
omarchy plugin remove pwnsxb.stow-sync --yes
rm -rf ~/.local/state/stow-sync
rm -rf ~/.config/stow-sync   # optional: also remove your saved config
```

Removing the plugin does not touch your repositories.

## License

MIT © 2026 pwnsxb
