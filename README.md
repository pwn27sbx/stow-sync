# Stow Sync (`pwnsxb.stow-sync`)

An Omarchy bar plugin for people who keep their dotfiles in **GNU Stow
repositories on GitHub**. It tells you, at a glance, whether those repos are
committed, pushed, up to date and fully linked, and it can set up a fresh
machine from them in one guided flow.

**What it does**

- **Watches** each configured Stow repo (for example `~/.dotfiles`): uncommitted
  or untracked files, commits waiting to be pushed or pulled, packages whose
  links are pending, conflicting or dangling, and new config files that were
  never added to a package. The bar icon only shows a badge when something
  needs you.
- **Lets you act** from the panel: review changes, commit and publish, upload
  commits whenever there are some, pull updates, and fix one package at a time
  with a plain explanation and a dry-run plan — or skip a package or a path on
  this machine only.
- **Sets up a new machine** (opt-in): checks your tools and `gh` login, downloads your repos,
  shows exactly what it will link and back up, links everything with
  `stow`, runs your optional post-install steps, and can undo the whole setup.

**Who it is for**

- You use **Omarchy** and already manage (or want to manage) your dotfiles as
  **GNU Stow packages in a git repo**, usually on GitHub.
- You want to know "is everything saved and linked?" without running
  `git status` and `stow -n` in every repo, and to move to a new laptop
  without redoing your setup by hand.

**What it is not**

- Not a dotfiles manager of its own and not a replacement for Stow: it drives
  `git` and `stow` on repos you own; no Stow repo, nothing to show.
- Not a backup or sync service, and no server of its own: it only talks to
  your own git remotes and to GitHub through `git` and `gh`. No telemetry.
- Not for Omarchy's own config tree (`~/.config/hypr`, `shell.json`, hooks):
  that is what the config-sync plugin is for. The two work side by side.
- It never overwrites your files silently: anything in the way is moved to a
  backup you can restore with Undo.

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
   overwritten** by the first run; edit it by hand, with the panel's **Edit**
   button, or with **Skip on this machine**.
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
| `machines` | object | Optional per-machine skips, keyed by hostname (see [Per-machine skips](#per-machine-skips)). Missing means today's behaviour. |
| `fetch_minutes` | number | How often the panel runs `git fetch --prune` in the background. |
| `refresh_minutes` | number | How often the panel re-runs `status`. |
| `notify_after_hours` | number | `0` disables desktop notifications. `N > 0` sends one `notify-send` when a repo has had pending items continuously for at least `N` hours, at most once per repo per calendar day. The continuous-pending clock is stored in `notify.json`; a repo that becomes clean clears its entry. |

### Per-machine skips

The config usually lives in your dotfiles, so one shared file has to describe
several machines. A `machines` section is keyed by hostname and only the current
host's entry applies:

```json
"machines": {
  "pwnsxb": {
    "skip_packages": ["mise-mac"],
    "skip_paths": ["~/Pictures/Wallpapers/solarized-osaka-mac"]
  }
}
```

The key is the hostname the plugin reads from `socket.gethostname()`: run
`hostname` on Linux to see it. (On macOS `hostname` can differ from
`scutil --get LocalHostName`; this plugin runs on Omarchy, so that note only
matters if you edit the shared file from a Mac.)

- `skip_packages` — the package is left out of health, the badge, the action
  count, notifications and **Needs fixing** on that host. The Packages tab still
  lists it, as **Skipped on this machine**.
- `skip_paths` — a pending `LINK` target at, under, or above a skipped path does
  not count as pending. A link that folds a whole parent covering a skipped path
  counts as touching it: skipping
  `~/Pictures/Wallpapers/solarized-osaka-mac` also hides a plan that would link
  `~/Pictures`.
- Another host's section changes nothing here, and a missing `machines` key is
  exactly the old behaviour. A wrong type prints one error in the panel and the
  section is ignored; it never crashes.
- **Skip on this machine** in a Needs fixing row writes the entry for the
  current host after showing you the change. The config is a Stow link into your
  dotfiles, so the plugin writes through the link (it never replaces it) and
  dotfiles then shows 1 change to publish. From a terminal,
  `python3 scripts/stow_sync.py skip --package NAME` (or `--path PATH`) does the
  same, and `--dry-run` prints the change without saving it.
- **Link this** refuses when its dry-run plan would touch a skipped path, and
  the setup wizard never links a package skipped on this host.

## Upload and fixing packages

### Upload is always reachable

Whenever any repository has commits ahead, the Overview shows an **Upload**
button in the action row — next to Review Changes, Update and Publish, whichever
of them is the recommended action — and the Changes tab shows **Upload N
commits** above its lists. Both open the same confirm card and push every repo
that is ahead, exactly like the `p` key's Upload action.

### Needs fixing, one package at a time

The Overview **Needs fixing** group lists one row per package, never a single
"fix everything" button. Each row says the state in plain words, the affected
paths (first three, then "+N more") and the action for that state:

| Package health | The row says | Action |
| --- | --- | --- |
| `pending` | **Missing links** | **Link this** |
| `conflicts` | **A real file is in the way** | **Review** — a conflict is never overwritten |
| `dangling` | **Broken links** | **Review** — there is no repair for a broken link, so it is shown, not re-linked |

**No button in this row is highlighted, because none is a recommendation.** The
plugin cannot know whether linking a package is right for this machine: a
Mac-only package such as `mise-mac` is listed exactly like one that should be
linked, and both actions are quiet outlines. The accent colour stays reserved
for the new-config rows, where the verdict is the plugin's own.

Every row also offers **Skip on this machine**, which writes the per-host entry
described in [Per-machine skips](#per-machine-skips). A package skipped on this
host is not listed at all.

Pressing the action runs `stow --dry-run` for that one package and opens a
confirm card with the plan, path by path:

- "will link `~/.config/nuncio` → `~/.dotfiles/nuncio/.config/nuncio`"
- "will replace the link `~/.config/mise` with a folder" for an `UNLINK`/`MKDIR`
  pair
- "conflict at `~/.config/ghostty/config`"

The card names the package and says that nothing else follows, so the old
"which package comes next?" surprise is gone. Only a conflict-free `pending`
package gets a **Link** button; a conflict, a broken link, a refused plan or an
empty plan shows **Close**, so nothing is ever applied blindly.

In the Packages tab a package skipped on this host says **Skipped on this
machine**, and a health check that crashed says **Check failed: <error>** instead
of pretending the package is fine.

## New config candidates

Every file or directory inside a `watch` area that is not in a configured repo
yet is a *candidate*. Stow Sync decides what to do with each one **by itself**,
from the file on disk — no network call, no model — and tells you why:

| Verdict | When | In the panel |
| --- | --- | --- |
| `never` | a known credential store, or a secret rule (the same rules the commit scan uses) matches the content: keys, tokens, private keys, chat webhooks (Discord, Slack, Teams), a Sentry DSN or cron check-in URL, a URL that carries a password or a long token, and a setting whose name says secret (`*_WEBHOOK`, `*_DSN`, `*_TOKEN`, `*_SECRET`, `*_KEY`, `*_PASSWORD` with a non-empty value) | not counted, listed under **Hidden**, says **Never stow this** and offers no Adopt button |
| `ignore` | tool-generated or machine state: a launcher whose shebang points into a tool-managed environment (uv, pipx, mise, npm), caches, logs, history, lock files, databases, backups, temp files, a file that only names paths installed on this machine, or an empty folder (or one holding only empty folders) — there is nothing to adopt | not counted, listed under **Hidden**, says **Recommended: Ignore**, can still be adopted by hand |
| `upload` | a small text config (up to 128 KB, valid UTF-8) with no secret, no machine-specific path and no group/other read; a hand-written file with comments counts as extra confidence | counted, listed first, says **Recommended: Adopt** with an accented Adopt button |
| `review` | anything else: binary, oversized, a directory with mixed contents, an entry the scan could not read, a file only its owner can read (mode `600` or any mode without group/other read), or a user unit whose `ExecStart` (or a `.timer`/`.path` whose service) runs a script in `~/Projects` | counted, says **Suggested: Ignore** with the accented Ignore button |

The reasons are plain, specific sentences: an `upload` reason names the file and
what the bytes show ("config.toml: ui, notifications, app; no secret match",
"config.json: JSON with your own comments; no secret match"), a directory names
the files inside it, `ignore` says why the file is machine state ("Launcher
generated by uv; reinstalling recreates it"), and `never` names the rule that
matched ("canary.env: Discord webhook URL; never stow it"). A `review` reason
names its doubt ("canary.env: private file (mode 600); check before stowing",
"Runs a script in ~/Projects; check before stowing"). An `upload` reason states
exactly what was checked — the same `SECRET_RULES` scan as a commit — and never
claims more. A matched secret **value** is never shown. A reason is capped at one
line in the row.

### What a candidate row tells you

Every row names its pick in plain words, above the two buttons, and the pick's
button is filled with the accent colour (the other stays a quiet outline). One
colour rule for the whole panel: **accent = the recommended choice**, **muted
grey = state or information**, **red = never**. One permanent legend states the
rule under the status sentence at the top of Overview — a soft strip with an 8 %
accent fill, a 35 % accent border and roomier padding, carrying "The highlighted
button is the recommended choice." — and the help overlay repeats the same
sentence plus the colour rule:

| Row says | Means | Filled button |
| --- | --- | --- |
| **Recommended: Adopt** | the verdict is `upload`; this file belongs in Stow | Adopt |
| **Recommended: Ignore** | the verdict is `ignore`; it is machine state, already out of the count. The row shows a neutral **✓ Ignored** state chip (muted text, no accent, the panel's button radius, the check right next to the word) and a quiet **Adopt anyway** button, because there is no Ignore action to press: the verdict is recomputed each scan | the chip is information, not a button; **Adopt anyway** stays a quiet outline |
| **Suggested: Ignore** | the verdict is `review`: a doubt, and Ignore is the safe pick | Ignore |
| **Never stow this** | the verdict is `never` (a secret or a credential store) | no button |

A suggestion is not a promise: the row still offers both actions, and you can
adopt a `review` file by hand. The suggestion says why in one short clause, and
the backend reason below it stays the full why:

- a project-bound unit → "belongs to the project in ~/Projects, not to dotfiles";
- an owner-only file → "private file; keep it out unless you know it is safe";
- any other doubt → "check it before stowing".

For `never` the Adopt action is not offered at all, exactly like a known
credential store: the row shows **Never stow this** in the warning colour and no
Adopt button, so a secret can never be adopted in one click. Clicking the row
itself adopts only when the pick is Adopt; a `review` row needs an explicit
button press. A row recommended Adopt but hidden for another reason (there is
none today: Hidden only holds `ignore`/`never`) would keep its accent Adopt and
a quiet Ignore, because hiding is about the group, not the advice.

The same colour rule applies to every Adopt/Ignore surface, not just the rows:
both **Accept recommendations (N)** surfaces (the New config files card and the
Overview banner) are the recommended Adopt, so they are accent-filled too; the
Hidden group, the keyboard (`a` still adopts the first new config) and the
counts are unchanged; the Changes tab and the setup wizard never offer
Adopt/Ignore, so they have nothing to colour.

A candidate **directory** follows the same rule: any file inside that only its
owner can read makes the directory `review`, with the reason naming that file
("canary.env: private file (mode 600); check before stowing"), because adopting
the directory copies every file in it into the repository, where the owner-only
mode is lost. A directory is therefore never `upload` just because its other
files are ordinary.

**Accept recommendations (N)** in the New config files card (and in the Overview
banner) adopts every `upload` candidate in one click through the normal Adopt
path. It never includes a `review` row (a suggestion) or a hidden row. The
confirm card lists every path, the package it goes into and its reason
before anything runs, and the list is frozen at that moment: a background
refresh cannot change what you approved. It only adopts — nothing is committed
or uploaded until you press Publish.

Nothing is ever uploaded automatically, and `ignore`/`never` are not written to
the config's `ignore` list: they are computed on every scan, so a rule fix
changes the verdict without a migration. The bar badge counts only `upload` and
`review` candidates.

Reads are bounded (128 KB per file; a directory contributes at most 400 entries
and 512 KB), so a pathological candidate can never stall `status`. Hitting a
bound gives `review`, never a guess.

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
  once; after that only **Skip on this machine** writes it, after showing you
  the change) and its own state directory
  `~/.local/state/stow-sync/` (`baseline.json`, `publish.json`, `notify.json`).
  State writes are atomic and `0600`, and the directory is `0700`. Nothing is
  ever written to a repository or to your tracked config unless you press a
  mutating action; Skip writes the config through its Stow link, so your
  dotfiles repo then shows 1 change to publish.
- **Confirm cards.** Every mutating action (Publish, Upload, Update, Link this,
  Skip on this machine, Adopt, Ignore) opens a confirm card that names exactly
  what will happen — the paths, the package, the config change and the
  repository involved — before anything runs.
- **Deletions and renames publish.** A selected deletion commits the removal, and
  a selected rename commits as a real rename (`old → new`) instead of leaving a
  stray staged deletion behind.
- **Secret scan.** Before a commit, the staged diff is scanned for private keys
  and common token/password patterns. If anything matches, the commit is
  blocked and the matched value is never shown; you can review the file and
  line, or explicitly choose to commit anyway.
- **Refusals instead of guesses.** Pull is `--ff-only` and refuses a dirty
  worktree, untracked files, a diverged branch or a missing upstream. Restow
  runs a dry run first and refuses on conflicts. Adopt refuses when the
  destination already exists and rolls back if stowing conflicts. Publish
  refuses a selected path that no longer exists and that git does not track — it
  names every invalid path and commits nothing (`Can't publish 1 selected file:
  it no longer exists and git doesn't track it — <path>. Refresh the list and
  try again.`). There is no discard or revert action.
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
- **What it writes.** Only your config (created once; a **Skip on this machine**
  confirms and then writes it, through the Stow link when it is one, so the real
  file inside your dotfiles changes and the link stays a link) and the plugin's
  own state directory (`baseline.json`, `publish.json`, `notify.json`,
  `setup-plan.json`, `setup-progress.json`, `setup-backups/`). Every write is
  atomic: an exclusive `0600` temp file inside the target directory, `fsync`,
  then `os.replace`; the state directory is `0700`. A config link that points
  outside `$HOME` is refused, never followed. The plugin never writes to a
  repository or to a tracked config unless you press a mutating action.
- **Processes.** Every external command runs as a fixed argument vector, never
  through a shell, with a hard timeout and a bounded, killable process group.
  Git runs with terminal prompts disabled, `GIT_ASKPASS=true` and
  `ssh -oBatchMode=yes`; `gh` runs with prompts disabled. Commit messages and
  other payloads go on **stdin**, never in `argv`, and a repository URL that
  embeds a credential is rejected before it reaches `git`.
- **Secrets.** Nothing sensitive is logged or stored. The pre-commit secret scan
  reports only the file, line and rule, never the matched value, and
  credential-bearing URLs are stripped from every diagnostic string. It knows
  the shapes that carry a credential inside the URL itself — Discord, Slack and
  Teams webhooks, Sentry DSNs and cron check-ins, and any `https://user:pass@` or
  `https://<token>@` URL — plus settings whose name says secret. Authentication
  is delegated entirely to your existing Git/`gh` configuration.
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
- A package skipped on this machine (see [Per-machine
  skips](#per-machine-skips)) never counts as pending.
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
| `a` | Adopt the first new config (the row's filled button shows the recommendation) |
| `i` | Hide the focused change row |
| `Esc` | Close the panel / go back |

The panel draws no scroll bar: the mouse wheel, the touchpad and the arrow keys
scroll every list, so nothing sits over the cards or the panel edge.

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
