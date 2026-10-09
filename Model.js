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
    label: count + " packages OK",
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
  new: "\uf067"
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

// Candidates the owner has not acknowledged yet (the "New configs" list).
function newCandidateCount(data) {
  var candidates = (data && data.candidates) || []
  var count = 0
  for (var i = 0; i < candidates.length; i++) if (!candidates[i] || candidates[i].known !== true) count++
  return count
}

function unhealthyCount(repo) {
  var packages = (repo && repo.packages) || []
  var count = 0
  for (var i = 0; i < packages.length; i++) {
    if (String((packages[i] && packages[i].health) || "ok") !== "ok") count++
  }
  return count
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

function plural(count, singular, pluralForm) {
  return count + (count === 1 ? singular : pluralForm)
}

// Top-of-panel state: one glyph, one plain sentence and one hint line.
// `now` is the panel's current "HH:MM" used only when no fetch time exists.
function heroState(data, now) {
  var d = data || {}
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
