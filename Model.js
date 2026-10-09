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
// changes grouped by package, then stow-health rows, then candidates with
// known:false first. The panel filters this for its collapsed group view.
function buildRows(data) {
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
    for (var p = 0; p < packages.length; p++) rows.push(healthRow(repoPath, packages[p], p))
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
function panelRows(data, showExisting) {
  var all = buildRows(data)
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
    title: "Pull " + String(p.repo || ""),
    message: "Fast-forward only; refuses when the worktree is dirty or diverged.",
    lines: [], confirmText: "Pull", destructive: false
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
  if (tag === "commit") {
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
  if (tag === "commit") return { kind: "commit-error", error: String(message || "") }
  if (tag === "suggest") return { kind: "ignore" }
  return { kind: "mutation-error", error: String(message || "") }
}

function activateIntent(row) {
  if (!row) return { kind: "none" }
  if (row.type === "repo") return { kind: "commit", repo: String(row.name || "") }
  if (row.type === "change") return { kind: "diff", repo: String(row.repo || ""), path: String(row.path || "") }
  if (row.type === "health") return { kind: "restow", repo: String(row.repo || ""), package: String(row.package || "") }
  return { kind: "adopt" }
}
