.pragma library

// Pure presentation model for the Stow Sync bar badge and panel.
//
// Every export here is a pure function with no QML objects and no side
// effects, so tests/run-model-tests.js can load the file through node:vm and
// exercise every branch with fixed fixtures. The QML panel only reads the
// row objects it returns.

// Severity mirrors the backend's _STATE_RANK (README section 5.1) plus the
// UI-only "secret-blocked" state and "candidates" (a non-empty new-config
// list). It only orders states for the badge color; it never updates data.
var STATE_RANK = {
  clean: 0,
  behind: 10,
  ahead: 20,
  pending: 25,
  "no-upstream": 30,
  dirty: 40,
  detached: 50,
  dangling: 55,
  diverged: 60,
  conflict: 65,
  operation: 70,
  missing: 80,
  candidates: 90,
  "secret-blocked": 100
}

var STATE_TITLES = {
  clean: "Clean",
  behind: "Behind remote",
  ahead: "Unpushed commits",
  pending: "Unstowed package",
  "no-upstream": "No upstream",
  dirty: "Uncommitted changes",
  detached: "Detached HEAD",
  dangling: "Dangling link",
  diverged: "Diverged",
  conflict: "Stow conflict",
  operation: "Operation in progress",
  missing: "Repository missing",
  candidates: "New configs",
  "secret-blocked": "Secrets blocked"
}

// Package ``health`` -> the state name it maps onto.
var HEALTH_STATE = {
  conflicts: "conflict",
  pending: "pending",
  dangling: "dangling"
}

function num(value, fallback) {
  var n = Number(value)
  return (n === n && n !== Infinity && n !== -Infinity) ? n : fallback
}

function stateRank(state) {
  var rank = STATE_RANK[String(state)]
  return rank === undefined ? 0 : rank
}

// Token name for a state; the panel resolves it against Color.*.
function stateColor(state) {
  var s = state === undefined || state === null ? "" : String(state)
  if (s === "conflict" || s === "diverged" || s === "operation" || s === "missing" || s === "secret-blocked")
    return "urgent"
  if (s === "dirty" || s === "ahead" || s === "behind" || s === "candidates" || s === "pending" || s === "dangling" || s === "no-upstream" || s === "detached")
    return "accent"
  return "muted"
}

// Package health reuses the state palette: conflicts are urgent, pending and
// dangling links are accent, healthy packages are muted.
function healthColor(health) {
  return stateColor(HEALTH_STATE[String(health)] || "clean")
}

function healthState(health) {
  return HEALTH_STATE[String(health)] || "clean"
}

function stateTitle(state) {
  var title = STATE_TITLES[String(state)]
  return title === undefined ? "Unknown" : title
}

// Branch plus ahead/behind, e.g. "main - 2 ahead - 1 behind". Empty branch
// falls back to the detached marker; a repo with neither stays blank.
function repoSubtitle(repo) {
  if (!repo) return ""
  var parts = []
  var branch = repo.branch ? String(repo.branch) : ""
  if (branch) parts.push(branch)
  else if (String(repo.state) === "detached") parts.push("detached")
  var ahead = num(repo.ahead, 0)
  var behind = num(repo.behind, 0)
  if (ahead > 0) parts.push(ahead + " ahead")
  if (behind > 0) parts.push(behind + " behind")
  return parts.join("  -  ")
}

function badgeCount(data) {
  if (!data || !data.summary) return 0
  var count = num(data.summary.count, 0)
  return count > 0 ? Math.floor(count) : 0
}

// Empty string hides the badge; over 99 collapses to "99+".
function badgeText(data) {
  var count = badgeCount(data)
  if (count <= 0) return ""
  return count > 99 ? "99+" : String(count)
}

// Worst state across the summary, every repo/package and the new-config list.
function worstState(data) {
  var states = []
  if (!data) return "clean"
  if (data.secret_blocked) states.push("secret-blocked")
  if (data.summary && data.summary.state) states.push(String(data.summary.state))
  var repos = data.repos || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    states.push(String(repo.state || "clean"))
    var packages = repo.packages || []
    for (var j = 0; j < packages.length; j++) states.push(healthState(packages[j].health))
  }
  var candidates = data.candidates || []
  for (var k = 0; k < candidates.length; k++) {
    if (!candidates[k].known) { states.push("candidates"); break }
  }
  var worst = "clean"
  for (var m = 0; m < states.length; m++) {
    if (stateRank(states[m]) > stateRank(worst)) worst = states[m]
  }
  return worst
}

function badgeColor(data) {
  return stateColor(worstState(data))
}

function formatSize(bytes) {
  var n = num(bytes, 0)
  if (n < 1024) return n + " B"
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB"
  if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB"
  return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB"
}

function packageLabel(name) {
  return name && String(name).length > 0 ? String(name) : "(root)"
}

function compareStrings(a, b) {
  var sa = String(a === undefined || a === null ? "" : a)
  var sb = String(b === undefined || b === null ? "" : b)
  if (sa < sb) return -1
  if (sa > sb) return 1
  return 0
}

// Changes grouped by package, packages sorted, paths sorted inside a package.
function groupChanges(changes) {
  var sorted = (changes || []).slice()
  sorted.sort(function(a, b) {
    var byPackage = compareStrings(a && a.package, b && b.package)
    return byPackage !== 0 ? byPackage : compareStrings(a && a.path, b && b.path)
  })
  var groups = []
  var current = null
  for (var i = 0; i < sorted.length; i++) {
    var change = sorted[i] || {}
    var name = change.package ? String(change.package) : ""
    if (!current || current.package !== name) {
      current = { package: name, label: packageLabel(name), items: [] }
      groups.push(current)
    }
    current.items.push(change)
  }
  return groups
}

function repoRow(repo, index) {
  var changes = (repo && repo.changes) || []
  var untracked = (repo && repo.untracked) || []
  var packages = (repo && repo.packages) || []
  var ahead = num(repo && repo.ahead, 0)
  var behind = num(repo && repo.behind, 0)
  var state = String((repo && repo.state) || "clean")
  var path = String((repo && repo.path) || "")
  var dirty = changes.length > 0 || untracked.length > 0
  var hasUpstream = !!(repo && repo.upstream)
  var basename = path.replace(/[\\/]+$/, "").split(/[\\/]/).pop()
  return {
    type: "repo",
    key: "repo:" + path,
    index: index,
    name: path,
    basename: basename || path,
    branch: String((repo && repo.branch) || ""),
    upstream: String((repo && repo.upstream) || ""),
    state: state,
    stateColor: stateColor(state),
    title: stateTitle(state),
    subtitle: repoSubtitle(repo),
    exists: !!(repo && repo.exists),
    ahead: ahead,
    behind: behind,
    operation: (repo && repo.operation) || null,
    fetchError: (repo && repo.fetch_error) || null,
    changesCount: changes.length,
    untrackedCount: untracked.length,
    packagesCount: packages.length,
    dirty: dirty,
    hasUpstream: hasUpstream,
    canCommit: !!(repo && repo.exists) && dirty,
    // A diverged branch would be rejected non-fast-forward, so push is only
    // meaningful when strictly ahead.
    canPush: !!(repo && repo.exists) && hasUpstream && ahead > 0 && behind === 0,
    canPull: !!(repo && repo.exists) && hasUpstream && behind > 0 && ahead === 0 && !dirty
  }
}

function changeRow(repoPath, change, index) {
  var c = change || {}
  var path = String(c.path || "")
  var untracked = !!c.untracked
  return {
    type: "change",
    key: "change:" + repoPath + ":" + path,
    index: index,
    repo: repoPath,
    path: path,
    package: c.package ? String(c.package) : "",
    packageLabel: packageLabel(c.package),
    kind: String(c.kind || (untracked ? "untracked" : "modified")),
    untracked: untracked,
    x: String(c.x || " "),
    y: String(c.y || " "),
    stateColor: "accent"
  }
}

function healthRow(repoPath, pkg, index) {
  var p = pkg || {}
  var name = String(p.name || "")
  var health = String(p.health || "ok")
  var pending = (p.pending_links || []).length
  var conflicts = (p.conflicts || []).length
  var dangling = (p.dangling || []).length
  return {
    type: "health",
    key: "health:" + repoPath + ":" + name,
    index: index,
    repo: repoPath,
    package: name,
    packageLabel: packageLabel(name),
    health: health,
    state: healthState(health),
    stateColor: healthColor(health),
    pending: pending,
    conflicts: conflicts,
    dangling: dangling,
    attention: health !== "ok"
  }
}

// One collapsed summary for a repo's healthy packages. The panel toggles
// `expanded`; when true, buildRows emits the healthy packages' health rows
// directly beneath this one so they can still be inspected.
function packagesOkRow(repoPath, count, expanded) {
  return {
    type: "packages-ok",
    key: "packages-ok:" + repoPath,
    repo: repoPath,
    count: count,
    expanded: !!expanded,
    label: pluralCount(count, "package") + " OK",
    stateColor: "muted"
  }
}

function candidateRow(candidate, index) {
  var c = candidate || {}
  var path = String(c.path || "")
  var known = !!c.known
  return {
    type: "candidate",
    key: "candidate:" + path,
    index: index,
    path: path,
    group: String(c.group || "watched"),
    known: known,
    suggestedPackage: String(c.suggested_package || ""),
    size: num(c.size, 0),
    sizeText: formatSize(c.size),
    itemType: String(c.type || "file"),
    stateColor: known ? "muted" : "accent"
  }
}

// Full deterministic display list: repos in config order, then per-repo
// changes grouped by package, then stow-health rows (unhealthy packages only)
// with one collapsed `packages-ok` summary per repo, then candidates with
// known:false first. The panel filters this for its collapsed group view.
// `options.expandedOk` names the repos whose healthy packages are expanded.
function buildRows(data, options) {
  var opts = options || {}
  var expandedOk = opts.expandedOk || []
  var rows = []
  if (!data) return rows
  var repos = data.repos || []
  for (var r = 0; r < repos.length; r++) {
    var repo = repos[r] || {}
    var repoPath = String(repo.path || ("repo" + r))
    rows.push(repoRow(repo, r))
    // Tracked changes and untracked files become one committable change list,
    // grouped by package then sorted by path.
    var changes = []
    var tracked = repo.changes || []
    for (var t = 0; t < tracked.length; t++) changes.push(tracked[t])
    var untracked = repo.untracked || []
    for (var u = 0; u < untracked.length; u++) {
      changes.push({ path: untracked[u] && untracked[u].path, package: untracked[u] && untracked[u].package, untracked: true })
    }
    changes.sort(function(a, b) {
      var byPackage = compareStrings(a && a.package, b && b.package)
      return byPackage !== 0 ? byPackage : compareStrings(a && a.path, b && b.path)
    })
    for (var c = 0; c < changes.length; c++) rows.push(changeRow(repoPath, changes[c], c))
    var packages = (repo.packages || []).slice().sort(function(a, b) {
      return compareStrings(a && a.name, b && b.name)
    })
    var healthy = []
    for (var p = 0; p < packages.length; p++) {
      if (String((packages[p] && packages[p].health) || "ok") === "ok") healthy.push(packages[p])
      else rows.push(healthRow(repoPath, packages[p], p))
    }
    if (healthy.length > 0) {
      var isExpanded = expandedOk.indexOf(repoPath) >= 0
      rows.push(packagesOkRow(repoPath, healthy.length, isExpanded))
      if (isExpanded) for (var h = 0; h < healthy.length; h++) rows.push(healthRow(repoPath, healthy[h], h))
    }
  }
  var candidates = (data.candidates || []).slice().sort(function(a, b) {
    var ra = (a.known ? 10 : 0) + (a.group === "watched" ? 0 : 1)
    var rb = (b.known ? 10 : 0) + (b.group === "watched" ? 0 : 1)
    return ra !== rb ? ra - rb : compareStrings(a && a.path, b && b.path)
  })
  for (var i = 0; i < candidates.length; i++) rows.push(candidateRow(candidates[i], i))
  return rows
}

// --------------------------------------------------------------------------
// View-model helpers. Panel.qml stays a thin shell; the ordering, filtering
// and argv/stdin shaping below are pure and unit-tested.
// --------------------------------------------------------------------------

// Full row list filtered for the collapsed "Existing untracked" group, with
// the group header stamped on the first candidate of each category.
// `options.showExisting` reveals known candidates; `options.expandedOk` names
// the repos whose healthy packages are expanded.
function panelRows(data, options) {
  var opts = options || {}
  var showExisting = opts.showExisting === true
  var all = buildRows(data, { expandedOk: opts.expandedOk || [] })
  var fresh = 0
  var known = 0
  for (var i = 0; i < all.length; i++) {
    if (all[i].type !== "candidate") continue
    if (all[i].known) known++
    else fresh++
  }
  var rows = []
  var existing = []
  var lastCategory = ""
  for (var j = 0; j < all.length; j++) {
    var row = all[j]
    if (row.type === "candidate") {
      if (row.known && !showExisting) continue
      var category = row.known ? "existing" : "new"
      row.header = category !== lastCategory
        ? (row.known ? "Existing untracked (" + known + ")" : "New configs (" + fresh + ")")
        : ""
      row.showBulk = row.known && row.header !== ""
      lastCategory = category
      if (row.known) existing.push(row.path)
    } else {
      lastCategory = ""
    }
    rows.push(row)
  }
  return { rows: rows, newCount: fresh, existingCount: known, existingPaths: existing }
}

// True when nothing in the config needs the user: every existing repo has no
// changes or untracked files, is neither ahead nor behind, and has only
// healthy packages, and no unknown candidate is waiting. `aux.newCount` is the
// panel's already-computed unknown-candidate count; when omitted it is derived
// from `data.candidates`. Known candidates do NOT block the empty state — the
// panel keeps its collapsed "Show untracked" toggle.
function isEmpty(data, aux) {
  if (!data) return false
  var repos = data.repos || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    if (repo.exists === false) return false
    if ((repo.changes || []).length > 0) return false
    if ((repo.untracked || []).length > 0) return false
    if (num(repo.ahead, 0) !== 0) return false
    if (num(repo.behind, 0) !== 0) return false
    var packages = repo.packages || []
    for (var j = 0; j < packages.length; j++) {
      if (String((packages[j] && packages[j].health) || "ok") !== "ok") return false
    }
  }
  var fresh
  if (aux && aux.newCount !== undefined && aux.newCount !== null) fresh = num(aux.newCount, 0)
  else {
    fresh = 0
    var candidates = data.candidates || []
    for (var k = 0; k < candidates.length; k++) if (!candidates[k].known) fresh++
  }
  return fresh === 0
}

function selectedPaths(rows, checked, repo) {
  var paths = []
  for (var i = 0; i < (rows || []).length; i++) {
    var row = rows[i]
    if (row.type !== "change" || String(row.repo) !== String(repo)) continue
    if (checked && checked[row.key] === false) continue
    paths.push(row.path)
  }
  return paths
}

function packageFor(row, overrides) {
  var override = overrides ? overrides[row.key] : undefined
  if (override !== undefined && override !== null && override !== "") return String(override)
  if (row.suggestedPackage) return String(row.suggestedPackage)
  var base = String(row.path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop()
  return base.toLowerCase()
}

function moveCursorIndex(rows, cursor, dx, dy) {
  if (!rows || rows.length === 0) return 0
  var step = dy !== 0 ? dy : (dx > 0 ? 1 : -1)
  var next = num(cursor, 0) + step
  if (next < 0) next = 0
  if (next > rows.length - 1) next = rows.length - 1
  return next
}

function sectionStarts(rows) {
  var starts = []
  for (var i = 0; i < (rows || []).length; i++) {
    if (rows[i].type === "repo") starts.push(i)
    else if (rows[i].type === "candidate" && (i === 0 || rows[i - 1].type !== "candidate")) starts.push(i)
  }
  return starts
}

// Confirm card copy per mutation kind.
function confirmSpec(kind, payload) {
  var p = payload || {}
  if (kind === "push") return {
    title: "Push " + String(p.repo || ""),
    message: "Push the current branch to " + String(p.upstream || "the remote") + ".",
    lines: [], confirmText: "Push", destructive: false
  }
  if (kind === "pull") return {
    title: "Update " + String(p.repo || ""),
    message: "Fast-forward only; refuses when the worktree is dirty or diverged.",
    lines: [], confirmText: "Update", destructive: false
  }
  if (kind === "upload") return {
    title: "Upload commits",
    message: "Push the current branch to GitHub.",
    lines: (p.repos || []).slice(), confirmText: "Upload", destructive: false
  }
  if (kind === "update") return {
    title: "Update from GitHub",
    message: "Fast-forward only; refuses when a repo is dirty or diverged.",
    lines: (p.repos || []).slice(), confirmText: "Update", destructive: false
  }
  if (kind === "restow") return {
    title: "Restow " + String(p.package || ""),
    message: "Dry-run first; conflicts abort the restow.",
    lines: [String(p.repo || ""), "package: " + String(p.package || "")],
    confirmText: "Restow", destructive: false
  }
  if (kind === "adopt") return {
    title: "Adopt into " + String(p.repo || ""),
    message: "Move the path into the repo and stow it back as a symlink.",
    lines: [String(p.path || ""), "package: " + String(p.package || "")],
    confirmText: "Adopt", destructive: false
  }
  if (kind === "ignore") return {
    title: "Ignore path",
    message: "This path will no longer be reported as a candidate.",
    lines: [String(p.path || "")], confirmText: "Ignore", destructive: false
  }
  if (kind === "ignore-all") return {
    title: "Ignore all shown",
    message: "These paths will no longer be reported.",
    lines: (p.paths || []).slice(), confirmText: "Ignore all", destructive: true
  }
  if (kind === "baseline") return {
    title: "Mark all as known",
    message: "Every current candidate becomes known; the badge drops to zero for them.",
    lines: ["New configs: " + num(p.count, 0)], confirmText: "Mark known", destructive: false
  }
  if (kind === "setup-undo") return {
    title: "Undo this setup",
    message: String(p.sentence || "Unlink the linked packages and put back the original files."),
    lines: p.backup ? [String(p.backup)] : [], confirmText: "Undo", destructive: true
  }
  return { title: "", message: "", lines: [], confirmText: "Confirm", destructive: false }
}

// Argv + stdin for a confirmed mutation.
function mutationFor(kind, payload) {
  var p = payload || {}
  if (kind === "push") return { tag: "push", args: ["push", "--repo", p.repo], stdin: "" }
  if (kind === "pull") return { tag: "pull", args: ["pull", "--repo", p.repo], stdin: "" }
  if (kind === "restow") return { tag: "restow", args: ["restow", "--repo", p.repo, "--package", p.package], stdin: "" }
  if (kind === "adopt") return { tag: "adopt", args: ["adopt", "--repo", p.repo, "--package", p.package, "--path", p.path], stdin: "" }
  if (kind === "ignore") return { tag: "ignore", args: ["ignore"], stdin: JSON.stringify([p.path]) }
  if (kind === "ignore-all") return { tag: "ignore", args: ["ignore"], stdin: JSON.stringify(p.paths || []) }
  if (kind === "baseline") return { tag: "baseline", args: ["baseline", "--reset"], stdin: "" }
  return { tag: kind, args: [], stdin: "" }
}

function secretLines(secrets) {
  return (secrets || []).map(function(secret) {
    return String(secret.path) + ":" + String(secret.line) + " (" + String(secret.rule) + ")"
  })
}

function pickerOptions(packages, suggested, current) {
  var out = (packages || []).slice()
  if (suggested && out.indexOf(String(suggested)) < 0) out.unshift(String(suggested))
  if (current && out.indexOf(String(current)) < 0) out.unshift(String(current))
  return out
}

function commitPayload(message, paths, allowSecrets) {
  var payload = { message: message, paths: paths }
  if (allowSecrets) payload.allow_secrets = true
  return JSON.stringify(payload)
}

// First existing repo (falling back to the first configured one) plus its
// package names — the default adopt target and the picker option list.
function adoptTarget(repos) {
  var list = repos || []
  var repo = ""
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].exists) { repo = String(list[i].path); break }
  }
  if (repo === "" && list.length > 0 && list[0]) repo = String(list[0].path)
  var packages = []
  for (var j = 0; j < list.length; j++) {
    if (!list[j] || String(list[j].path) !== repo) continue
    var names = list[j].packages || []
    for (var k = 0; k < names.length; k++) if (names[k].name) packages.push(String(names[k].name))
  }
  return { repo: repo, packages: packages }
}

function findRepo(repos, path) {
  for (var i = 0; i < (repos || []).length; i++) {
    if (String(repos[i].path) === String(path)) return repos[i]
  }
  return null
}

// Index of the next section start in `direction`, wrapping around.
function nextSectionIndex(rows, cursor, direction) {
  var starts = sectionStarts(rows)
  if (starts.length === 0) return -1
  var current = 0
  for (var i = 0; i < starts.length; i++) if (starts[i] <= cursor) current = i
  var next = current + (direction >= 0 ? 1 : -1)
  if (next < 0) next = starts.length - 1
  if (next >= starts.length) next = 0
  return starts[next]
}

// Classify an action result so the panel applies one outcome, not a switch.
function actionOutcome(tag, payload) {
  var data = payload || {}
  if (tag === "diff") return { kind: "diff", body: String(data.text || ""), truncated: data.truncated === true }
  if (tag === "suggest") return { kind: "suggest", message: String(data.message || "") }
  if (tag === "commit" || tag === "publish-commit") {
    if (!data.ok) {
      if (data.secrets && data.secrets.length > 0) return { kind: "commit-secrets", secrets: data.secrets }
      return { kind: "commit-error", error: String(data.error || "Commit failed.") }
    }
    return { kind: "commit-ok" }
  }
  if (!data.ok) return { kind: "mutation-error", error: String(data.error || "Action failed.") }
  if (data.push_error) return { kind: "mutation-error", error: String(data.push_error) }
  return { kind: "mutation-ok" }
}

function failureOutcome(tag, message) {
  if (tag === "status" || tag === "status-fetch") return { kind: "status-error", error: String(message || "") }
  if (tag === "commit" || tag === "publish-commit") return { kind: "commit-error", error: String(message || "") }
  if (tag === "suggest") return { kind: "ignore" }
  return { kind: "mutation-error", error: String(message || "") }
}

function activateIntent(row) {
  if (!row) return { kind: "none" }
  if (row.type === "repo") return { kind: "commit", repo: String(row.name || "") }
  if (row.type === "change") return { kind: "diff", repo: String(row.repo || ""), path: String(row.path || "") }
  if (row.type === "health") return { kind: "restow", repo: String(row.repo || ""), package: String(row.package || "") }
  if (row.type === "packages-ok") return { kind: "toggle-ok" }
  return { kind: "adopt" }
}

// --------------------------------------------------------------------------
// Unit 4c: the hero, the single primary action and the per-tab row builders.
// All pure so the QML stays a thin renderer.
// --------------------------------------------------------------------------

var HERO_GLYPH = {
  check: "\uf00c",
  warn: "\uf071",
  changes: "\uf044",
  upload: "\uf093",
  update: "\uf019",
  new: "\uf067",
  setup: "\uf109"
}

// "~/.dotfiles" -> "dotfiles"; "~/wallpapers/" -> "wallpapers".
function repoDisplayName(path) {
  var s = String(path === undefined || path === null ? "" : path)
  if (s === "") return ""
  var base = s.replace(/[\\/]+$/, "").split(/[\\/]/).pop()
  if (!base) return s
  if (base.charAt(0) === ".") base = base.slice(1)
  return base || s
}

function fetchClock(iso) {
  var match = String(iso === undefined || iso === null ? "" : iso).match(/T(\d{2}:\d{2})/)
  return match ? match[1] : ""
}

// Most recent "HH:MM" across the repos, or "" when nothing was fetched.
function latestFetchClock(data) {
  var latest = ""
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var clock = fetchClock(repos[i] && repos[i].last_fetch)
    if (clock > latest) latest = clock
  }
  return latest
}

function repoChangeCount(repo) {
  var r = repo || {}
  return ((r.changes || []).length) + ((r.untracked || []).length)
}

// Total changed+untracked files across repos and the display names of the
// repos that contribute them (config order, no duplicates).
function changeTotals(data) {
  var count = 0
  var names = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var n = repoChangeCount(repos[i])
    if (n <= 0) continue
    count += n
    names.push(repoDisplayName(repos[i] && repos[i].path))
  }
  return { count: count, repos: names }
}

// Sum a flow counter ("ahead"/"behind") and the repos that have it.
function flowTotals(data, key) {
  var count = 0
  var names = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var value = num(repos[i] && repos[i][key], 0)
    if (value <= 0) continue
    count += value
    names.push(repoDisplayName(repos[i] && repos[i].path))
  }
  return { count: count, repos: names }
}

// Overview gating for a machine that is not set up (finding 76): while not set
// up the Overview shows only the setup card, hides the management actions, and
// keeps at most a one-line "Updates available" hint.
function overviewState(data, opts) {
  var o = opts || {}
  var notSetUp = o.notSetUp === true
  var behind = flowTotals(data, "behind").count
  return {
    notSetUp: notSetUp,
    showSetupCard: notSetUp || o.setupNeeded === true,
    showManagement: !notSetUp,
    showUpdateHint: notSetUp && behind > 0,
    updateHint: behind > 0 ? "Updates available on GitHub" : ""
  }
}

// Candidates the owner has not acknowledged yet (the "New configs" list).
function newCandidateCount(data) {
  var candidates = (data && data.candidates) || []
  var count = 0
  for (var i = 0; i < candidates.length; i++) if (!candidates[i] || candidates[i].known !== true) count++
  return count
}

// The first unacknowledged candidate (falling back to the first candidate) —
// what the `a` key adopts. Null when there is nothing to adopt.
function firstNewCandidate(candidates) {
  var list = candidates || []
  var fallback = null
  for (var i = 0; i < list.length; i++) {
    if (!list[i]) continue
    if (list[i].known !== true) return list[i]
    if (fallback === null) fallback = list[i]
  }
  return fallback
}

// "https://github.com/pwn27sbx/dotfiles.git" -> "pwn27sbx/dotfiles" and
// "git@github.com:pwn27sbx/dotfiles.git" -> "pwn27sbx/dotfiles". The lane shows
// this short form; the copy button still copies the full URL.
function shortRemote(url) {
  var s = String(url === undefined || url === null ? "" : url).trim()
  if (s === "") return ""
  s = s.replace(/\.git$/, "")
  var scp = s.match(/^[^@]+@[^:]+:(.+)$/)
  if (scp) s = scp[1]
  else {
    s = s.replace(/^[a-z+]+:\/\//i, "")
    var slash = s.indexOf("/")
    if (slash >= 0) s = s.slice(slash + 1)
  }
  var parts = []
  var raw = s.split("/")
  for (var i = 0; i < raw.length; i++) if (raw[i] !== "") parts.push(raw[i])
  if (parts.length >= 2) return parts.slice(-2).join("/")
  return s
}

function unhealthyCount(repo) {
  var packages = (repo && repo.packages) || []
  var count = 0
  for (var i = 0; i < packages.length; i++) {
    if (String((packages[i] && packages[i].health) || "ok") !== "ok") count++
  }
  return count
}

// Plain-words label for a package health token (the Overview "Needs fixing"
// rows and the "Fix packages" button).
function healthLabel(health) {
  var h = String(health === undefined || health === null ? "ok" : health)
  if (h === "conflicts") return "conflict"
  if (h === "pending") return "pending link"
  if (h === "dangling") return "dangling link"
  return h
}

// First unhealthy package in repo/package order, or null when every package is
// healthy. The Overview "Fix packages" button restows exactly this package.
function firstUnhealthy(data) {
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var packages = (repos[i] && repos[i].packages) || []
    for (var j = 0; j < packages.length; j++) {
      if (String((packages[j] && packages[j].health) || "ok") !== "ok")
        return { repo: String((repos[i] && repos[i].path) || ""), package: String((packages[j] && packages[j].name) || "") }
    }
  }
  return null
}

// The first thing that needs the owner's attention, with a plain-words hint
// that names the repo. Returns null when nothing blocks save/sync.
function attentionFor(data) {
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var name = repoDisplayName(repo.path)
    var state = String(repo.state || "clean")
    if (state === "missing") return { repo: repo.path, hint: name + " is missing" }
    if (state === "operation") return { repo: repo.path, hint: name + " has a git " + String(repo.operation || "operation") + " in progress" }
    if (state === "diverged") return { repo: repo.path, hint: name + " has changes on both sides; it needs a manual merge" }
    if (state === "conflict") return { repo: repo.path, hint: name + " can't be stowed (a file is in the way)" }
    var packages = repo.packages || []
    for (var j = 0; j < packages.length; j++) {
      if (String((packages[j] && packages[j].health) || "ok") === "conflicts")
        return { repo: repo.path, hint: name + " can't be stowed (a file is in the way)" }
    }
  }
  return null
}

// Legacy helper: the singular/plural fragments carry their own leading space
// (e.g. plural(1, " change", " changes") -> "1 change"). Kept for the prose
// callers; new count+unit sites should use pluralCount/pluralUnit.
function plural(count, singular, pluralForm) {
  return count + (count === 1 ? singular : pluralForm)
}

// Number plus a pluralized noun: "1 change" / "2 changes" / "0 items". Pass
// pluralForm for a noun that does not just add an "s" (e.g. "person",
// "people"). Non-numeric counts fall back to 0 via num().
function pluralCount(count, singular, pluralForm) {
  var n = num(count, 0)
  return n + " " + (n === 1 ? singular : (pluralForm !== undefined ? pluralForm : singular + "s"))
}

// Bare pluralized unit word for a count+unit card: pluralUnit(1, "file") is
// "file" and every other count is "files" (or the supplied pluralForm).
function pluralUnit(count, singular, pluralForm) {
  return num(count, 0) === 1 ? singular : (pluralForm !== undefined ? pluralForm : singular + "s")
}

// The rendered label of a group header: the count and a BARE unit noun, so
// groupCountLabel(6, "packages") is "6 packages" (never "6 6 packages", the
// 11d regression). A negative count means "no count".
function groupCountLabel(count, unit) {
  var n = num(count, -1)
  if (n < 0) return ""
  var u = String(unit === undefined || unit === null ? "" : unit)
  return String(n) + (u !== "" ? " " + u : "")
}

// --- bar icon overlays (Unit 7) ------------------------------------------
// At most one status dot plus the up/down chevrons: the dot is `urgent` when
// anything needs attention (conflict/diverged/operation/stow conflict/missing),
// else `accent` when there are local changes or new configs, else none. `up`
// marks commits to upload (ahead), `down` commits to fetch (behind).
// `opts.blocked` (a commit stopped by the secret scan) forces the urgent dot.
function barIconState(data, opts) {
  var d = data || {}
  var o = opts || {}
  var urgent = o.blocked === true || attentionFor(d) !== null
  var pending = changeTotals(d).count > 0 || newCandidateCount(d) > 0
  return {
    dot: urgent ? "urgent" : (pending ? "accent" : "none"),
    up: flowTotals(d, "ahead").count > 0,
    down: flowTotals(d, "behind").count > 0
  }
}

// Bar icon glyphs (README unit "bar icon redesign"): one Nerd Font Material Design
// glyph, with a refresh glyph while a request runs and a tiny up/down arrow overlay.
var BAR_GLYPH_IDLE = "\u{F0D0B}" // md-folder_sync (owner pick after comparing it with swap-horizontal-bold)
var BAR_GLYPH_BUSY = "\u{F006A}" // md-autorenew (circular, clearly different from the idle arrows)
var BAR_GLYPH_UP = "\u{F005D}"   // md-arrow_up
var BAR_GLYPH_DOWN = "\u{F0045}" // md-arrow_down

// The bar glyph: the refresh glyph while busy, the swap-arrows glyph otherwise.
function barIconGlyph(busy) {
  return busy === true ? BAR_GLYPH_BUSY : BAR_GLYPH_IDLE
}

// The bottom-right overlay glyph for barIconState()'s up/down flags. Ahead wins
// over behind (a diverged repo already shows the urgent dot).
function barArrowGlyph(state) {
  var s = state || {}
  if (s.up === true) return BAR_GLYPH_UP
  if (s.down === true) return BAR_GLYPH_DOWN
  return ""
}

// Top-of-panel state: one glyph, one plain sentence and one hint line.
// `now` is the panel's current "HH:MM" used only when no fetch time exists.
// `opts.machineSetup` (the opt-in switch) turns a fresh machine into a
// "not set up yet" state instead of the attention/publish text (README 10b.2).
function heroState(data, now, opts) {
  var d = data || {}
  var o = opts || {}
  if (o.notSetUp === true || (o.machineSetup === true && allReposMissing(d))) {
    return {
      glyph: HERO_GLYPH.setup,
      title: "This machine is not set up yet",
      hint: "Use Set up to download and link everything",
      tone: "accent"
    }
  }
  var attention = attentionFor(d)
  if (attention) return { glyph: HERO_GLYPH.warn, title: "Needs your attention", hint: attention.hint, tone: "urgent" }

  var changes = changeTotals(d)
  if (changes.count > 0) return {
    glyph: HERO_GLYPH.changes,
    title: plural(changes.count, " change to publish", " changes to publish"),
    hint: changes.repos.length > 0 ? "in " + changes.repos.join(", ") : "",
    tone: "accent"
  }

  var ahead = flowTotals(d, "ahead")
  if (ahead.count > 0) return {
    glyph: HERO_GLYPH.upload,
    title: plural(ahead.count, " commit waiting to be uploaded", " commits waiting to be uploaded"),
    hint: ahead.repos.length > 0 ? "in " + ahead.repos.join(", ") : "",
    tone: "accent"
  }

  var behind = flowTotals(d, "behind")
  if (behind.count > 0) return {
    glyph: HERO_GLYPH.update,
    title: "Updates available from GitHub",
    hint: behind.repos.length > 0 ? "in " + behind.repos.join(", ") : "",
    tone: "accent"
  }

  var fresh = newCandidateCount(d)
  if (fresh > 0) return {
    glyph: HERO_GLYPH.new,
    title: plural(fresh, " new config file not in Stow", " new config files not in Stow"),
    hint: "Review them to add them to a package",
    tone: "accent"
  }

  var checked = latestFetchClock(d) || String(now || "")
  return {
    glyph: HERO_GLYPH.check,
    title: "Everything is saved and synced",
    hint: "Last checked " + (checked !== "" ? checked : "just now"),
    tone: "muted"
  }
}

// One primary button under the hero, same precedence as the hero branches.
function primaryAction(data) {
  var d = data || {}
  if (attentionFor(d)) return { kind: "review", label: "Review" }
  if (changeTotals(d).count > 0) return { kind: "publish", label: "Publish" }
  if (flowTotals(d, "ahead").count > 0) return { kind: "upload", label: "Upload" }
  if (flowTotals(d, "behind").count > 0) return { kind: "update", label: "Update" }
  if (newCandidateCount(d) > 0) return { kind: "review-new", label: "Review new configs" }
  return { kind: "none", label: "" }
}

// One plain-words line for a repo card.
function repoPlainStatus(repo) {
  var r = repo || {}
  if (r.exists === false) return "Repository is missing"
  var changes = repoChangeCount(r)
  if (changes > 0) return plural(changes, " change to publish", " changes to publish")
  var state = String(r.state || "clean")
  if (state === "diverged") return "Changes on both sides — needs a manual merge"
  if (state === "operation") return "A git " + String(r.operation || "operation") + " is in progress"
  if (state === "detached") return "Detached HEAD"
  if (state === "no-upstream") return "No GitHub remote set"
  var behind = num(r.behind, 0)
  if (behind > 0) return plural(behind, " update available", " updates available")
  var ahead = num(r.ahead, 0)
  if (ahead > 0) return plural(ahead, " commit to upload", " commits to upload")
  var health = unhealthyCount(r)
  if (health > 0) return plural(health, " package needs fixing", " packages need fixing")
  return "Everything is saved and synced"
}

// Overview tab: one compact card per repo plus a Fix row per unhealthy package.
function overviewTabRows(data) {
  var rows = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var row = repoRow(repo, i)
    row.statusText = repoPlainStatus(repo)
    rows.push(row)
    var packages = (repo.packages || []).slice().sort(function(a, b) {
      return compareStrings(a && a.name, b && b.name)
    })
    for (var j = 0; j < packages.length; j++) {
      if (String((packages[j] && packages[j].health) || "ok") === "ok") continue
      rows.push(healthRow(String(repo.path || ""), packages[j], j))
    }
  }
  return rows
}

// Changes tab: changed + untracked files grouped by repo then package, with a
// group header stamped on the first row of each (repo, package) pair.
function changeTabRows(data) {
  var rows = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var repoPath = String(repo.path || "")
    var changes = []
    var tracked = repo.changes || []
    for (var t = 0; t < tracked.length; t++) changes.push(tracked[t])
    var untracked = repo.untracked || []
    for (var u = 0; u < untracked.length; u++) {
      changes.push({ path: untracked[u] && untracked[u].path, package: untracked[u] && untracked[u].package, untracked: true })
    }
    if (changes.length === 0) continue
    changes.sort(function(a, b) {
      var byPackage = compareStrings(a && a.package, b && b.package)
      return byPackage !== 0 ? byPackage : compareStrings(a && a.path, b && b.path)
    })
    var repoName = repoDisplayName(repoPath)
    var lastPackage = null
    for (var c = 0; c < changes.length; c++) {
      var row = changeRow(repoPath, changes[c], c)
      if (row.packageLabel !== lastPackage) {
        row.header = repoName + "  \u203a  " + row.packageLabel
        lastPackage = row.packageLabel
      } else {
        row.header = ""
      }
      rows.push(row)
    }
  }
  return rows
}

// New configs tab: new candidates at the top, then a collapsible "Existing
// untracked (N)" group row (type "group") whose known candidates appear only
// when expanded. The group row also carries the bulk-ignore action.
function candidateTabRows(data, options) {
  var opts = options || {}
  var showExisting = opts.showExisting === true
  var candidates = (data && data.candidates || []).slice().sort(function(a, b) {
    var ra = (a && a.known ? 10 : 0) + (a && a.group === "watched" ? 0 : 1)
    var rb = (b && b.known ? 10 : 0) + (b && b.group === "watched" ? 0 : 1)
    return ra !== rb ? ra - rb : compareStrings(a && a.path, b && b.path)
  })
  var rows = []
  var existingPaths = []
  var fresh = 0
  var known = 0
  for (var i = 0; i < candidates.length; i++) {
    if (candidates[i] && candidates[i].known === true) { known++; existingPaths.push(String(candidates[i].path || "")) }
    else fresh++
  }
  var headerSet = false
  for (var j = 0; j < candidates.length; j++) {
    if (candidates[j] && candidates[j].known === true) continue
    var row = candidateRow(candidates[j], j)
    row.header = headerSet ? "" : "New configs (" + fresh + ")"
    headerSet = true
    rows.push(row)
  }
  if (known > 0) {
    rows.push({
      type: "group", key: "candidates:existing", repo: "", count: known,
      label: "Existing untracked (" + known + ")", expanded: showExisting,
      showAction: showExisting, actionText: "Ignore all", stateColor: "muted"
    })
    if (showExisting) {
      for (var k = 0; k < candidates.length; k++) {
        if (candidates[k] && candidates[k].known === true) rows.push(candidateRow(candidates[k], k))
      }
    }
  }
  return { rows: rows, newCount: fresh, existingCount: known, existingPaths: existingPaths }
}

// Repos that have at least one checked change, with their selected paths and
// upstream. `repoFilter` (optional) narrows it to one repo. The publish confirm
// card and the publish plan both build on this.
function publishRepos(data, checked, repoFilter) {
  var out = []
  var filter = String(repoFilter === undefined || repoFilter === null ? "" : repoFilter)
  var rows = changeTabRows(data)
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var repoPath = String(repo.path || "")
    if (filter !== "" && repoPath !== filter) continue
    var paths = selectedPaths(rows, checked, repoPath)
    if (paths.length === 0) continue
    out.push({ repo: repoPath, paths: paths, upstream: String(repo.upstream || "") })
  }
  return out
}

// Flat FIFO plan for the Publish button: commit then push every repo that has
// checked changes and an upstream. Pure and ordered; the panel enqueues it.
function publishPlanFrom(list, message, allowSecrets) {
  var steps = []
  for (var i = 0; i < (list || []).length; i++) {
    steps.push({ tag: "publish-commit", args: ["commit", "--repo", list[i].repo], stdin: commitPayload(message, list[i].paths, allowSecrets) })
    if (list[i].upstream !== "") steps.push({ tag: "publish-push", args: ["push", "--repo", list[i].repo], stdin: "" })
  }
  return steps
}

function publishPlan(data, checked, message, allowSecrets) {
  return publishPlanFrom(publishRepos(data, checked), message, allowSecrets)
}

// Display names of the repos whose `metric` counter ("ahead"/"behind") is > 0.
function repoNames(data, metric) {
  var names = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    if (num(repos[i] && repos[i][metric], 0) > 0) names.push(repoDisplayName(repos[i].path))
  }
  return names
}

// One-line result copy for a completed single mutation.
function actionSuccessText(tag) {
  if (tag === "adopt") return "Adopted the file"
  if (tag === "restow") return "Fixed packages"
  if (tag === "ignore") return "Ignored the path"
  if (tag === "baseline") return "Marked all as known"
  if (tag === "push") return "Uploaded commits"
  if (tag === "pull") return "Updated from GitHub"
  return "Done"
}

function publishSummaryText(count, upstream) {
  return "Published " + count + (count === 1 ? " commit to " : " commits to ") + String(upstream || "GitHub")
}

// Everything the publish confirm card renders: the repo list plus flattened
// file lines and one "name → upstream" target line per repo.
function publishCard(data, checked, repoFilter) {
  var list = publishRepos(data, checked, repoFilter)
  var lines = []
  var targets = []
  for (var i = 0; i < list.length; i++) {
    for (var j = 0; j < list[i].paths.length; j++) lines.push(list[i].paths[j])
    targets.push(repoDisplayName(list[i].repo) + " \u2192 " + (list[i].upstream || "GitHub"))
  }
  return { list: list, lines: lines, targets: targets }
}

function commitStepCount(plan) {
  var count = 0
  for (var i = 0; i < (plan || []).length; i++) if (plan[i].tag === "publish-commit") count++
  return count
}

// Upload = push every repo that is ahead of its upstream.
function uploadPlan(data) {
  var steps = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    if (num(repo.ahead, 0) <= 0 || String(repo.upstream || "") === "") continue
    steps.push({ tag: "push", args: ["push", "--repo", String(repo.path || "")], stdin: "" })
  }
  return steps
}

// Update = fast-forward pull every repo that is behind its upstream.
function updatePlan(data) {
  var steps = []
  var repos = (data && data.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    if (num(repo.behind, 0) <= 0 || String(repo.upstream || "") === "") continue
    steps.push({ tag: "pull", args: ["pull", "--repo", String(repo.path || "")], stdin: "" })
  }
  return steps
}

// --------------------------------------------------------------------------
// Request queue (Runner's FIFO). Pure so the ordering/dedupe can be tested
// without QML; Runner.qml only mutates its Process around these results.
// --------------------------------------------------------------------------

// Append `request`, collapsing it into an identical *pending* status request.
// Two status requests with the same `fetch` flag are the same refresh, so a
// burst collapses into one; the existing request is always kept, so the queue
// never loses its runnable status request (never collapses to zero).
// The Runner must not start any request until BarWidget.injectPanel() has
// injected settings; otherwise the helper runs with the real default
// --config/--state-dir and touches the real HOME (README 11a fix). Requests
// queue until then. Strict booleans: a stray truthy value never opens the gate.
function runnerMayStart(settingsReady, hasPending) {
  return settingsReady === true && hasPending === true
}

function enqueue(queue, request) {
  var pending = (queue || []).slice()
  if (!request) return pending
  if (request.isStatus === true) {
    for (var i = 0; i < pending.length; i++) {
      if (pending[i] && pending[i].isStatus === true && pending[i].fetch === request.fetch) return pending
    }
  }
  pending.push(request)
  return pending
}

// Shift the front request; `{request: null, queue}` when nothing is queued.
function nextRequest(queue) {
  var pending = (queue || []).slice()
  if (pending.length === 0) return { request: null, queue: pending }
  return { request: pending.shift(), queue: pending }
}

// --------------------------------------------------------------------------
// Unit 4d: config-sync parity view models. All pure, all tested.
//
// Nerd Font glyphs, verified against the installed CaskaydiaCove Nerd Font
// (scripts in the plan folder pin the codepoints):
//   pencil        U+F040   (fa-pencil, stat tile "Changes")
//   cloud-upload  U+F0EE   (fa-cloud-upload, stat tile "To upload")
//   cloud-down    U+F0ED   (fa-cloud-download, stat tile "Updates")
//   file-plus     U+F0752  (md-file_plus, stat tile "New configs")
//   editor        U+E83A   (dev-neovim, package "nvim")
//   terminal      U+F120   (fa-terminal, packages "fish"/"zsh")
//   window        U+F2D0   (fa-window-maximize, "ghostty"/"tmux")
//   palette       U+F03D8  (md-palette, package "omarchy")
//   image         U+F03E   (fa-image, package "walls")
//   wrench        U+F0AD   (fa-wrench, "ai-tools"/"wallpaper-tint")
//   folder        U+F07B   (fa-folder, default package icon)
// --------------------------------------------------------------------------

var ICON = {
  changes: "\uf040",
  upload: "\uf0ee",
  updates: "\uf0ed",
  newConfigs: "\uf0752",
  editor: "\ue83a",
  terminal: "\uf120",
  window: "\uf2d0",
  palette: "\uf03d8",
  image: "\uf03e",
  wrench: "\uf0ad",
  folder: "\uf07b"
}

var PACKAGE_ICON_BY_NAME = {
  nvim: ICON.editor,
  fish: ICON.terminal,
  zsh: ICON.terminal,
  ghostty: ICON.window,
  tmux: ICON.window,
  omarchy: ICON.palette,
  walls: ICON.image,
  "ai-tools": ICON.wrench,
  "wallpaper-tint": ICON.wrench
}

// Exact name first, then a substring match (so "neovim"/"oh-my-zsh" hit),
// then the default folder.
function packageIcon(name) {
  var key = String(name || "")
  if (PACKAGE_ICON_BY_NAME[key] !== undefined) return PACKAGE_ICON_BY_NAME[key]
  for (var prefix in PACKAGE_ICON_BY_NAME) {
    if (key.indexOf(prefix) >= 0) return PACKAGE_ICON_BY_NAME[prefix]
  }
  return ICON.folder
}

// --- relative time (no Date object in the vm sandbox: parse ISO manually) --

function daysFromCivil(year, month, day) {
  var y = month <= 2 ? year - 1 : year
  var era = Math.floor(y / 400)
  var yoe = y - era * 400
  var doy = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1
  var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy
  return era * 146097 + doe - 719468
}

// Epoch milliseconds for an ISO 8601 string, or NaN when unparseable.
function parseIsoMillis(iso) {
  var text = String(iso === undefined || iso === null ? "" : iso)
  var m = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$/)
  if (!m) return NaN
  var year = Number(m[1])
  var month = Number(m[2])
  var day = Number(m[3])
  var hour = Number(m[4])
  var minute = Number(m[5])
  var second = Number(m[6] || 0)
  var ms = Math.floor(Number("0." + (m[7] || "0")) * 1000)
  var zone = m[8] || "Z"
  var offsetSeconds = 0
  if (zone !== "Z") {
    var z = zone.match(/^([+-])(\d{2}):?(\d{2})$/)
    var sign = z[1] === "-" ? -1 : 1
    offsetSeconds = sign * (Number(z[2]) * 60 + Number(z[3])) * 60
  }
  var days = daysFromCivil(year, month, day)
  return ((days * 86400) + hour * 3600 + minute * 60 + second - offsetSeconds) * 1000 + ms
}

// "3h ago", "just now", "1d ago", ... `now` accepts epoch milliseconds (as a
// number or a numeric string, the form the panel passes) or an ISO string;
// when omitted the value reads as "just now".
function relativeTime(iso, now) {
  var then = parseIsoMillis(iso)
  if (then !== then) return ""
  var current
  if (now === undefined || now === null || now === "") current = then
  else if (typeof now === "number") current = now
  else if (/^\d+$/.test(String(now))) current = Number(now)
  else current = parseIsoMillis(now)
  if (current !== current) current = then
  var diff = current - then
  if (diff < 0) diff = 0
  var seconds = Math.floor(diff / 1000)
  if (seconds < 45) return "just now"
  var minutes = Math.floor(seconds / 60)
  if (minutes < 60) return minutes + "m ago"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h ago"
  var days = Math.floor(hours / 24)
  if (days < 7) return days + "d ago"
  if (days < 30) return Math.floor(days / 7) + "w ago"
  if (days < 365) return Math.floor(days / 30) + "mo ago"
  return Math.floor(days / 365) + "y ago"
}

// --- explain: one plain-words paragraph for the Overview tab ---------------

function joinNames(names) {
  var list = names || []
  if (list.length === 0) return ""
  if (list.length === 1) return String(list[0])
  if (list.length === 2) return String(list[0]) + " and " + String(list[1])
  return list.slice(0, -1).join(", ") + " and " + list[list.length - 1]
}

function explain(data, opts) {
  var d = data || {}
  var o = opts || {}
  if (o.notSetUp === true || (o.machineSetup === true && allReposMissing(d))) {
    return "This machine is not set up yet. Use Set up to download your repos and link your configs."
  }
  var attention = attentionFor(d)
  if (attention) {
    return "Something needs your attention: " + attention.hint +
      ". Open Changes to review it before publishing."
  }
  var changes = changeTotals(d)
  if (changes.count > 0) {
    return "Your " + joinNames(changes.repos) + " have " +
      plural(changes.count, " local change", " local changes") +
      ". Review them in Changes, or Publish to save and upload everything."
  }
  var ahead = flowTotals(d, "ahead")
  if (ahead.count > 0) {
    return "You have " + plural(ahead.count, " commit", " commits") +
      " waiting to upload in " + joinNames(ahead.repos) + ". Upload to send them to GitHub."
  }
  var behind = flowTotals(d, "behind")
  if (behind.count > 0) {
    return "GitHub has " + plural(behind.count, " newer commit", " newer commits") +
      " for " + joinNames(behind.repos) + ". Update to bring them in."
  }
  var fresh = newCandidateCount(d)
  if (fresh > 0) {
    return plural(fresh, " new config file is", " new config files are") +
      " not in Stow yet. Open New configs to adopt or ignore them."
  }
  return "Everything is saved and synced. Nothing to do."
}

// --- statTiles: the 4 equal tiles on the Overview tab ----------------------

function statTiles(data) {
  var d = data || {}
  var changes = changeTotals(d).count
  var ahead = flowTotals(d, "ahead").count
  var behind = flowTotals(d, "behind").count
  var fresh = newCandidateCount(d)
  return [
    { key: "changes", icon: ICON.changes, value: String(changes), label: "Changes", tone: changes > 0 ? "accent" : "muted" },
    { key: "upload", icon: ICON.upload, value: String(ahead), label: "To upload", tone: ahead > 0 ? "accent" : "muted" },
    { key: "updates", icon: ICON.updates, value: String(behind), label: "Updates", tone: behind > 0 ? "accent" : "muted" },
    { key: "newConfigs", icon: ICON.newConfigs, value: String(fresh), label: "New configs", tone: fresh > 0 ? "accent" : "muted" }
  ]
}

// --- overviewGroups: collapsible groups, hidden when empty -----------------

function changeChip(change, untracked) {
  if (untracked) return "?"
  var x = String((change && change.x) || "").replace(/\s/g, "")
  if (x) return x.charAt(0)
  var y = String((change && change.y) || "").replace(/\s/g, "")
  if (y) return y.charAt(0)
  return "?"
}

function changeItem(repoPath, change, untracked) {
  var c = change || {}
  return {
    type: "change",
    repo: repoPath,
    path: String(c.path || ""),
    package: c.package ? String(c.package) : "",
    chip: changeChip(c, untracked),
    untracked: !!untracked,
    stateColor: "accent"
  }
}

function overviewGroup(key, title, unit, items) {
  return {
    key: key,
    title: title,
    subtitle: pluralCount(items.length, "item") + " included",
    count: items.length,
    unit: pluralUnit(items.length, unit),
    items: items,
    expanded: false
  }
}

function overviewGroups(data) {
  var d = data || {}
  var repos = d.repos || []
  var groups = []

  var outgoing = []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var repoPath = String(repo.path || "")
    var tracked = repo.changes || []
    for (var t = 0; t < tracked.length; t++) outgoing.push(changeItem(repoPath, tracked[t], false))
    var untracked = repo.untracked || []
    for (var u = 0; u < untracked.length; u++) outgoing.push(changeItem(repoPath, untracked[u], true))
  }
  outgoing.sort(function(a, b) {
    var byPackage = compareStrings(a.package, b.package)
    return byPackage !== 0 ? byPackage : compareStrings(a.path, b.path)
  })
  if (outgoing.length > 0) {
    groups.push(overviewGroup("outgoing", "Outgoing \u2014 this machine", "file", outgoing))
  }

  var incoming = []
  for (var c = 0; c < repos.length; c++) {
    var commits = (repos[c] && repos[c].incoming_commits) || []
    for (var k = 0; k < commits.length; k++) {
      incoming.push({
        type: "incoming",
        repo: String(repos[c].path || ""),
        hash: String((commits[k] && commits[k].hash) || ""),
        subject: String((commits[k] && commits[k].subject) || "")
      })
    }
  }
  if (incoming.length > 0) {
    groups.push(overviewGroup("incoming", "Incoming \u2014 from GitHub", "commit", incoming))
  }

  var newConfigs = []
  var candidates = d.candidates || []
  for (var f = 0; f < candidates.length; f++) {
    if (candidates[f] && candidates[f].known === true) continue
    newConfigs.push({
      type: "candidate",
      path: String((candidates[f] && candidates[f].path) || ""),
      package: String((candidates[f] && candidates[f].suggested_package) || ""),
      group: String((candidates[f] && candidates[f].group) || "watched")
    })
  }
  if (newConfigs.length > 0) {
    groups.push(overviewGroup("newConfigs", "New config files", "file", newConfigs))
  }

  var fixing = []
  for (var r = 0; r < repos.length; r++) {
    var current = repos[r] || {}
    var packages = (current.packages || []).slice().sort(function(a, b) {
      return compareStrings(a && a.name, b && b.name)
    })
    for (var p = 0; p < packages.length; p++) {
      var pkg = packages[p] || {}
      var health = String(pkg.health || "ok")
      if (health === "ok") continue
      var pkgName = String(pkg.name || "")
      fixing.push({
        type: "health",
        repo: String(current.path || ""),
        package: pkgName,
        health: health,
        // Plain title/subtitle so the row never renders "undefined" (finding 79).
        title: pkgName,
        subtitle: repoDisplayName(String(current.path || "")) + " \u00b7 " + healthLabel(health),
        stateColor: healthColor(health)
      })
    }
  }
  if (fixing.length > 0) {
    groups.push(overviewGroup("fixing", "Needs fixing", "package", fixing))
  }

  return groups
}

// --- changesGroups: repo -> package groups with checkbox rows --------------

function changesGroups(data, options) {
  var d = data || {}
  var opts = options || {}
  var hiddenMap = {}
  var hiddenPaths = opts.hiddenPaths || []
  for (var h = 0; h < hiddenPaths.length; h++) hiddenMap[String(hiddenPaths[h])] = true
  var showExisting = opts.showExisting !== false
  var selected = opts.selectedRepos || null
  var selectedMap = {}
  if (selected && selected.length) {
    for (var s = 0; s < selected.length; s++) selectedMap[String(selected[s])] = true
  }

  var groups = []
  var repos = d.repos || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var repoPath = String(repo.path || "")
    if (selected && selected.length && !selectedMap[repoPath]) continue
    var entries = []
    var tracked = repo.changes || []
    for (var t = 0; t < tracked.length; t++) entries.push({ change: tracked[t], untracked: false })
    var untracked = repo.untracked || []
    for (var u = 0; u < untracked.length; u++) entries.push({ change: untracked[u], untracked: true })
    if (entries.length === 0) continue
    entries.sort(function(a, b) {
      var byPackage = compareStrings(a.change && a.change.package, b.change && b.change.package)
      if (byPackage !== 0) return byPackage
      return compareStrings(a.change && a.change.path, b.change && b.change.path)
    })
    var packages = []
    var current = null
    for (var e = 0; e < entries.length; e++) {
      var change = entries[e].change || {}
      var name = change.package ? String(change.package) : ""
      if (!current || current.package !== name) {
        current = { package: name, label: packageLabel(name), count: 0, items: [] }
        packages.push(current)
      }
      var path = String(change.path || "")
      var isHidden = hiddenMap[path] === true
      if (entries[e].untracked && change.known === true && !showExisting) isHidden = true
      current.items.push({
        path: path,
        package: name,
        chip: changeChip(change, entries[e].untracked),
        checked: true,
        hidden: isHidden
      })
      current.count += 1
    }
    var count = 0
    for (var c = 0; c < packages.length; c++) count += packages[c].count
    groups.push({
      key: "changes:" + repoPath,
      repo: repoPath,
      title: repoDisplayName(repoPath),
      subtitle: pluralCount(count, "change"),
      count: count,
      unit: pluralUnit(count, "file"),
      packages: packages
    })
  }
  return groups
}

// Changes tab view: changesGroups with hidden rows removed unless
// `showHidden`, plus a flat list of the visible rows for the keyboard cursor,
// selection and publish plan. Each row carries the same "change:<repo>:<path>"
// key the panel stores in its checked map. Pure; the panel only renders it.
function changesView(data, options) {
  var opts = options || {}
  var showHidden = opts.showHidden === true
  var groups = changesGroups(data, {
    hiddenPaths: opts.hiddenPaths || [],
    showExisting: opts.showExisting !== false,
    selectedRepos: opts.selectedRepos || []
  })
  var out = []
  var rows = []
  for (var g = 0; g < groups.length; g++) {
    var group = groups[g]
    var packages = []
    for (var p = 0; p < group.packages.length; p++) {
      var pkg = group.packages[p]
      var items = []
      for (var i = 0; i < pkg.items.length; i++) {
        var item = pkg.items[i]
        if (item.hidden && !showHidden) continue
        var row = {
          type: "change",
          repo: group.repo,
          package: pkg.package,
          label: pkg.label,
          path: item.path,
          chip: item.chip,
          hidden: item.hidden === true,
          checked: item.checked !== false,
          key: "change:" + group.repo + ":" + item.path
        }
        items.push(row)
        rows.push(row)
      }
      if (items.length > 0) {
        packages.push({ package: pkg.package, label: pkg.label, count: items.length, items: items })
      }
    }
    if (packages.length > 0) {
      var count = 0
      for (var c = 0; c < packages.length; c++) count += packages[c].count
      out.push({
        key: group.key,
        repo: group.repo,
        title: group.title,
        subtitle: pluralCount(count, "change"),
        count: count,
        unit: pluralUnit(count, "file"),
        packages: packages
      })
    }
  }
  return { groups: out, rows: rows }
}

// --- packageCards: one card per package per repo ---------------------------

function packageChangeFiles(repo, packageName) {
  var files = []
  var changes = (repo && repo.changes) || []
  for (var i = 0; i < changes.length; i++) {
    if (String((changes[i] && changes[i].package) || "") !== packageName) continue
    files.push({
      path: String((changes[i] && changes[i].path) || ""),
      state: String((changes[i] && changes[i].kind) || "modified")
    })
  }
  var untracked = (repo && repo.untracked) || []
  for (var u = 0; u < untracked.length; u++) {
    if (String((untracked[u] && untracked[u].package) || "") !== packageName) continue
    files.push({
      path: String((untracked[u] && untracked[u].path) || ""),
      state: "untracked"
    })
  }
  files.sort(function(a, b) { return compareStrings(a.path, b.path) })
  return files
}

// "~/.config/fish": from a stow-health target dir, else the common target
// directory of the package's known repo-relative files
// (``fish/.config/fish/conf.d/x`` and ``fish/.config/fish/y`` -> ``~/.config/fish``).
function packageTargetLabel(pkg, files) {
  var groups = [pkg.pending_links, pkg.conflicts, pkg.dangling]
  for (var g = 0; g < groups.length; g++) {
    var list = groups[g] || []
    for (var i = 0; i < list.length; i++) {
      var target = list[i] && list[i].target ? String(list[i].target) : ""
      if (!target) continue
      var slash = target.lastIndexOf("/")
      return slash > 0 ? target.slice(0, slash) : target
    }
  }
  var dirs = []
  for (var f = 0; f < files.length; f++) {
    var parts = String(files[f].path).split("/")
    if (parts.length > 1) parts.shift()
    var dir = parts.slice(0, -1).join("/")
    if (dir) dirs.push(dir)
  }
  if (dirs.length === 0) return ""
  var common = dirs[0].split("/")
  for (var d = 1; d < dirs.length; d++) {
    var other = dirs[d].split("/")
    var keep = 0
    while (keep < common.length && keep < other.length && common[keep] === other[keep]) keep++
    common = common.slice(0, keep)
  }
  var label = common.join("/")
  return label ? "~/" + label : "~/" + dirs[0]
}

function packageCards(data) {
  var d = data || {}
  var cards = []
  var repos = d.repos || []
  for (var i = 0; i < repos.length; i++) {
    var repo = repos[i] || {}
    var repoPath = String(repo.path || "")
    var packages = (repo.packages || []).slice().sort(function(a, b) {
      return compareStrings(a && a.name, b && b.name)
    })
    for (var p = 0; p < packages.length; p++) {
      var pkg = packages[p] || {}
      var name = String(pkg.name || "")
      var health = String(pkg.health || "ok")
      var files = packageChangeFiles(repo, name)
      var statusText
      if (health !== "ok") statusText = "Needs fixing"
      else if (files.length > 0) statusText = plural(files.length, " change", " changes")
      else statusText = "Stowed"
      var target = packageTargetLabel(pkg, files)
      cards.push({
        repo: repoPath,
        name: name,
        health: health,
        icon: packageIcon(name),
        title: name,
        description: (target ? target + " \u00b7 " : "\u00b7 ") + statusText,
        count: files.length,
        unit: pluralUnit(files.length, "file"),
        files: files,
        expanded: false
      })
    }
  }
  return cards
}

// --- repoInfoRows: the per-repo info table ---------------------------------

function repoInfoRows(repo, version, now) {
  var r = repo || {}
  var branch = String(r.branch || "")
  var head = String(r.head || "")
  var branchValue = branch
  if (head) branchValue = branch ? branch + " @ " + head : "@ " + head
  var remote = String(r.remote_url || "")
  var published = relativeTime(r.last_publish, now)
  return [
    { label: "Repo", value: String(r.path || "") },
    { label: "Remote", value: remote, copy: remote !== "" },
    { label: "Branch", value: branchValue },
    { label: "Sync", value: "\u2191" + num(r.ahead, 0) + " \u2193" + num(r.behind, 0) },
    { label: "Last commit", value: relativeTime(r.head_time, now) },
    { label: "Last publish", value: published === "" ? "never" : published },
    { label: "Packages", value: pluralCount(num(r.stowed_packages, 0), "package") },
    { label: "Plugin", value: "stow-sync " + String(version || "") }
  ]
}

// --------------------------------------------------------------------------
// Unit 6: own visual identity. Pure view models for the sync bridge, the
// borderless repo lanes, the package chip grid and the count tween.
// --------------------------------------------------------------------------

// A repo needs the urgent stripe when a git operation is stuck, the repo is
// gone, or a package cannot be stowed at all; pending work stays accent.
function repoAttention(repo) {
  var r = repo || {}
  if (r.exists === false) return true
  var state = String(r.state || "clean")
  if (state === "conflict" || state === "diverged" || state === "operation" || state === "missing" || state === "secret-blocked") return true
  var packages = r.packages || []
  for (var i = 0; i < packages.length; i++) {
    if (String((packages[i] && packages[i].health) || "ok") === "conflicts") return true
  }
  return false
}

// The hero diagram's shape: two node labels, the up/down flows, which chips
// are present, the line tone and the "This PC" change-count badge.
function bridgeState(data, opts) {
  var d = data || {}
  var o = opts || {}
  var up = flowTotals(d, "ahead").count
  var down = flowTotals(d, "behind").count
  var changes = changeTotals(d).count
  return {
    leftLabel: "This PC",
    rightLabel: "GitHub",
    up: up,
    down: down,
    hasUp: up > 0,
    hasDown: down > 0,
    upText: up > 0 ? "\u2191" + up : "",
    downText: down > 0 ? "\u2193" + down : "",
    // A fresh machine (opt-in on, every repo missing) is neutral, not urgent.
    lineTone: o.notSetUp === true ? "neutral" : (attentionFor(d) ? "urgent" : "accent"),
    badge: changes,
    badgeText: changes > 99 ? "99+" : (changes > 0 ? String(changes) : ""),
    hasChanges: changes > 0
  }
}

// Collapsed repo lane: bold name, branch chip, short hash, relative time and a
// compact "N pkgs" count (the panel elides it clear of the scrollbar). The
// stripe is accent at half alpha when clean, full accent while work is
// pending, and urgent for a state that needs attention.
function repoLaneSummary(repo, now, opts) {
  var r = repo || {}
  var o = opts || {}
  var branch = String(r.branch || "")
  var head = String(r.head || "")
  var count = num(r.stowed_packages, 0)
  var attention = repoAttention(r)
  var pending = attention || repoChangeCount(r) > 0 ||
    num(r.ahead, 0) > 0 || num(r.behind, 0) > 0 || String(r.state || "clean") !== "clean" ||
    unhealthyCount(r) > 0
  return {
    name: repoDisplayName(r.path),
    branch: branch,
    branchChip: branch,
    shortHash: head.length > 7 ? head.slice(0, 7) : head,
    timeText: relativeTime(r.head_time, now),
    count: count,
    countText: pluralCount(count, "pkg", "pkgs"),
    // A fresh machine draws a neutral stripe, never the urgent one (10b.2).
    stripeTone: o.neutral ? "neutral" : (attention ? "urgent" : "accent"),
    stripeAlpha: o.neutral ? 0.25 : (pending ? 1 : 0.5),
    state: String(r.state || "clean")
  }
}

// Chip grid tone for one package card: an unhealthy package gets the urgent
// outline, a package with changes the accent outline, everything else the
// plain foreground fill.
function packageChipState(card) {  var c = card || {}
  var health = String(c.health || "ok")
  var count = num(c.count, (c.files || []).length)
  if (health !== "ok") return { tone: "fixing", fillAlpha: 0.06, outline: true, outlineTone: "urgent" }
  if (count > 0) return { tone: "changed", fillAlpha: 0.06, outline: true, outlineTone: "accent" }
  return { tone: "ok", fillAlpha: 0.06, outline: false, outlineTone: "" }
}

// Integer ease-out cubic interpolation. t is clamped to [0, 1]; no other
// animation in the panel is allowed, so this mirrors the only tween.
function tweenValue(from, to, t) {
  var clamped = Number(t)
  if (!isFinite(clamped)) clamped = 0
  if (clamped < 0) clamped = 0
  if (clamped > 1) clamped = 1
  var eased = 1 - Math.pow(1 - clamped, 3)
  return Math.round(from + (to - from) * eased)
}

// --- "Set up this machine" view model (Unit 8b) ---------------------------
// Pure helpers behind SetupWizard.qml. The backend contract lives in
// scripts/stow_sync.py (README section 8a); nothing here mutates anything.

// The whole feature is opt-in: it exists only when the machineSetup setting is
// on (README section 8.1). `status` is reserved for future gating.
function setupVisible(settings, status) {
  var s = settings || {}
  return s.machineSetup === true || s.machineSetup === "true"
}

// True when any configured repo is absent on disk; drives the Overview banner.
function anyRepoMissing(status) {
  var repos = (status && status.repos) || []
  for (var i = 0; i < repos.length; i++) if (repos[i].exists === false) return true
  return false
}

// True when the machine looks fresh: the config lists repos but none exists on
// disk (README 10b.2). An empty repo list is not a fresh machine.
function allReposMissing(status) {
  var repos = (status && status.repos) || []
  if (repos.length === 0) return false
  for (var i = 0; i < repos.length; i++) if (repos[i].exists !== false) return false
  return true
}

// Prefill the Connect URL from the dotfiles repo's remote when it is present.
function setupPrefillUrl(status) {
  var repos = (status && status.repos) || []
  for (var i = 0; i < repos.length; i++) {
    var path = String(repos[i].path || "")
    if (/\.dotfiles$/.test(path) && repos[i].remote_url) return String(repos[i].remote_url)
  }
  return ""
}

// A URL the Connect step accepts: a GitHub URL or anything ending in ".git"
// (README 10b.4/finding 11). Empty and free text are rejected.
function setupValidUrl(url) {
  var s = String(url === undefined || url === null ? "" : url).trim()
  if (s === "") return false
  if (/^https?:\/\/github\.com\/[^/\s]+\/[^/\s]+/i.test(s)) return true
  if (/^git@github\.com:[^/\s]+\/.+/i.test(s)) return true
  return /\.git$/i.test(s)
}

// Connect checklist rows: waiting / cloning / cloned / ready / error per repo
// (README 10b.4/finding 13). The wizard feeds entries in clone order.
function setupConnectRows(entries) {
  var list = entries || []
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var e = list[i] || {}
    var state = String(e.state || "waiting")
    var detail = "Waiting"
    var status = "waiting"
    var tone = "muted"
    if (state === "cloned") { detail = "Cloned"; status = "done"; tone = "accent" }
    else if (state === "ready") { detail = "Ready"; status = "done"; tone = "accent" }
    else if (state === "cloning") { detail = "Cloning\u2026"; status = "running"; tone = "muted" }
    else if (state === "error") { detail = String(e.error || "Clone failed"); status = "failed"; tone = "urgent" }
    rows.push({ label: String(e.path || ""), detail: detail, status: status, tone: tone, authError: e.authError === true })
  }
  return rows
}

// The GitHub login line for the Check step (README 11c.3): the gh-auth check's
// detail ("signed in as X" / "not signed in"), or empty when gh is absent.
function setupLoginDetail(prereqs) {
  var checks = (prereqs && prereqs.checks) || []
  for (var i = 0; i < checks.length; i++) {
    if (String(checks[i] && checks[i].id) === "gh-auth") return String(checks[i].detail || "")
  }
  return ""
}

// The auth-failure fix shown in the Connect step (README 11c.3): non-null when
// a connect/clone entry failed because GitHub login is missing, or when the
// whole connect command failed on auth (`commandFailed`).
function setupAuthFix(entries, commandFailed) {
  if (commandFailed === true) {
    return { command: "gh auth login, then gh auth setup-git", detail: "" }
  }
  var list = entries || []
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].authError === true) {
      return {
        command: "gh auth login, then gh auth setup-git",
        detail: String(list[i].error || "GitHub login is needed to download this repo.")
      }
    }
  }
  return null
}

// Candidate picker rows (README 11c.2). `data` is the setup-candidates result:
// definitive repos first (preselected in the view), then likely ones; every
// other repo goes behind "Show all repos".
function setupCandidateRows(data) {
  var d = data || {}
  function rowsFor(list, tier) {
    var rows = []
    var items = list || []
    for (var i = 0; i < items.length; i++) {
      var r = items[i] || {}
      var detail = String(r.detail || "")
      if (r.private === true) detail = detail === "" ? "private" : detail + " \u00b7 private"
      rows.push({
        key: String(r.url || ""),
        label: String(r.name || ""),
        detail: detail,
        value: String(r.url || ""),
        likely: tier !== "other",
        tier: tier,
        hint: r.hint === true,
        private: r.private === true,
        // Radio-card fields (README 12c finding 51).
        sentence: tier === "definitive" ? "Has a Stow Sync recipe"
          : (tier === "likely" ? "Looks like a dotfiles repo" : ""),
        badges: (r.private === true ? ["private"] : []).concat(tier === "definitive" ? ["recipe"] : [])
      })
    }
    return rows
  }
  return {
    definitive: rowsFor(d.definitive, "definitive"),
    likely: rowsFor(d.likely, "likely"),
    others: rowsFor(d.others, "other")
  }
}

// The URL to prefill from the first definitive repo, or "" (README 11c.2).
function setupCandidateFirstUrl(data) {
  var definitive = (data && data.definitive) || []
  if (definitive.length === 0) return ""
  return String((definitive[0] && definitive[0].url) || "")
}

// Case-insensitive filter for the "Show all repos" list.
function setupFilterRows(rows, query) {
  var text = String(query === undefined || query === null ? "" : query).trim().toLowerCase()
  var list = rows || []
  if (text === "") return list.slice()
  var out = []
  for (var i = 0; i < list.length; i++) {
    var label = String((list[i] && list[i].label) || "").toLowerCase()
    var value = String((list[i] && list[i].value) || "").toLowerCase()
    if (label.indexOf(text) !== -1 || value.indexOf(text) !== -1) out.push(list[i])
  }
  return out
}

// The post-step ids the wizard will run: an explicit toggle wins, otherwise the
// recipe default (README 10b.5). Used by the Review step and setup-apply.
function setupSelectedPostIds(plan, checked) {
  var state = checked || {}
  var post = (plan && plan.post) || []
  var ids = []
  for (var i = 0; i < post.length; i++) {
    var id = String(post[i].id || "")
    var on = state[id] !== undefined ? state[id] === true : post[i].default === true
    if (on) ids.push(id)
  }
  return ids
}

// How many post steps are on (README Unit 15c/finding 89); the Review wording
// and the primary button follow this count.
function setupSelectedPostCount(plan, checked) {
  return setupSelectedPostIds(plan, checked).length
}

// Prerequisite rows for the Check step (README 10b.3). Labels are plain words;
// the fix command stays in `fix` for the copy button.
function setupPrereqRows(prereqs) {
  if (!prereqs || !prereqs.checks) return []
  var labels = {
    "stow": "GNU Stow",
    "git": "Git",
    "pacman-db": "Package database",
    "gh": "GitHub CLI",
    "gh-auth": "GitHub login"
  }
  var rows = []
  var checks = prereqs.checks || []
  for (var i = 0; i < checks.length; i++) {
    var c = checks[i] || {}
    var id = String(c.id || "")
    rows.push({
      id: id,
      label: labels[id] !== undefined ? labels[id] : id,
      ok: c.ok === true,
      detail: String(c.detail || ""),
      fix: String(c.fix || ""),
      tone: c.ok === true ? "accent" : "urgent"
    })
  }
  return rows
}

// Continue is enabled only when the backend says every blocking check passed.
function setupPrereqReady(prereqs) {
  if (!prereqs || prereqs.ok === false) return false
  return prereqs.ok_to_connect === true
}

// Review step groups, in reading order, empty groups omitted. Each group is a
// collapsible summary row; Missing tools and Still to do start expanded
// (README 10b.5). Post steps carry `available`/`detail` so a step whose tool is
// missing renders disabled with "needs X".
function setupPlanGroups(plan) {
  var p = plan || {}
  var groups = []
  var clone = (p.clone || []).slice()
  if (clone.length > 0) {
    var downloadItems = []
    for (var c = 0; c < clone.length; c++) {
      downloadItems.push({ label: String(clone[c].path || ""), detail: clone[c].private ? "private" : "", tone: "muted" })
    }
    groups.push({ key: "download", title: "Will download", subtitle: "Repositories cloned from GitHub", tone: "accent", count: clone.length, unit: pluralUnit(clone.length, "repository", "repositories"), expandByDefault: false, items: downloadItems })
  }
  var links = p.link || []
  var linkItems = []
  var skippedItems = []
  for (var i = 0; i < links.length; i++) {
    var l = links[i]
    var status = String(l.status || "")
    if (status === "already") continue
    if (status === "blocked") {
      var blockedConflict = (l.conflicts && l.conflicts[0]) || {}
      skippedItems.push({ label: String(l.repo || "") + " \u00b7 " + String(l.package || ""), detail: String(blockedConflict.reason || blockedConflict.message || "blocked"), tone: "urgent" })
      continue
    }
    var files = (l.links && l.links.length) || num(l.files_to_backup, 0)
    linkItems.push({ label: String(l.repo || "") + " \u00b7 " + String(l.package || ""), detail: pluralCount(files, "file"), tone: "muted" })
  }
  if (linkItems.length > 0) groups.push({ key: "link", title: "Will link", subtitle: "Stow packages", tone: "accent", count: linkItems.length, unit: pluralUnit(linkItems.length, "package"), expandByDefault: false, items: linkItems })
  // Backup files grouped by package, with plain wording (README 12c finding 54)
  // and per-kind counts plus bare file names (finding 69).
  var backupGroups = setupBackupByPackage(p)
  if (backupGroups.length > 0) {
    var backupTotal = 0
    var backupItems = []
    for (var bg = 0; bg < backupGroups.length; bg++) {
      backupTotal += backupGroups[bg].count
      var bGroup = backupGroups[bg]
      var clauses = []
      if (bGroup.savedToBackup > 0) clauses.push(bGroup.savedToBackup + " saved to backup")
      if (bGroup.identical > 0) clauses.push(bGroup.identical + " same as yours")
      var bDetail = pluralCount(bGroup.count, "file") + (clauses.length > 0 ? " \u00b7 " + clauses.join(", ") : "")
      var names = []
      for (var sf = 0; sf < bGroup.files.length; sf++) names.push(bGroup.files[sf].name)
      backupItems.push({ label: bGroup.package, detail: bDetail, tone: "muted", sub: names })
    }
    groups.push({ key: "backup", title: "Will move to backup", subtitle: "Existing files kept in the backup folder", tone: "accent", count: backupTotal, unit: pluralUnit(backupTotal, "file"), expandByDefault: false, items: backupItems })
  }
  if (skippedItems.length > 0) groups.push({ key: "skipped", title: "Skipped", subtitle: "Nothing is forced", tone: "urgent", count: skippedItems.length, unit: pluralUnit(skippedItems.length, "package"), expandByDefault: false, items: skippedItems })
  var missing = []
  var requires = p.requires || []
  for (var r = 0; r < requires.length; r++) {
    if (requires[r].found === false) missing.push({ label: String(requires[r].name || ""), detail: "not installed", tone: "urgent" })
  }
  if (missing.length > 0) groups.push({ key: "missing", title: "Missing tools", subtitle: "Reported, never installed", tone: "urgent", count: missing.length, unit: pluralUnit(missing.length, "tool"), expandByDefault: true, items: missing })
  var posts = p.post || []
  if (posts.length > 0) {
    var afterItems = []
    for (var q = 0; q < posts.length; q++) {
      var post = posts[q] || {}
      var available = post.available !== false
      var missingTools = post.missing || []
      afterItems.push({
        id: String(post.id || ""),
        label: String(post.label || post.id || ""),
        detail: available ? "" : String(post.reason || ("needs " + missingTools.join(", "))),
        tone: available ? "muted" : "urgent",
        default: post.default === true,
        available: available
      })
    }
    groups.push({ key: "after", title: "Afterwards", subtitle: "Optional steps", tone: "muted", count: afterItems.length, unit: pluralUnit(afterItems.length, "step"), expandByDefault: false, items: afterItems })
  }
  var notes = p.notes || []
  if (notes.length > 0) {
    var noteItems = []
    for (var n = 0; n < notes.length; n++) noteItems.push({ label: String(notes[n]), detail: "", tone: "muted" })
    groups.push({ key: "notes", title: "Still to do by hand", subtitle: "", tone: "muted", count: noteItems.length, unit: pluralUnit(noteItems.length, "note"), expandByDefault: true, items: noteItems })
  }
  return groups
}

// One sentence naming exactly what Set up will do (README 8b Review).
function setupPrimaryLabel(plan, steps) {
  var p = plan || {}
  var stepCount = num(steps, 0)
  var clone = (p.clone || []).length
  var links = p.link || []
  var toLink = 0
  var files = 0
  var blocked = 0
  for (var i = 0; i < links.length; i++) {
    var status = String(links[i].status || "")
    if (status === "blocked") { blocked++; continue }
    if (status === "already") continue
    toLink++
    files += num(links[i].files_to_backup, 0)
  }
  var parts = []
  if (clone > 0) parts.push("download " + pluralCount(clone, "repository", "repositories"))
  if (toLink > 0) parts.push("link " + pluralCount(toLink, "package"))
  if (files > 0) parts.push("back up " + pluralCount(files, "file"))
  if (parts.length === 0 && blocked > 0) parts.push("review " + pluralCount(blocked, "blocked package"))
  // A steps-only run (nothing to link, at least one post step on) is still work
  // (README Unit 15c/finding 89).
  if (parts.length === 0 && stepCount > 0) return "Run " + pluralCount(stepCount, "step")
  if (parts.length === 0) return "Nothing to set up"
  return "Set up \u00b7 " + parts.join(", ")
}

// True when Set up would change something: a clone, a non-already package, or
// at least one step on. Drives the Review primary button's enabled state.
function setupHasWork(plan, steps) {
  var p = plan || {}
  if ((p.clone || []).length > 0) return true
  var links = p.link || []
  for (var i = 0; i < links.length; i++) {
    if (String(links[i].status || "") !== "already") return true
  }
  return num(steps, 0) > 0
}

// Apply step progress rows derived from the rich apply response (README 10b.6).
function setupStepState(results) {
  if (!results) return []
  var rows = []
  var packages = results.packages || []
  if (packages.length > 0) {
    for (var i = 0; i < packages.length; i++) {
      var p = packages[i] || {}
      var st = String(p.state || "")
      rows.push({ label: String(p.repo || "") + " \u00b7 " + String(p.package || ""), status: (st === "failed" || st === "blocked") ? "failed" : "done", detail: "" })
    }
  } else {
    var applied = results.applied || []
    for (var a = 0; a < applied.length; a++) rows.push({ label: String(applied[a].repo || "") + " \u00b7 " + String(applied[a].package || ""), status: "done", detail: "" })
    var failed = results.failed || []
    for (var f = 0; f < failed.length; f++) rows.push({ label: String(failed[f].repo || "") + " \u00b7 " + String(failed[f].package || ""), status: "failed", detail: String(failed[f].error || "failed") })
    var skipped = results.skipped || []
    for (var s = 0; s < skipped.length; s++) {
      var sk = skipped[s]
      if (sk.status === "already") rows.push({ label: String(sk.repo || "") + " \u00b7 " + String(sk.package || ""), status: "done", detail: "already linked" })
      else if (sk.status === "repo-missing") rows.push({ label: String(sk.path || ""), status: "failed", detail: String(sk.reason || "repo missing") })
    }
  }
  var services = results.services || []
  for (var v = 0; v < services.length; v++) {
    var svc = services[v] || {}
    var svcOk = svc.state !== undefined ? String(svc.state) === "enabled" : svc.ok === true
    rows.push({ label: String(svc.unit || ""), status: svcOk ? "done" : "failed", detail: String(svc.error || "") })
  }
  var posts = results.post || []
  for (var q = 0; q < posts.length; q++) {
    var post = posts[q] || {}
    var postState = String(post.state || (post.ok === true ? "ran" : "failed"))
    var status = postState === "ran" ? "done" : (postState === "skipped" ? "skipped" : "failed")
    var detail = postState === "skipped" ? String(post.reason || "skipped") : String(post.last_line || post.error || "")
    rows.push({ label: String(post.id || ""), status: status, detail: detail })
  }
  return rows
}

// Absolute path of the live progress file the wizard polls (README 12a/finding
// 52): the panel used to watch the state DIRECTORY, so the FileView never loaded.
function setupProgressPath(stateDir) {
  var dir = String(stateDir === undefined || stateDir === null ? "" : stateDir)
  if (dir === "") return ""
  if (dir.charAt(dir.length - 1) === "/") dir = dir.slice(0, -1)
  return dir + "/setup-progress.json"
}

// Hard byte cap for the polled progress file (README 11 hardening audit): the
// QML FileView buffers whatever the file holds, so refuse anything larger
// before JSON.parse instead of letting a planted huge file reach the model.
var SETUP_PROGRESS_MAX_BYTES = 262144

function parseSetupProgress(text, maxBytes) {
  var cap = num(maxBytes, SETUP_PROGRESS_MAX_BYTES)
  var raw = String(text === undefined || text === null ? "" : text).trim()
  if (raw === "") return null
  if (raw.length > cap) return null
  try { return JSON.parse(raw) } catch (error) { return null }
}

// True when the newest setup backup is marked undone (README 12a/finding 61):
// the machine is back to the not-set-up state. Backups are oldest-first.
function setupUndoneFromBackups(backups) {
  var list = backups || []
  if (list.length === 0) return false
  return list[list.length - 1].undone === true
}

// Backups that have not been undone yet (README Unit 15/finding 83): the setup
// Undo entry point is only shown, and only runs directly, while one exists.
function setupActiveBackups(backups) {
  var list = backups || []
  var out = []
  for (var i = 0; i < list.length; i++) {
    if ((list[i] || {}).undone !== true) out.push(list[i])
  }
  return out
}

// "2026-10-12T03:29:06+00:00" or "20261012T032906Z" -> "12 Oct" (README 15d).
function formatSetupDate(stamp) {
  var s = String(stamp === undefined || stamp === null ? "" : stamp)
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) m = s.match(/^(\d{4})(\d{2})(\d{2})T/)
  if (!m) return s
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  var month = months[parseInt(m[2], 10) - 1]
  return month ? (parseInt(m[3], 10) + " " + month) : s
}

// Quiet Overview line for the latest un-undone setup (README Unit 15d):
// "Set up 12 Oct · 17 packages linked" with the Undo setup entry point. Hidden
// while the machine is not set up or while busy; null when nothing can be undone.
function setupLine(backups, opts) {
  var o = opts || {}
  if (o.notSetUp === true || o.busy === true) return null
  var active = setupActiveBackups(backups)
  if (active.length === 0) return null
  var latest = active[active.length - 1] || {}
  var packages = num((latest.counts || {}).packages, 0)
  var date = formatSetupDate(latest.label || latest.created || "")
  return {
    id: String(latest.id || ""),
    date: date,
    summary: pluralCount(packages, "package") + " linked",
    label: "Set up " + date + " \u00b7 " + pluralCount(packages, "package") + " linked",
    multi: active.length > 1
  }
}

// Plain one-line undo summary for the backups list (finding 80), mirroring the
// Report card: "Setup undone · 17 packages unlinked · 16 files restored · 1
// service disabled". Empty when the undo failed or produced no result.
function setupUndoSummary(results) {
  var r = results || {}
  if (results === null || results === undefined || r.ok === false) return ""
  var parts = ["Setup undone"]
  var pkgs = (r.unstowed || []).length
  if (pkgs > 0) parts.push(pluralCount(pkgs, "package") + " unlinked")
  var files = (r.restored || []).length
  if (files > 0) parts.push(pluralCount(files, "file") + " restored")
  var services = (r.services_disabled || []).length
  if (services > 0) parts.push(pluralCount(services, "service") + " disabled")
  return parts.join(" \u00b7 ")
}

// True when any configured repo already has a healthy stowed package.
function machineHasLinkedPackages(status) {
  var repos = (status && status.repos) || []
  for (var i = 0; i < repos.length; i++) {
    if (num((repos[i] || {}).stowed_packages, 0) > 0) return true
  }
  return false
}

// "Not set up" for the Overview (README 12a/finding 61 + Unit 15/finding 81):
// every repo missing, or no package linked and no active (un-undone) setup.
// A stray regular file that survives an Undo must not re-enable management —
// the decision never depends on a clean stow dry run.
function setupMachineNotSetUp(status, opts) {
  var o = opts || {}
  if (o.setupOn !== true) return false
  if (allReposMissing(status)) return true
  if (machineHasLinkedPackages(status)) return false
  var backups = o.backups || []
  for (var i = 0; i < backups.length; i++) {
    if ((backups[i] || {}).undone !== true) return false
  }
  return true
}

// --- Unit 12c: approved redesign helpers ----------------------------------

// Stepper state for step `index` when the wizard is on `current` (README 12c).
function setupWizardStepState(index, current) {
  var i = num(index, 0)
  var c = num(current, 0)
  if (i < c) return "done"
  if (i === c) return "current"
  return "next"
}

// A real byte estimate as a short label (README 12c answer 2): "" when there is
// no number, never an invented one. Decimal units (KB/MB/GB = 1000) so every
// size in the wizard uses one system (finding 66).
function setupSizeLabel(bytes) {
  var n = num(bytes, 0)
  if (!(n > 0)) return ""
  var gb = n / 1e9
  if (gb >= 1) return "~" + (Math.round(gb * 10) / 10) + " GB"
  var mb = n / 1e6
  if (mb >= 1) return Math.round(mb) + " MB"
  return Math.max(1, Math.round(n / 1000)) + " KB"
}

// Parse a git progress size into bytes (finding 66): "410.20 MiB" and "944.81
// KiB" are binary (*iB), plain "KB"/"MB"/"GB" are decimal, ""/garbage is 0.
function parseSizeBytes(text) {
  var s = String(text === undefined || text === null ? "" : text).trim()
  if (s === "") return 0
  var m = s.match(/^([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B)$/i)
  if (!m) return 0
  var value = parseFloat(m[1])
  if (!isFinite(value)) return 0
  var factor = 1
  switch (m[2].toLowerCase()) {
    case "kib": factor = 1024; break
    case "mib": factor = 1024 * 1024; break
    case "gib": factor = 1024 * 1024 * 1024; break
    case "tib": factor = 1024 * 1024 * 1024 * 1024; break
    case "kb": factor = 1000; break
    case "mb": factor = 1e6; break
    case "gb": factor = 1e9; break
    case "tb": factor = 1e12; break
  }
  return Math.round(value * factor)
}

// One decimal size label for the download cards (finding 66): "" when there is
// nothing to show, else GB with one decimal, or a whole number of MB/KB.
function formatBytesDecimal(bytes) {
  var n = num(bytes, 0)
  if (!(n > 0)) return ""
  var gb = n / 1e9
  if (gb >= 1) return (Math.round(gb * 10) / 10) + " GB"
  var mb = n / 1e6
  if (mb >= 1) return Math.round(mb) + " MB"
  return Math.max(1, Math.round(n / 1000)) + " KB"
}

// Live download speed and ETA from two consecutive samples (finding 67).
// Returns ok:false and empty text for anything unusable, so the UI hides the
// line instead of showing a made-up number.
function downloadRate(currentBytes, previousBytes, elapsedSeconds, totalBytes) {
  var cur = Number(currentBytes)
  var prev = Number(previousBytes)
  var elapsed = Number(elapsedSeconds)
  var total = Number(totalBytes)
  if (!(isFinite(cur) && isFinite(prev) && isFinite(elapsed) && isFinite(total))) return { ok: false, speedText: "", etaText: "" }
  if (!(elapsed > 0) || !(prev >= 0) || !(cur > prev)) return { ok: false, speedText: "", etaText: "" }
  var speedBytes = (cur - prev) / elapsed
  var speedText = formatBytesDecimal(speedBytes) + "/s"
  var etaText = ""
  if (total > cur && speedBytes > 0) {
    var etaSeconds = (total - cur) / speedBytes
    if (isFinite(etaSeconds)) etaText = etaSeconds >= 60 ? "about " + Math.round(etaSeconds / 60) + " min left" : "about " + Math.round(etaSeconds) + " s left"
  }
  return { ok: true, speedText: speedText, etaText: etaText }
}

// Download-view cards (README 12c answer 2 / finding 53): one card per repo,
// with the live percent from the current clone when it is this repo.
function setupDownloadCards(entries, clone, rate) {
  var list = entries || []
  var c = clone || null
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var e = list[i] || {}
    var state = String(e.state || "waiting")
    var row = {
      label: String(e.path || ""),
      state: state,
      percent: -1,
      size: String(e.sizeLabel || ""),
      speed: "",
      detail: "",
      tone: "muted"
    }
    if (state === "cloned" || state === "ready") { row.detail = "done"; row.tone = "accent" }
    else if (state === "error") { row.detail = String(e.error || "failed"); row.tone = "urgent" }
    else if (state === "cloning") {
      if (c && String(c.item) === String(e.path)) {
        row.percent = num(c.percent, -1)
        row.detail = String(c.label || "Downloading\u2026")
        // Prefer the parsed byte size in the one decimal system (finding 66).
        if (num(c.bytes, 0) > 0) row.size = formatBytesDecimal(c.bytes)
        else if (String(c.size || "") !== "") row.size = String(c.size)
        // Speed + ETA on the active card, empty when unknown (finding 67).
        if (rate && rate.ok === true) row.speed = rate.etaText !== "" ? (rate.speedText + " \u00b7 " + rate.etaText) : String(rate.speedText || "")
      } else {
        row.detail = "Downloading\u2026"
      }
    } else {
      row.detail = "Waiting"
    }
    rows.push(row)
  }
  return rows
}

// The overall download line (README 12c finding 53).
function setupDownloadSummary(entries) {
  var list = entries || []
  if (list.length === 0) return ""
  var done = 0
  for (var i = 0; i < list.length; i++) {
    var s = String(list[i].state || "")
    if (s === "cloned" || s === "ready") done++
  }
  if (done === list.length) return list.length === 1 ? "Repository downloaded" : "All " + pluralCount(list.length, "repo") + " downloaded"
  return "Downloading " + pluralCount(list.length, "repo") + " \u00b7 " + done + " of " + list.length + " done"
}

// One plain sentence for the whole Review step (README 12c finding 54).
function setupReviewSummary(plan, steps) {
  var p = plan || {}
  var stepCount = num(steps, 0)
  var links = p.link || []
  var toLink = 0
  var files = 0
  for (var i = 0; i < links.length; i++) {
    var status = String(links[i].status || "")
    if (status === "already" || status === "blocked") continue
    toLink++
    files += num(links[i].files_to_backup, 0)
  }
  var clone = (p.clone || []).length
  var parts = []
  if (clone > 0) parts.push("download " + pluralCount(clone, "repository", "repositories"))
  if (toLink > 0) parts.push("link " + pluralCount(toLink, "package"))
  if (files > 0) parts.push("keep a backup of " + pluralCount(files, "file"))
  // Nothing to link but steps on: the run is still work (finding 89).
  if (parts.length === 0 && stepCount > 0) return "Nothing to link. " + pluralCount(stepCount, "step") + " will run."
  if (parts.length === 0) return "Nothing to set up."
  return "Stow Sync will " + parts.join(", ") + ". Nothing is deleted, and you can undo it."
}

// Plain wording for a stow conflict kind (README 12c finding 54).
function setupConflictWording(kind) {
  if (kind === "identical") return "same as yours \u2192 replaced"
  if (kind === "different") return "Omarchy's version \u2192 saved to backup, yours is used"
  return String(kind || "")
}

// Backup files grouped by package (README 12c finding 54). Blocked conflicts
// are reported elsewhere, so they are skipped here.
function setupBackupByPackage(plan) {
  var links = (plan && plan.link) || []
  var groups = []
  for (var i = 0; i < links.length; i++) {
    var conflicts = links[i].conflicts || []
    var files = []
    var savedToBackup = 0
    var identical = 0
    for (var k = 0; k < conflicts.length; k++) {
      if (conflicts[k].kind === "blocked") continue
      var target = String(conflicts[k].target || "")
      var kind = String(conflicts[k].kind || "")
      if (kind === "different") savedToBackup++
      else if (kind === "identical") identical++
      files.push({
        target: target,
        kind: kind,
        name: target.slice(target.lastIndexOf("/") + 1),
        wording: setupConflictWording(conflicts[k].kind)
      })
    }
    if (files.length > 0) {
      groups.push({
        repo: String(links[i].repo || ""),
        package: String(links[i].package || ""),
        count: files.length,
        unit: pluralUnit(files.length, "file"),
        savedToBackup: savedToBackup,
        identical: identical,
        files: files
      })
    }
  }
  return groups
}

// Explicit On/Off wording for a step toggle (README 12c finding 54).
function setupToggleLabel(checked) {
  return checked === true ? "On" : "Off"
}

// One skip line that also tells how to run the step later (finding 89).
function setupSkipLine(reason) {
  return "skipped: " + String(reason || "unavailable") + " \u2014 then run Set up again"
}

// One Report step row (README 11d.3/12a findings 59): every recipe step is
// listed, its state is `ran` / `skipped: <reason>` / `not selected`, and `sub`
// carries the cleaned last output line to render under the step name. A step the
// plan marked unavailable is `skipped: needs X` (the user never deselected it).
function setupReportSteps(plan, results) {
  var posts = results || []
  var byId = {}
  for (var i = 0; i < posts.length; i++) byId[String(posts[i].id || "")] = posts[i]
  var ordered = []
  var seen = {}
  var planPosts = (plan && plan.post) || []
  for (var q = 0; q < planPosts.length; q++) {
    var pid = String(planPosts[q].id || "")
    seen[pid] = true
    ordered.push({ id: pid, label: String(planPosts[q].label || pid), planEntry: planPosts[q] })
  }
  for (var j = 0; j < posts.length; j++) {
    var rid = String(posts[j].id || "")
    if (!seen[rid]) { seen[rid] = true; ordered.push({ id: rid, label: rid }) }
  }
  var items = []
  for (var k = 0; k < ordered.length; k++) {
    var res = byId[ordered[k].id]
    if (res === undefined) {
      var pe = ordered[k].planEntry || {}
      if (pe.available === false) {
        var missing = pe.missing || []
        var reason = String(pe.reason || ("needs " + missing.join(", ")) || "unavailable")
        items.push({ label: ordered[k].label, state: setupSkipLine(reason), sub: "", tone: "muted" })
      } else {
        items.push({ label: ordered[k].label, state: "not selected", sub: "", tone: "muted" })
      }
      continue
    }
    var st = String(res.state || (res.ok === true ? "ran" : "failed"))
    if (st === "ran") items.push({ label: ordered[k].label, state: "ran", sub: String(res.last_line || ""), tone: "muted" })
    else if (st === "skipped") items.push({ label: ordered[k].label, state: setupSkipLine(res.reason), sub: "", tone: "muted" })
    else items.push({ label: ordered[k].label, state: "failed", sub: String(res.last_line || res.error || ""), tone: "urgent" })
  }
  return items
}

// One collapsible Report group (README 11d.4): title, tone, count, unit and
// whether it starts expanded.
function setupReportSection(key, title, tone, unit, items, expandByDefault, undone) {
  return {
    key: key,
    title: title,
    tone: tone,
    count: items.length,
    unit: pluralUnit(items.length, unit),
    expandByDefault: expandByDefault === true,
    undone: undone === true,
    items: items
  }
}

// Report step summary: grouped sections with counts, the backup folder and one
// line per problem (README 10b.6/11d.4). Packages and Moved collapse by default;
// Services, Steps, Failed and notes start expanded. Notes are kept separate so
// they can be shown again under "Still to do by hand".
function setupReport(results, plan, undone) {
  var r = results || {}
  var undoneFlag = undone === true
  var packages = r.packages || r.applied || []
  var appliedPackages = []
  for (var i = 0; i < packages.length; i++) {
    if (String((packages[i] || {}).state || "applied") === "applied") appliedPackages.push(packages[i])
  }
  var moved = r.moved || []
  var services = r.services || []
  var posts = r.post || []
  var failed = r.failed || []
  var notes = r.notes || []
  var sections = []
  if (appliedPackages.length > 0) {
    var pkgItems = []
    for (var p = 0; p < appliedPackages.length; p++) pkgItems.push({ label: String(appliedPackages[p].repo || "") + " \u00b7 " + String(appliedPackages[p].package || ""), detail: "", tone: "muted" })
    sections.push(setupReportSection("packages", "Packages linked", "accent", "package", pkgItems, false, undoneFlag))
  }
  if (moved.length > 0) {
    var moveItems = []
    for (var m = 0; m < moved.length; m++) moveItems.push({ label: String((moved[m] || {}).path || ""), detail: "", tone: "muted" })
    sections.push(setupReportSection("moved", "Moved to backup", "muted", "file", moveItems, false, undoneFlag))
  }
  if (services.length > 0) {
    var svcItems = []
    for (var s = 0; s < services.length; s++) {
      var svc = services[s] || {}
      var svcOk = svc.state !== undefined ? String(svc.state) === "enabled" : svc.ok === true
      // After an undo the row shows the real current state, not stale "enabled" (finding 74).
      var svcDetail = undoneFlag ? "disabled" : (svcOk ? (svc.state !== undefined ? String(svc.state) : "enabled") : String(svc.error || "failed"))
      svcItems.push({ label: String(svc.unit || ""), detail: svcDetail, tone: (undoneFlag || svcOk) ? "muted" : "urgent" })
    }
    sections.push(setupReportSection("services", "Services", "accent", "service", svcItems, true, undoneFlag))
  }
  if (failed.length > 0) {
    var failItems = []
    for (var f = 0; f < failed.length; f++) failItems.push({ label: String((failed[f] || {}).repo || "") + " \u00b7 " + String((failed[f] || {}).package || ""), detail: String((failed[f] || {}).error || "failed"), tone: "urgent" })
    sections.push(setupReportSection("failed", "Failed", "urgent", "problem", failItems, true, undoneFlag))
  }
  var steps = setupReportSteps(plan, posts)
  if (steps.length > 0) sections.push(setupReportSection("steps", "Steps", "accent", "step", steps, true, undoneFlag))
  if (notes.length > 0) {
    var noteItems = []
    for (var n = 0; n < notes.length; n++) noteItems.push({ label: String(notes[n]), detail: "", tone: "muted" })
    // Notes are instructions, not results: never tag them undone (finding 74).
    sections.push(setupReportSection("notes", "Still to do by hand", "muted", "note", noteItems, true, false))
  }
  var lines = []
  for (var x = 0; x < sections.length; x++) {
    var sec = sections[x]
    for (var y = 0; y < sec.items.length; y++) lines.push({ label: sec.items[y].label, detail: String(sec.items[y].detail || ""), tone: sec.items[y].tone })
  }
  return {
    ok: results === null ? false : r.ok === true,
    backup: String(r.backup || ""),
    backupDir: String(r.backup_dir || ""),
    // A steps-only run changes no files (finding 89): no Undo, "Steps finished".
    stepsOnly: r.steps_only === true,
    linked: appliedPackages.length,
    moved: moved.length,
    services: services.length,
    sections: sections,
    lines: lines
  }
}

// The sentence on the destructive Undo button (README 10b.6/finding 24).
function setupUndoSentence(results) {
  var r = results || {}
  var packages = r.packages || r.applied || []
  var count = 0
  for (var i = 0; i < packages.length; i++) if (String((packages[i] || {}).state || "applied") === "applied") count++
  var moved = num((r.moved || []).length, 0)
  var services = num((r.services || []).length, 0)
  var sentence = "Unlink the " + pluralCount(count, "package") + " and put back the " + pluralCount(moved, "original file")
  if (services > 0) sentence += ", and disable the " + pluralCount(services, "service")
  return sentence
}

// The same sentence from a backup row's counts (README Unit 15/finding 83): the
// header Undo can confirm a single backup directly without an apply result.
function setupUndoSentenceFromCounts(counts) {
  var c = counts || {}
  var services = num(c.services, 0)
  var sentence = "Unlink the " + pluralCount(num(c.packages, 0), "package") +
    " and put back the " + pluralCount(num(c.moved, 0), "original file")
  if (services > 0) sentence += ", and disable the " + pluralCount(services, "service")
  return sentence
}

// Header Undo decision (README Unit 15b/finding 87): with exactly one
// un-undone setup the confirm card opens directly; with none or several the
// backups list opens first. Pure so the header click is unit-tested.
function headerUndo(backups) {
  var active = setupActiveBackups(backups)
  if (active.length !== 1) return { direct: false }
  return {
    direct: true,
    backup: String(active[0].id || ""),
    sentence: setupUndoSentenceFromCounts(active[0].counts)
  }
}

// Rows for the "Setup backups" list (README 10b.7/finding 27).
function setupBackupsRows(backups) {
  var list = backups || []
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var b = list[i] || {}
    var counts = b.counts || {}
    rows.push({
      id: String(b.id || ""),
      label: String(b.created || b.id || ""),
      detail: pluralCount(counts.packages, "package") + " \u00b7 " + pluralCount(counts.moved, "file") + " \u00b7 " + pluralCount(counts.services, "service"),
      undone: b.undone === true,
      counts: counts
    })
  }
  return rows
}

// Live clone progress from setup-progress.json (README 11b.2). percent is -1
// when git has not reported one yet (the UI shows an indeterminate bar).
function setupCloneProgress(progress) {
  var p = progress || {}
  if (String(p.phase || "") !== "clone") return null
  var hasPercent = p.percent !== null && p.percent !== undefined
  var percent = hasPercent ? Number(p.percent) : -1
  var size = String(p.size || "")
  var bytes = parseSizeBytes(size)
  var human = formatBytesDecimal(bytes)
  return {
    item: String(p.item || ""),
    percent: percent,
    size: size,
    bytes: bytes,
    state: String(p.state || ""),
    label: "Downloading " + (hasPercent ? percent + "%" : "\u2026") + (human !== "" ? " \u00b7 " + human : "")
  }
}

// Undo result card data (README 11b.3).
function setupUndoResult(results) {
  var r = results || {}
  var unstowed = r.unstowed || []
  var restored = r.restored || []
  var disabled = r.services_disabled || []
  var refused = r.refused || []
  var errors = r.errors || []
  var lines = []
  if (unstowed.length > 0) lines.push({ label: pluralCount(unstowed.length, "package") + " unlinked", detail: "", tone: "muted" })
  if (restored.length > 0) lines.push({ label: pluralCount(restored.length, "file") + " restored", detail: "", tone: "muted" })
  if (disabled.length > 0) lines.push({ label: pluralCount(disabled.length, "service") + " disabled", detail: "", tone: "muted" })
  for (var i = 0; i < refused.length; i++) lines.push({ label: String(refused[i].package || refused[i].path || ""), detail: "refused", tone: "urgent" })
  for (var e = 0; e < errors.length; e++) lines.push({ label: String(errors[e].path || ""), detail: String(errors[e].error || "error"), tone: "urgent" })
  return { backup: String(r.backup || ""), lines: lines, ok: results !== null && r.ok !== false }
}

var setupWizardSteps = ["Check", "Connect", "Review", "Apply", "Report"]

function setupStepName(index) {
  var i = num(index, -1)
  return i >= 0 && i < setupWizardSteps.length ? setupWizardSteps[i] : ""
}

// Live Apply checklist rows from <state>/setup-progress.json (README 11a.4).
function setupProgressRows(progress) {
  var p = progress || {}
  var items = p.items || []
  var rows = []
  for (var i = 0; i < items.length; i++) {
    var item = items[i] || {}
    rows.push({
      key: String(item.kind || "") + ":" + String(item.id || ""),
      kind: String(item.kind || ""),
      label: String(item.id || ""),
      status: String(item.state || "waiting"),
      detail: ""
    })
  }
  return rows
}

// Review group expansion (README 11a.1): the default comes from the group, the
// override from the user's toggles. Both pure so the toggle is unit-tested.
function setupGroupExpanded(expanded, group) {
  var map = expanded || {}
  var g = group || {}
  var key = String(g.key || "")
  if (map[key] !== undefined) return map[key] === true
  return g.expandByDefault === true
}

function setupToggleGroup(expanded, group) {
  var map = expanded || {}
  var g = group || {}
  var key = String(g.key || "")
  var next = {}
  for (var k in map) next[k] = map[k]
  next[key] = !setupGroupExpanded(map, g)
  return next
}

// One-key accordion (README Unit 15/finding 84): expanding a group collapses
// the previously expanded one. The whole group list is materialized so a
// section's `expandByDefault` cannot re-open behind the user's back.
function setupAccordionToggle(expanded, group, groups) {
  var g = group || {}
  var key = String(g.key || "")
  var wasOpen = setupGroupExpanded(expanded, g)
  var list = groups || []
  var next = {}
  for (var i = 0; i < list.length; i++) {
    var k = String((list[i] || {}).key || "")
    next[k] = (!wasOpen && k === key)
  }
  return next
}

// The next accordion key: toggling the open key closes it (""), any other key
// opens it. Used by the Overview repos/groups accordion.
function accordionKey(current, key) {
  var c = String(current === undefined || current === null ? "" : current)
  var k = String(key === undefined || key === null ? "" : key)
  return c === k ? "" : k
}

function groupFor(groups, key) {
  var gs = groups || []
  for (var i = 0; i < gs.length; i++) if (String(gs[i].key) === String(key)) return gs[i]
  return null
}

// Move the Review group keyboard cursor by `dy` and return the next group key.
function nextGroupKey(groups, currentKey, dy) {
  var gs = groups || []
  if (gs.length === 0) return ""
  var index = -1
  for (var i = 0; i < gs.length; i++) if (String(gs[i].key) === String(currentKey)) index = i
  if (index < 0) index = dy >= 0 ? -1 : gs.length
  index = Math.max(0, Math.min(gs.length - 1, index + (dy >= 0 ? 1 : -1)))
  return String(gs[index].key)
}

// --- Panel selection/cursor helpers (kept pure, moved out of Panel.qml) ----
// Cycle the checked set to one repo; returns the next cycle index.
function selectRepoCycle(changeView, rows, index) {
  var groups = (changeView && changeView.groups) || []
  var repos = []
  for (var g = 0; g < groups.length; g++) repos.push(String(groups[g].repo))
  if (repos.length === 0) return { index: num(index, 0), checked: {}, message: "" }
  var repo = repos[num(index, 0) % repos.length]
  var next = {}
  for (var i = 0; i < rows.length; i++) next[rows[i].key] = String(rows[i].repo) === repo
  return { index: (num(index, 0) + 1) % repos.length, checked: next, message: "Selected " + repoDisplayName(repo) }
}

// Toggle one path in the hidden list; returns the next list and whether it was removed.
function toggleHiddenPath(hiddenPaths, row) {
  var list = hiddenPaths || []
  var next = []
  var removed = false
  for (var i = 0; i < list.length; i++) {
    if (String(list[i]) === String(row.path)) { removed = true; continue }
    next.push(list[i])
  }
  if (!removed) next.push(String(row.path))
  return { paths: next, removed: removed }
}

// Move the cursor by `dy` rows and return the new focused key.
function nextCursor(rows, focusedKey, dy) {
  if (!rows || rows.length === 0) return focusedKey
  var index = 0
  for (var i = 0; i < rows.length; i++) if (rows[i].key === focusedKey) index = i
  index = Math.max(0, Math.min(rows.length - 1, index + num(dy, 0)))
  return rows[index].key
}
