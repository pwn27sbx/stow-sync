# Changelog

All notable changes to Stow Sync. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the plugin uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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
- **One colour rule on every surface.** The same accent/quiet rule now covers
  the Hidden rows and the group's **Accept recommendations (N)** action: an
  already-ignored row shows a **✓ Ignored** chip with a quiet **Adopt anyway**
  instead of a lonely opposite button. A permanent legend under the status
  sentence — a soft accent callout with an info icon, "The highlighted button is
  the recommended choice." — and the help overlay state the rule once.

### Changed

- The new-config badge, the Overview banner sentence, the bar tone and the `a`
  key count only `upload` and `review` candidates; the `a` key prefers a
  recommendation and never picks a hidden one.
- Candidate reasons are specific to the file: an `upload` names the file and
  what it holds (TOML sections, JSON with your own comments, a script) and
  states only what the scan proved ("no secret match"), instead of a generic
  "no private data found". A directory names the files inside it, and a reason
  stays one line.

### Fixed

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
