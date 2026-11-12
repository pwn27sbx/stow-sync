# Changelog

All notable changes to Stow Sync. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the plugin uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.1 - 2026-11-11

### Added

- **Upload is always reachable.** The Overview action row now carries an
  **Upload** button whenever any repository has commits ahead, and the Changes
  tab carries **Upload N commits**, even while another action (Publish, Update,
  Review, a package to fix) is the recommended one. Both open the same confirm
  card and push every repo that is ahead; before, Upload only existed as the
  primary button and disappeared as soon as anything else needed attention.
- **"Needs fixing" explains every package.** Each package is its own row with
  its state in plain words (**Missing links**, **A real file is in the way**,
  **Broken links**), its affected paths (first three, then "+N more") and one
  recommended action: **Link this** for a missing link, **Review** for a
  conflict or a broken link — never an automatic overwrite.
- **The link confirm shows the dry-run plan.** Pressing Link runs
  `stow --dry-run` for that one package and lists every action path by path
  ("will link X → Y", "will replace the link X with a folder" for an
  `UNLINK`/`MKDIR` pair, "conflict at Z"), names the package and says nothing
  else follows. Only a conflict-free pending package gets a **Link** button; a
  conflict, a broken link, a refused plan or an empty plan only closes.
- **Per-machine skips.** An optional `machines.<hostname>` section with
  `skip_packages` and `skip_paths` leaves a package or a path alone on one
  machine without affecting another, so a shared dotfiles config can say
  "`mise-mac` never restows here". A skipped package is out of health, the
  badge, the count, notifications and Needs fixing, and the Packages tab shows
  it as **Skipped on this machine**. **Skip on this machine** in a row shows the
  exact config change before saving it, and writes through the Stow link
  instead of replacing it; `skip --package|--path [--dry-run]` does the same
  from a terminal. The setup wizard also honours `machines.<host>.skip_packages`.
- **A broken `machines` section never crashes.** One clear error is reported in
  the panel and the section is ignored, which keeps today's behaviour.
- **Packages tab says when a check failed.** A package whose `stow` check
  crashed now shows **Check failed: <error>** instead of looking healthy.

### Changed

- **Fix packages is gone.** It restowed only the first unhealthy package and
  gave no guidance; every package now has its own row and its own action, so
  there is no multi-package walk to explain.

### Fixed

- **Writing the config through its Stow link.** `ignore`/`unignore` and the new
  skip action used to replace a symlinked `config.json` with a regular file.
  The real file is now resolved with `realpath` and written only when it stays
  inside `$HOME`; the link is preserved, and a link pointing outside `$HOME` is
  refused.
- **`restow --dry-run` reports conflicts with the plan** instead of failing
  before the panel can show what a package would do.

## 0.3.0 - 2026-11-07

### Added

- **New config candidates get a verdict and a reason.** The backend judges every
  candidate from its own bytes — no network, no model — and reports `never`,
  `ignore`, `upload` or `review` with a one-line plain reason: a credential
  store or a secret match is `never`, tool-generated launchers and machine state
  are `ignore`, a small text config with no machine-specific path is `upload`,
  and everything doubtful is `review`. Reads are bounded, so `status` stays fast
  and a bound turns into `review` instead of a guess.
- **Hidden group.** `never` and `ignore` candidates move out of the new-config
  list into a collapsible **Hidden** group that keeps their reason. `never`
  offers no Adopt button; `ignore` can still be adopted by hand. Neither writes
  to the config's `ignore` list.
- **Accept recommendations (N).** One click in the New config files card (or the
  Overview banner) adopts every `upload` candidate through the existing Adopt
  path, after a confirm card that lists each path, package and reason. Nothing
  is committed or uploaded: publishing stays the Publish step.
- `status` candidates now carry `verdict` and `reason`.
- **The secret scan knows credentials carried inside a URL.** Discord, Slack and
  Teams webhooks, a Sentry DSN or cron check-in URL, any `https://user:pass@` or
  `https://<token>@` URL, and an env-style setting whose name says secret
  (`*_WEBHOOK`, `*_DSN`, `*_TOKEN`, `*_SECRET`, `*_KEY`, `*_PASSWORD` with a
  non-empty value) are now `never` in a candidate and block a commit. A `never`
  reason names the rule that matched ("canary.env: Discord webhook URL; never
  stow it"), never the value.
- **Owner-only files and project-bound units are `review`.** A candidate nobody
  but its owner can read (mode `600`, or any mode without group/other read) is
  not recommended for upload: git records only the executable bit, so stowing and
  publishing it would widen who can read it. A user unit whose `ExecStart` points
  into `~/Projects`, and a `.timer`/`.path` that triggers such a service, belong
  to that project rather than to dotfiles.
- **Every candidate row says its pick.** The row names the choice in plain
  words — **Recommended: Adopt**, **Recommended: Ignore**, **Suggested: Ignore**
  or **Never stow this** — and fills that button with the accent colour; the
  other stays a quiet outline. A `review` row now suggests the safer Ignore with
  a short why instead of leaving both buttons equal: a project-bound unit says
  it belongs to the project in `~/Projects`, an owner-only file says it is
  private, and any other doubt says to check it first. A `never` row keeps no
  Adopt button, as a credential store always did.
- **One colour rule on every surface.** Accent means the recommended choice,
  muted grey is state or information, red is never. The same rule covers the
  Hidden rows and the group's **Accept recommendations (N)** action: an
  already-ignored row shows a neutral **✓ Ignored** state chip (muted text, no
  accent, the button radius, the check next to the word) with a quiet **Adopt
  anyway** instead of a lonely opposite button. A permanent legend under the
  status sentence — a soft accent strip (8 % fill, 35 % border, no icon), "The
  highlighted button is the recommended choice." — and the help overlay state the
  rule once, including the accent/grey/red sentence.

### Changed

- The panel no longer draws a scroll bar, which collided with the cards and the
  panel border: the mouse wheel, the touchpad and the arrow keys still scroll
  every list, and the content keeps the panel padding.
- The new-config badge, the Overview banner sentence, the bar tone and the `a`
  key count only `upload` and `review` candidates; the `a` key prefers a
  recommendation and never picks a hidden one.
- Candidate reasons are specific to the file: an `upload` names the file and
  what it holds (TOML sections, JSON with your own comments, a script) and
  states only what the scan proved ("no secret match"), instead of a generic
  "no private data found". A directory names the files inside it, and a reason
  stays one line.

### Fixed

- A D-Bus interface name is no longer read as a secret setting: a portal config
  key such as `org.freedesktop.impl.portal.Secret` is a plain desktop config,
  while `secret=`, `client_secret=` and `API_SECRET=` still count as secrets.
- A machine-state name (a real SQLite file, an oversized log) stays `ignore`
  instead of falling into `review`, and a secret in the readable bytes still
  wins over that name.
- An empty new-config folder, or one holding only empty machine-state folders,
  is `ignore` with a "nothing to keep" reason instead of asking for a decision
  with nothing inside to adopt.
- The Accept recommendations confirm card replays the plan it listed, so a
  background refresh while the card is open cannot change the approved paths.
- The generic `assignment` secret rule only reads a value from the line below its
  key when the key is YAML-style (`password:`), so an empty `SOMETHING_TOKEN=` in
  an env file no longer borrows the next setting's name, while a hand-edited YAML
  value — base64 padding and a `user:pass` pair included — is still caught.
