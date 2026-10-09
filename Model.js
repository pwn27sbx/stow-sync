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

// "3h ago", "just now", "1d ago", ... `now` accepts epoch ms or an ISO string;
// when omitted the value reads as "just now".
function relativeTime(iso, now) {
  var then = parseIsoMillis(iso)
  if (then !== then) return ""
  var current
  if (now === undefined || now === null || now === "") current = then
  else if (typeof now === "number") current = now
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

function explain(data) {
  var d = data || {}
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
    subtitle: items.length + " included \u00b7 press to expand",
    count: items.length,
    unit: unit,
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
    groups.push(overviewGroup("outgoing", "Outgoing \u2014 this machine", "files", outgoing))
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
    groups.push(overviewGroup("incoming", "Incoming \u2014 from GitHub", "commits", incoming))
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
    groups.push(overviewGroup("newConfigs", "New config files", "files", newConfigs))
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
      fixing.push({
        type: "health",
        repo: String(current.path || ""),
        package: String(pkg.name || ""),
        health: health,
        stateColor: healthColor(health)
      })
    }
  }
  if (fixing.length > 0) {
    groups.push(overviewGroup("fixing", "Needs fixing", "packages", fixing))
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
      count: count,
      unit: "files",
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
        count: count,
        unit: "files",
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
      else statusText = "Stowed \u00b7 press to expand"
      var target = packageTargetLabel(pkg, files)
      cards.push({
        repo: repoPath,
        name: name,
        icon: packageIcon(name),
        title: name,
        description: (target ? target + " \u00b7 " : "\u00b7 ") + statusText,
        count: files.length,
        unit: "files",
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
  return [
    { label: "Repo", value: String(r.path || "") },
    { label: "Remote", value: remote, copy: remote !== "" },
    { label: "Branch", value: branchValue },
    { label: "Ahead / behind", value: num(r.ahead, 0) + " / " + num(r.behind, 0) },
    { label: "Last commit", value: relativeTime(r.head_time, now) },
    { label: "Last publish", value: relativeTime(r.last_publish, now) },
    { label: "Packages", value: num(r.stowed_packages, 0) + " stowed" },
    { label: "Plugin", value: "stow-sync " + String(version || "") }
  ]
}
