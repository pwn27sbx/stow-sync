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
omarchy plugin add https://github.com/pwn27sbx/stow-sync --enable --yes
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

### "Set up this machine" (opt-in)

On a fresh Omarchy install Stow Sync can clone every Stow repo, link every
package and back up anything in the way. It is **off by default**: the header
button, the Overview banner and the wizard only appear when you enable it. Add
the setting to this plugin's `shell.json` layout entry:

```json
{ "id": "pwnsxb.stow-sync", "machineSetup": true }
```

then `omarchy restart shell`. The complete walkthrough — the tools to install,
GitHub authentication, the recipe schema, the safety rules and how Undo works —
is in [New machine](#new-machine).

## New machine

Restore your whole Stow setup on a **fresh Omarchy install** by running these
steps in order.

```bash
# 1. Update Omarchy first (needed before installing packages).
omarchy update

# 2. Install the tools Stow Sync and the recipe need. `stow` and `github-cli`
#    are NOT preinstalled on a fresh Omarchy.
omarchy pkg add stow github-cli

# 3. Authenticate GitHub — only needed when any recipe repo is private.
gh auth login
gh auth setup-git

# 4. Install the plugin (published), or from a local checkout for development.
omarchy plugin add https://github.com/pwn27sbx/stow-sync --enable --yes
# omarchy plugin add /path/to/omarchy-stow-sync --enable --yes

# 5. Enable it. For a manual copy the shell must rescan plugins first.
omarchy-shell shell rescanPlugins        # manual installs only
omarchy plugin enable pwnsxb.stow-sync --section right
```

6. Turn the wizard on: add `"machineSetup": true` to this plugin's `shell.json`
   layout entry (see [the snippet above](#set-up-this-machine-opt-in)) and run
   `omarchy restart shell`.
7. Open the panel and press **Set up this machine** — the wand icon in the
   header, or the button on the Overview banner. The wizard walks through five
   steps: **Check → Connect → Review → Apply → Report**.

The **Check** step verifies `stow`, `git`, the pacman sync database and — when
`gh` is installed — a **GitHub login** row ("signed in as …" / "not signed in"),
showing the exact fix command for anything missing. **Connect** asks GitHub which
of your repos are dotfiles candidates: a repo that contains
`.stow-sync/setup.json` is **definitive** (shown first and preselected), a repo
with a Stow-package shape is **likely**, and everything else stays behind "Show
all repos" with a filter field; it then clones the dotfiles repo and each other
recipe repo one at a time with a real progress bar, and shows a GitHub login fix
with **Check again** if a clone fails on authentication. **Review** shows exactly
what will be linked and moved to backup; nothing is forced, and blocked packages
are reported in red. **Apply** links the packages, enables the services and runs
the selected post-steps behind a live per-item checklist. **Report** lists what
happened under collapsible groups — every post-step with its state (`ran`,
`skipped: needs gowall`, `not selected`) and its last output line — the backup
folder path, and a one-click **Undo** pinned in the footer. An Undo shows a result
card (packages unlinked, files restored, services disabled, anything refused) and,
on a fresh machine, returns the overview to the "not set up" state.

### The recipe

The recipe lives in the dotfiles repo at `.stow-sync/setup.json` (a directory
that starts with `.`, so `packages: "auto"` never treats it as a package). A
full example ships in [`docs/setup-recipe.example.json`](docs/setup-recipe.example.json).
Every key is validated strictly; unknown keys and wrong types are rejected with a
precise error.

| Key | Type | Meaning |
| --- | --- | --- |
| `version` | number | Schema version. Currently `1`. |
| `repos` | array | The repos to clone and link, in `order`. |
| `repos[].path` | string | Where to clone (e.g. `~/.dotfiles`). `~` expands against `HOME`. |
| `repos[].url` | string | The git URL to clone from. |
| `repos[].packages` | `"auto"` or array | `"auto"` detects every top-level package; an array lists them explicitly. |
| `repos[].order` | number | Clone/link order (must be unique). |
| `repos[].private` | boolean | Marks a private repo so the wizard checks GitHub auth up front. |
| `skip_packages` | array | Package names never linked (e.g. `odd`, `zen`). |
| `services` | array | systemd user units to `enable --now` after linking. |
| `requires` | array | Commands reported as missing tools (never installed). |
| `post` | array | Optional commands to run after linking. |
| `post[].id` | string | Unique id, also used by the `--post` selection. |
| `post[].label` | string | Human label shown in Review and Report. |
| `post[].argv` | array | The command as an argument vector — never a shell string. |
| `post[].default` | boolean | Whether the step is selected by default. |
| `post[].timeout_s` | number | Per-step timeout in seconds. |
| `post[].needs` | array | Command names the step needs. If one is missing, the step is shown disabled (`needs gowall`) and is never run. |
| `post[].requires_path` | string | A `~`-relative glob that must match at least one path (e.g. `~/.zen/*/prefs.js`). If nothing matches, the step is shown disabled. |
| `post[].requires_hint` | string | The plain reason shown for a disabled `requires_path` step (e.g. "Install Zen and open it once first"). |
| `notes` | array | Free-form reminders shown verbatim in Review and Report. |

The recipe also drives post-steps a fresh machine would otherwise do by hand. A
concrete `post` section (see the owner's own recipe) installs every tool pinned
in your mise config, and recolors wallpapers only when `gowall` is present:

```json
"post": [
  { "id": "wallpaper-tint", "label": "Recolor wallpapers for every theme",
    "argv": ["~/.local/bin/wallpaper-tint", "--all"], "default": true,
    "timeout_s": 900, "needs": ["gowall"] },
  { "id": "mise-install", "label": "Install the tools from your mise config",
    "argv": ["~/.dotfiles/.stow-sync/post/mise-install"], "default": true,
    "timeout_s": 1800 }
]
```

`mise` ships with Omarchy, so the `mise-install` step installs every tool pinned
in your mise config (Node and future tools) without making Node a Stow Sync
requirement.

### Safety and Undo

- **No shell.** Every `post[].argv[0]` must expand (after `~`) to an absolute
  path **inside `$HOME`**, and commands run as an argument vector with `cwd`
  set to `$HOME` — never through a shell.
- **Nothing is deleted.** Any file in the way is **moved** into
  `~/.local/state/stow-sync/setup-backups/<id>/files/`, preserving its type and
  mode, and recorded in that folder's `manifest.json`.
- **Reviewed plan.** Connect and Review build a plan and a 10-minute token;
  Apply refuses to run if the plan changed since you reviewed it.
- **Undo.** Each apply writes its manifest before every move, so a crash is still
  undoable. Undo disables the services the apply enabled, unstows the packages it
  stowed (only those), moves every backup back and refuses any destination that
  is no longer the apply's own symlink. Run it from the Report step, or any time
  later from the header's **Setup backups** view (each backup shows its date and
  counts, or an "undone" marker).

Stow links **files** into an existing folder; it does not replace the folder. For
a package like `nvim`, Stow adds symlinks for the files the repo contains but
leaves Omarchy's own extra files (for example `~/.config/nvim/lua/plugins/*.lua`)
in place, so the two are mixed. Check what a package's folder overlay will keep
before you rely on it.

### Testing in a VM

The "Set up this machine" wizard is safe to rehearse in a throwaway Omarchy VM
(take a snapshot first). A few host/guest quirks are worth knowing:

- **Host firewall.** libvirt guests are blocked by `ufw`'s default deny policy.
  Allow the bridge on the host:

  ```bash
  sudo ufw allow in on virbr0
  sudo ufw route allow in on virbr0
  sudo ufw route allow out on virbr0
  ```

- **Guest DNS.** DNS through libvirt's dnsmasq can fail; set the DNS provider to
  Cloudflare in the guest's Omarchy network panel.
- **Clipboard.** Host-to-guest clipboard sharing is unreliable under Wayland (no
  `spice-vdagent`); serve a script over the network instead of pasting.
- **Manual installs.** After copying the plugin folder into a VM, run
  `omarchy-shell shell rescanPlugins` before `omarchy plugin enable`, otherwise
  the freshly enabled plugin is "not known" to the shell.

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

## Data and privacy

Stow Sync is a local helper: it talks only to your own repositories and your
own machine. It has no account, no telemetry and no analytics, and no network
code of its own — the only network traffic is `git fetch`/`clone`/`push`/`pull`
and, when you use the wizard, `gh`.

- **What it reads.** Your repositories read-only (`git status`, `git log`,
  `stow -n` dry runs), `~/.config/stow-sync/config.json`, the optional setup
  recipe `.stow-sync/setup.json` inside a repo, and its own state directory
  `~/.local/state/stow-sync/`. Every read is size-capped and opened with
  `O_NOFOLLOW`; the opened inode itself is checked to be a regular file owned
  by you, so a planted symlink, a foreign-owned file or an oversized file is
  refused instead of read.
- **What it writes.** Only your config (created once, never overwritten) and the
  plugin's own state directory (`baseline.json`, `publish.json`, `notify.json`,
  `setup-plan.json`, `setup-progress.json`, `setup-backups/`). Every write is
  atomic: an exclusive `0600` temp file inside the target directory, `fsync`,
  then `os.replace`; the state directory is `0700`. The plugin never writes to a
  repository or to a tracked config unless you press a mutating action.
- **Processes.** Every external command runs as a fixed argument vector, never
  through a shell, with a hard timeout and a bounded, killable process group.
  Git runs with terminal prompts disabled, `GIT_ASKPASS=true` and
  `ssh -oBatchMode=yes`; `gh` runs with prompts disabled. Commit messages and
  other payloads go on **stdin**, never in `argv`, and a repository URL that
  embeds a credential is rejected before it reaches `git`.
- **Secrets.** Nothing sensitive is logged or stored. The pre-commit secret scan
  reports only the file, line and rule, never the matched value, and
  credential-bearing URLs are stripped from every diagnostic string.
  Authentication is delegated entirely to your existing Git/`gh` configuration.
- **The setup wizard.** It runs only when you turn it on, changes nothing until
  you review the plan and confirm, backs up every file it replaces (with an
  on-disk manifest) and can undo the whole apply. Every post step's `argv[0]`
  must resolve inside `$HOME`, and post commands run as a fixed vector, never a
  shell string.

### Dependencies

Shipped with Omarchy: `python3` and `git`. GNU Stow (`stow`) is required to read
and change Stow state and is installed by the [New machine](#new-machine) guide.
`github-cli` (`gh`) is optional and only needed when the wizard has to clone a
private repository. `notify-send` is optional and only used when
`notify_after_hours` is greater than zero.

## Known limitations

- **Omarchy can rewrite `~/.config/ghostty/config`.** The Text size slider
  (`omarchy-display-text-size`) and `omarchy-font-set` edit that file in place
  with `sed -i`, which replaces the Stow symlink with a regular file. Stow Sync
  then correctly reports a `ghostty` conflict. The clean fix is to keep your own
  ghostty settings in a separate file and include it, leaving `config` to
  Omarchy:

  ```ini
  # in the ghostty config your dotfiles stow
  config-file = ~/.config/ghostty/personal
  ```

  Otherwise, re-adopt the rewritten file into its package.

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

In the "Set up this machine" wizard: `Enter` confirms the current step or moves
on, `Esc` goes back (or shows "Setup is running" while a step is in flight), and
the arrow keys scroll the Review and Report content.

## Requirements

Shipped with Omarchy: `python3` and `git`. GNU Stow (`stow`) is required to read
and change Stow state and is **not** preinstalled on a fresh Omarchy — the
[New machine](#new-machine) guide installs it (`omarchy pkg add stow
github-cli`). `github-cli` (`gh`) is only needed when the opt-in "Set up this
machine" wizard has to clone a private repo. `notify-send` is optional and only
needed when `notify_after_hours` is greater than zero. The helper never prompts
for credentials; git runs with terminal prompts and SSH batch mode disabled, so
authentication failures surface as a message instead of freezing the bar.

## Removal

```bash
omarchy plugin remove pwnsxb.stow-sync --yes
rm -rf ~/.local/state/stow-sync
rm -rf ~/.config/stow-sync   # optional: also remove your saved config
```

Removing the plugin does not touch your repositories.

## License

MIT © 2026 pwnsxb
