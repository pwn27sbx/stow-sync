const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

const source = fs
  .readFileSync(path.join(__dirname, "..", "Model.js"), "utf8")
  .replace(/^\.pragma library\s*$/m, "")

// Model.js is pure: it only needs the standard math/JSON builtins. The vm
// sandbox is its own realm, so give it the globals it references.
const Model = { Math, Number, JSON, Array, String, Object, isFinite }
vm.createContext(Model)
vm.runInContext(source, Model, { filename: "Model.js" })

function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8"))
}

function test(name, body) {
  try {
    body()
  } catch (err) {
    process.stdout.write(`not ok - ${name}\n`)
    process.stdout.write(`${(err && err.stack) || err}\n`)
    process.exit(1)
  }
  process.stdout.write(`ok - ${name}\n`)
}

// The vm realm's arrays/objects have foreign prototypes; normalize before a
// strict structural comparison.
function same(actual, expected, message) {
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message)
}

// --- stateColor: every documented branch ---------------------------------

test("stateColor maps urgent, accent and muted states", () => {
  const urgent = ["conflict", "diverged", "operation", "secret-blocked", "missing"]
  const accent = ["dirty", "ahead", "behind", "candidates", "pending", "dangling", "no-upstream", "detached"]
  for (const state of urgent) assert.equal(Model.stateColor(state), "urgent", state)
  for (const state of accent) assert.equal(Model.stateColor(state), "accent", state)
  assert.equal(Model.stateColor("clean"), "muted")
  assert.equal(Model.stateColor(""), "muted")
  assert.equal(Model.stateColor(undefined), "muted")
})

test("healthColor maps conflicts/pending/dangling/ok", () => {
  assert.equal(Model.healthColor("conflicts"), "urgent")
  assert.equal(Model.healthColor("pending"), "accent")
  assert.equal(Model.healthColor("dangling"), "accent")
  assert.equal(Model.healthColor("ok"), "muted")
})

test("stateTitle has a title for every state and a fallback", () => {
  const expected = {
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
  for (const [state, title] of Object.entries(expected)) assert.equal(Model.stateTitle(state), title, state)
  assert.equal(Model.stateTitle("bogus"), "Unknown")
})

test("repoSubtitle joins branch and ahead/behind", () => {
  assert.equal(Model.repoSubtitle({ branch: "main", ahead: 0, behind: 0 }), "main")
  assert.equal(Model.repoSubtitle({ branch: "main", ahead: 2, behind: 1 }), "main  -  2 ahead  -  1 behind")
  assert.equal(Model.repoSubtitle({ branch: "main", ahead: 0, behind: 3 }), "main  -  3 behind")
  assert.equal(Model.repoSubtitle({ branch: "", state: "detached", ahead: 1 }), "detached  -  1 ahead")
  assert.equal(Model.repoSubtitle({ branch: "", state: "missing" }), "")
  assert.equal(Model.repoSubtitle(null), "")
})

// --- badge ---------------------------------------------------------------

test("badgeCount reads summary.count defensively", () => {
  assert.equal(Model.badgeCount(null), 0)
  assert.equal(Model.badgeCount({}), 0)
  assert.equal(Model.badgeCount({ summary: { count: 4 } }), 4)
  assert.equal(Model.badgeCount({ summary: { count: -2 } }), 0)
  assert.equal(Model.badgeCount({ summary: { count: "7" } }), 7)
})

test("badgeText hides zero and caps at 99+", () => {
  assert.equal(Model.badgeText({ summary: { count: 0 } }), "")
  assert.equal(Model.badgeText({ summary: { count: 1 } }), "1")
  assert.equal(Model.badgeText({ summary: { count: 99 } }), "99")
  assert.equal(Model.badgeText({ summary: { count: 100 } }), "99+")
  assert.equal(Model.badgeText({ summary: { count: 5000 } }), "99+")
})

test("badgeColor takes the worst signal", () => {
  assert.equal(Model.badgeColor({ summary: { state: "clean", count: 0 }, repos: [], candidates: [] }), "muted")
  assert.equal(Model.badgeColor({ summary: { state: "dirty", count: 2 }, repos: [] }), "accent")
  assert.equal(Model.badgeColor({ summary: { state: "conflict", count: 2 }, repos: [] }), "urgent")
  // A package conflict outranks a clean summary.
  assert.equal(Model.badgeColor({
    summary: { state: "clean", count: 0 },
    repos: [{ state: "clean", packages: [{ name: "p", health: "conflicts" }] }]
  }), "urgent")
  // An unknown candidate forces at least accent.
  assert.equal(Model.badgeColor({
    summary: { state: "clean", count: 0 },
    repos: [{ state: "clean", packages: [] }],
    candidates: [{ path: "~/.config/x", known: false }]
  }), "accent")
  // Known candidates alone stay muted.
  assert.equal(Model.badgeColor({
    summary: { state: "clean", count: 0 },
    repos: [{ state: "clean", packages: [] }],
    candidates: [{ path: "~/.config/x", known: true }]
  }), "muted")
  assert.equal(Model.badgeColor({ summary: { state: "clean" }, secret_blocked: true }), "urgent")
})

// --- package grouping ----------------------------------------------------

test("groupChanges sorts packages then paths and labels root", () => {
  const groups = Model.groupChanges([
    { path: "fish/b", package: "fish" },
    { path: "hypr/a", package: "hypr" },
    { path: "fish/a", package: "fish" },
    { path: "rootfile", package: "" }
  ])
  same(groups.map((g) => g.package), ["", "fish", "hypr"])
  same(groups[0].items.map((i) => i.path), ["rootfile"])
  same(groups[1].items.map((i) => i.path), ["fish/a", "fish/b"])
  assert.equal(groups[0].label, "(root)")
})

// --- buildRows -----------------------------------------------------------

test("buildRows collapses a clean repo's healthy packages into one packages-ok row", () => {
  const rows = Model.buildRows(fixture("status-clean.json"))
  same(rows.map((r) => r.type), ["repo", "packages-ok"])
  const repo = rows[0]
  assert.equal(repo.key, "repo:~/.dotfiles")
  assert.equal(repo.name, "~/.dotfiles")
  assert.equal(repo.basename, ".dotfiles")
  assert.equal(repo.state, "clean")
  assert.equal(repo.stateColor, "muted")
  assert.equal(repo.canCommit, false)
  assert.equal(repo.canPush, false)
  assert.equal(repo.canPull, false)
  assert.equal(rows[1].repo, "~/.dotfiles")
  assert.equal(rows[1].count, 1)
  assert.equal(rows[1].expanded, false)
})

test("buildRows emits only unhealthy package rows and a packages-ok summary", () => {
  const rows = Model.buildRows(fixture("status-mixed.json"))
  same(rows.map((r) => r.type), [
    "repo",
    "change", "change", "change", "change",
    "health", "health",
    "packages-ok",
    "repo",
    "repo"
  ])
  // Repo A change order: fish x2, hypr, then the untracked omarchy file.
  same(rows.slice(1, 5).map((r) => r.path), [
    "fish/.config/fish/conf.d/abbr.fish",
    "fish/.config/fish/config.fish",
    "hypr/.config/hypr/hyprland.conf",
    "omarchy/.config/omarchy/backgrounds/nord/new.png"
  ])
  same(rows.slice(1, 5).map((r) => r.packageLabel), ["fish", "fish", "hypr", "omarchy"])
  assert.equal(rows[4].untracked, true)
  // Only unhealthy packages get health rows, alphabetised: fish, hypr.
  same(rows.slice(5, 7).map((r) => r.package), ["fish", "hypr"])
  assert.equal(rows[5].stateColor, "accent")   // pending
  assert.equal(rows[6].stateColor, "urgent")   // conflicts
  // The healthy omarchy package collapses into one summary row.
  assert.equal(rows[7].type, "packages-ok")
  assert.equal(rows[7].count, 1)
  assert.equal(rows[7].expanded, false)
  // Repo A header fields.
  const repoA = rows[0]
  assert.equal(repoA.state, "dirty")
  assert.equal(repoA.stateColor, "accent")
  assert.equal(repoA.canCommit, true)
  assert.equal(repoA.canPush, true)
  assert.equal(repoA.canPull, false)
  assert.equal(repoA.subtitle, "main  -  2 ahead")
  // Diverged repo: no push (not just ahead), no pull (dirty/diverged guard).
  const repoB = rows[8]
  assert.equal(repoB.state, "diverged")
  assert.equal(repoB.stateColor, "urgent")
  assert.equal(repoB.canPush, false)
  assert.equal(repoB.canPull, false)
  // Missing repo.
  const repoC = rows[9]
  assert.equal(repoC.state, "missing")
  assert.equal(repoC.exists, false)
  assert.equal(repoC.canCommit, false)
})

test("buildRows expands healthy packages beneath the packages-ok row", () => {
  const collapsed = Model.buildRows(fixture("status-mixed.json"))
  assert.equal(collapsed.filter((r) => r.type === "health" && r.health === "ok").length, 0)

  const rows = Model.buildRows(fixture("status-mixed.json"), { expandedOk: ["~/.dotfiles"] })
  const summary = rows.find((r) => r.type === "packages-ok")
  assert.equal(summary.expanded, true)
  const at = rows.indexOf(summary)
  assert.equal(rows[at + 1].type, "health")
  assert.equal(rows[at + 1].package, "omarchy")
  assert.equal(rows[at + 1].health, "ok")
})

test("buildRows orders candidates known:false first, watched before other", () => {
  const rows = Model.buildRows(fixture("status-candidates.json"))
  const cands = rows.filter((r) => r.type === "candidate")
  same(cands.map((r) => r.path), [
    "~/.config/systemd/user/a.timer",
    "~/.config/zzz",
    "~/.local/bin/foo",
    "~/.config/aaa"
  ])
  assert.equal(cands[0].known, false)
  assert.equal(cands[0].stateColor, "accent")
  assert.equal(cands[2].known, true)
  assert.equal(cands[2].stateColor, "muted")
  assert.equal(cands[0].suggestedPackage, "systemd")
  assert.equal(cands[1].sizeText, "4.0 KB")
})

test("repo row enablement covers no-upstream and behind-only", () => {
  const rows = Model.buildRows({
    repos: [
      { path: "~/a", exists: true, state: "no-upstream", branch: "main", upstream: "", ahead: 1, behind: 0, changes: [], untracked: [], packages: [] },
      { path: "~/b", exists: true, state: "behind", branch: "main", upstream: "origin/main", ahead: 0, behind: 2, changes: [], untracked: [], packages: [] }
    ],
    candidates: []
  })
  assert.equal(rows[0].canPush, false)  // no upstream to push to
  assert.equal(rows[0].canPull, false)
  assert.equal(rows[1].canPull, true)   // strictly behind and clean
  assert.equal(rows[1].canPush, false)
  assert.equal(rows[1].stateColor, "accent")
})

test("buildRows tolerates missing data", () => {
  same(Model.buildRows(null), [])
  same(Model.buildRows({}), [])
  same(Model.buildRows({ repos: null, candidates: null }), [])
})

test("formatSize picks a readable unit", () => {
  assert.equal(Model.formatSize(0), "0 B")
  assert.equal(Model.formatSize(1023), "1023 B")
  assert.equal(Model.formatSize(1024), "1.0 KB")
  assert.equal(Model.formatSize(1048576), "1.0 MB")
  assert.equal(Model.formatSize("nope"), "0 B")
})

// --- panelRows and friends (view-model helpers) --------------------------

test("panelRows hides known candidates and marks group headers", () => {
  const collapsed = Model.panelRows(fixture("status-candidates.json"), { showExisting: false })
  same(collapsed.rows.filter((r) => r.type === "candidate").map((r) => r.path), [
    "~/.config/systemd/user/a.timer",
    "~/.config/zzz"
  ])
  assert.equal(collapsed.newCount, 2)
  assert.equal(collapsed.existingCount, 2)
  same(collapsed.existingPaths, [])
  assert.equal(collapsed.rows.find((r) => r.type === "candidate").header, "New configs (2)")

  const expanded = Model.panelRows(fixture("status-candidates.json"), { showExisting: true })
  assert.equal(expanded.rows.filter((r) => r.type === "candidate").length, 4)
  same(expanded.existingPaths, ["~/.local/bin/foo", "~/.config/aaa"])
  const existingHeader = expanded.rows.find((r) => r.type === "candidate" && r.known)
  assert.equal(existingHeader.header, "Existing untracked (2)")
  assert.equal(existingHeader.showBulk, true)
  // Non-candidate rows never carry a header.
  assert.equal(expanded.rows[0].header, undefined)
})

test("panelRows forwards expandedOk to buildRows", () => {
  const result = Model.panelRows(fixture("status-clean.json"), { showExisting: false, expandedOk: ["~/.dotfiles"] })
  const summary = result.rows.find((r) => r.type === "packages-ok")
  assert.equal(summary.expanded, true)
  assert.equal(result.rows[result.rows.indexOf(summary) + 1].type, "health")
})

test("panelRows tolerates missing data", () => {
  const result = Model.panelRows(null, { showExisting: true })
  same(result.rows, [])
  assert.equal(result.newCount, 0)
  assert.equal(result.existingCount, 0)
  same(result.existingPaths, [])
})

test("isEmpty reports a fully settled config", () => {
  assert.equal(Model.isEmpty(fixture("status-clean.json"), { newCount: 0 }), true)
  // Known candidates alone do not block the empty state.
  assert.equal(Model.isEmpty(fixture("status-candidates.json"), { newCount: 0 }), true)
  // Unknown candidates do.
  assert.equal(Model.isEmpty(fixture("status-candidates.json"), { newCount: 2 }), false)
  // Changes, ahead/behind or unhealthy packages do.
  assert.equal(Model.isEmpty(fixture("status-mixed.json"), { newCount: 0 }), false)
  assert.equal(Model.isEmpty({
    repos: [{ path: "~/a", exists: true, ahead: 0, behind: 0, changes: [], untracked: [], packages: [{ name: "p", health: "pending" }] }],
    candidates: []
  }, { newCount: 0 }), false)
  assert.equal(Model.isEmpty({
    repos: [{ path: "~/a", exists: true, ahead: 1, behind: 0, changes: [], untracked: [], packages: [] }],
    candidates: []
  }, { newCount: 0 }), false)
  // A missing repo is never "settled".
  assert.equal(Model.isEmpty({
    repos: [{ path: "~/gone", exists: false, ahead: 0, behind: 0, changes: [], untracked: [], packages: [] }],
    candidates: []
  }, { newCount: 0 }), false)
  // Without aux.newCount the unknown candidates are counted from the data.
  assert.equal(Model.isEmpty(fixture("status-candidates.json")), false)
  assert.equal(Model.isEmpty(fixture("status-clean.json")), true)
  // Before any data is loaded the panel must not claim emptiness.
  assert.equal(Model.isEmpty(null, { newCount: 0 }), false)
})

test("selectedPaths honours the checked map and repo", () => {
  const rows = Model.buildRows(fixture("status-mixed.json"))
  const checked = {}
  for (const row of rows) if (row.type === "change") checked[row.key] = true
  checked["change:~/.dotfiles:fish/.config/fish/config.fish"] = false
  const paths = Model.selectedPaths(rows, checked, "~/.dotfiles")
  same(paths, [
    "fish/.config/fish/conf.d/abbr.fish",
    "hypr/.config/hypr/hyprland.conf",
    "omarchy/.config/omarchy/backgrounds/nord/new.png"
  ])
  same(Model.selectedPaths(rows, checked, "~/wallpapers"), [])
})

test("packageFor prefers override, then suggestion, then basename", () => {
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "systemd", path: "~/.config/systemd/user/a.timer" }, {}), "systemd")
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "systemd", path: "~/.config/systemd/user/a.timer" }, { k: "custom" }), "custom")
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "", path: "~/.config/MyTool" }, {}), "mytool")
})

test("moveCursorIndex steps and clamps", () => {
  const rows = [{ type: "repo" }, { type: "change" }, { type: "change" }]
  assert.equal(Model.moveCursorIndex(rows, 0, 0, 1), 1)
  assert.equal(Model.moveCursorIndex(rows, 0, 1, 0), 1)
  assert.equal(Model.moveCursorIndex(rows, 2, 0, 1), 2)
  assert.equal(Model.moveCursorIndex(rows, 0, 0, -1), 0)
  assert.equal(Model.moveCursorIndex([], 3, 0, 1), 0)
})

test("sectionStarts finds repo and candidate group boundaries", () => {
  const rows = [
    { type: "repo" }, { type: "change" }, { type: "health" },
    { type: "repo" },
    { type: "candidate" }, { type: "candidate" }
  ]
  same(Model.sectionStarts(rows), [0, 3, 4])
})

test("confirmSpec names the repo, package and paths", () => {
  const push = Model.confirmSpec("push", { repo: "~/.dotfiles", upstream: "origin/main" })
  assert.equal(push.confirmText, "Push")
  assert.ok(push.title.indexOf("~/.dotfiles") !== -1)
  assert.ok(push.message.indexOf("origin/main") !== -1)

  const adopt = Model.confirmSpec("adopt", { repo: "~/.dotfiles", package: "systemd", path: "~/.config/systemd/user/a.timer" })
  same(adopt.lines, ["~/.config/systemd/user/a.timer", "package: systemd"])
  assert.ok(adopt.title.indexOf("~/.dotfiles") !== -1)

  const bulk = Model.confirmSpec("ignore-all", { paths: ["~/.config/a", "~/.config/b"] })
  same(bulk.lines, ["~/.config/a", "~/.config/b"])
  assert.equal(bulk.destructive, true)

  const baseline = Model.confirmSpec("baseline", { count: 3 })
  assert.ok(baseline.lines[0].indexOf("3") !== -1)
})

test("mutationFor returns the exact argv and stdin", () => {
  same(Model.mutationFor("push", { repo: "~/.dotfiles" }), { tag: "push", args: ["push", "--repo", "~/.dotfiles"], stdin: "" })
  same(Model.mutationFor("restow", { repo: "r", package: "p" }), { tag: "restow", args: ["restow", "--repo", "r", "--package", "p"], stdin: "" })
  same(Model.mutationFor("adopt", { repo: "r", package: "p", path: "~/.config/x" }), { tag: "adopt", args: ["adopt", "--repo", "r", "--package", "p", "--path", "~/.config/x"], stdin: "" })
  same(Model.mutationFor("ignore", { path: "~/.config/x" }), { tag: "ignore", args: ["ignore"], stdin: '["~/.config/x"]' })
  same(Model.mutationFor("ignore-all", { paths: ["a", "b"] }), { tag: "ignore", args: ["ignore"], stdin: '["a","b"]' })
  same(Model.mutationFor("baseline", {}), { tag: "baseline", args: ["baseline", "--reset"], stdin: "" })
})

test("secretLines and commitPayload shape the commit request", () => {
  same(Model.secretLines([{ path: "a", line: 4, rule: "aws-access-key" }]), ["a:4 (aws-access-key)"])
  same(Model.secretLines(null), [])
  same(JSON.parse(Model.commitPayload("msg", ["a"], false)), { message: "msg", paths: ["a"] })
  same(JSON.parse(Model.commitPayload("msg", ["a"], true)), { message: "msg", paths: ["a"], allow_secrets: true })
})

test("pickerOptions merges packages, suggestion and current", () => {
  same(Model.pickerOptions(["systemd", "fish"], "bin", "systemd"), ["bin", "systemd", "fish"])
  same(Model.pickerOptions(["systemd"], "systemd", "systemd"), ["systemd"])
  same(Model.pickerOptions([], "", ""), [])
})

test("adoptTarget picks the first existing repo and its packages", () => {
  const target = Model.adoptTarget([
    { path: "~/a", exists: false, packages: [{ name: "x" }] },
    { path: "~/b", exists: true, packages: [{ name: "systemd" }, { name: "fish" }] },
    { path: "~/c", exists: true, packages: [{ name: "other" }] }
  ])
  assert.equal(target.repo, "~/b")
  same(target.packages, ["systemd", "fish"])
  assert.equal(Model.adoptTarget([]).repo, "")
  assert.equal(Model.adoptTarget(null).repo, "")
})

test("findRepo matches by path", () => {
  const repos = [{ path: "~/a" }, { path: "~/b" }]
  assert.equal(Model.findRepo(repos, "~/b"), repos[1])
  assert.equal(Model.findRepo(repos, "~/z"), null)
})

test("nextSectionIndex wraps across repo and candidate sections", () => {
  const rows = [
    { type: "repo" }, { type: "change" }, { type: "health" },
    { type: "repo" }, { type: "change" },
    { type: "candidate" }, { type: "candidate" }
  ]
  assert.equal(Model.nextSectionIndex(rows, 0, 1), 3)
  assert.equal(Model.nextSectionIndex(rows, 3, 1), 5)
  assert.equal(Model.nextSectionIndex(rows, 5, 1), 0)
  assert.equal(Model.nextSectionIndex(rows, 5, -1), 3)
  assert.equal(Model.nextSectionIndex([], 0, 1), -1)
})

test("actionOutcome classifies every result", () => {
  assert.equal(Model.actionOutcome("diff", { text: "x", truncated: true }).kind, "diff")
  assert.equal(Model.actionOutcome("suggest", { message: "m" }).kind, "suggest")
  assert.equal(Model.actionOutcome("commit", { ok: false, secrets: [{ path: "a" }] }).kind, "commit-secrets")
  assert.equal(Model.actionOutcome("commit", { ok: false, error: "boom" }).kind, "commit-error")
  assert.equal(Model.actionOutcome("commit", { ok: true }).kind, "commit-ok")
  assert.equal(Model.actionOutcome("push", { ok: true, push_error: "nope" }).kind, "mutation-error")
  assert.equal(Model.actionOutcome("push", { ok: true, pushed: true }).kind, "mutation-ok")
})

test("failureOutcome classifies transport failures", () => {
  assert.equal(Model.failureOutcome("status", "x").kind, "status-error")
  assert.equal(Model.failureOutcome("status-fetch", "x").kind, "status-error")
  assert.equal(Model.failureOutcome("commit", "x").kind, "commit-error")
  assert.equal(Model.failureOutcome("suggest", "x").kind, "ignore")
  assert.equal(Model.failureOutcome("push", "x").kind, "mutation-error")
})

test("activateIntent maps a row to its primary action", () => {
  assert.equal(Model.activateIntent({ type: "repo", name: "~/a" }).kind, "commit")
  assert.equal(Model.activateIntent({ type: "change", repo: "~/a", path: "p" }).kind, "diff")
  assert.equal(Model.activateIntent({ type: "health", repo: "~/a", package: "p" }).kind, "restow")
  assert.equal(Model.activateIntent({ type: "packages-ok", repo: "~/a", count: 2 }).kind, "toggle-ok")
  assert.equal(Model.activateIntent({ type: "candidate" }).kind, "adopt")
  assert.equal(Model.activateIntent(null).kind, "none")
})

// --- request queue (Runner's FIFO, moved out of QML) ----------------------

function statusRequest(fetch) {
  return {
    isStatus: true,
    fetch: !!fetch,
    tag: fetch ? "status-fetch" : "status",
    args: fetch ? ["status", "--fetch"] : ["status"],
    stdin: ""
  }
}

function actionRequest(tag) {
  return { isStatus: false, fetch: false, tag: tag, args: [tag], stdin: "" }
}

test("nextRequest shifts the front and reports an empty queue", () => {
  const action = actionRequest("push")
  const first = Model.nextRequest([action, statusRequest(false)])
  assert.equal(first.request, action)
  same(first.queue.map((r) => r.tag), ["status"])
  const last = Model.nextRequest(first.queue)
  assert.equal(last.request.isStatus, true)
  same(last.queue, [])
  const empty = Model.nextRequest([])
  assert.equal(empty.request, null)
  same(empty.queue, [])
})

test("runnerMayStart: only when settings are ready and a request is pending", () => {
  assert.equal(Model.runnerMayStart(true, true), true)
  assert.equal(Model.runnerMayStart(true, false), false)
  assert.equal(Model.runnerMayStart(false, true), false)
  assert.equal(Model.runnerMayStart(false, false), false)
  // Only an explicit boolean true opens the gate (a stray truthy value does not).
  assert.equal(Model.runnerMayStart("true", 1), false)
  assert.equal(Model.runnerMayStart(undefined, true), false)
})

test("enqueue dedupes identical pending status requests but never to zero", () => {
  let queue = Model.enqueue([], statusRequest(false))
  assert.equal(queue.length, 1)
  queue = Model.enqueue(queue, statusRequest(false))
  assert.equal(queue.length, 1) // collapsed, never zero and never two
  // A different fetch flag is a different request and stays queued.
  queue = Model.enqueue(queue, statusRequest(true))
  assert.equal(queue.length, 2)
  // Non-status requests are never deduped.
  let actions = Model.enqueue([], actionRequest("push"))
  actions = Model.enqueue(actions, actionRequest("push"))
  assert.equal(actions.length, 2)
})

test("a status refresh during an action is kept and runs right after it", () => {
  // The action is running, so it has already been shifted out of the queue.
  const taken = Model.nextRequest(Model.enqueue([], actionRequest("commit")))
  assert.equal(taken.request.tag, "commit")
  let queue = taken.queue
  // The panel asks for a refresh while the action is still in flight.
  queue = Model.enqueue(queue, statusRequest(false))
  assert.equal(queue.length, 1)
  // When the action finishes the refresh is the very next request.
  const after = Model.nextRequest(queue)
  assert.equal(after.request.isStatus, true)
  assert.equal(after.request.fetch, false)
  same(after.queue, [])
})

test("queue helpers tolerate missing input", () => {
  same(Model.enqueue(null, null), [])
  same(Model.enqueue(undefined, null), [])
  assert.equal(Model.enqueue(undefined, statusRequest(false)).length, 1)
  const empty = Model.nextRequest(null)
  assert.equal(empty.request, null)
  same(empty.queue, [])
})

// --- heroState / primaryAction (Unit 4c) ---------------------------------

const HERO = fixture("hero-cases.json")
const GLYPH_CHECK = "\uf00c"
const GLYPH_WARN = "\uf071"

test("heroState: everything clean shows the check glyph and last checked time", () => {
  const hero = Model.heroState(HERO.clean)
  assert.equal(hero.glyph, GLYPH_CHECK)
  assert.equal(hero.title, "Everything is saved and synced")
  assert.equal(hero.hint, "Last checked 15:00")
  assert.equal(hero.tone, "muted")
})

test("heroState: clean without a fetch time falls back to now", () => {
  const hero = Model.heroState(HERO.cleanNoFetch, "09:41")
  assert.equal(hero.glyph, GLYPH_CHECK)
  assert.equal(hero.hint, "Last checked 09:41")
})

test("heroState: local changes count every file and name the repos", () => {
  const hero = Model.heroState(HERO.changes)
  assert.equal(hero.title, "3 changes to publish")
  assert.equal(hero.hint, "in dotfiles, wallpapers")
  assert.equal(hero.tone, "accent")
})

test("heroState: a single change uses singular wording", () => {
  assert.equal(Model.heroState(HERO.singleChange).title, "1 change to publish")
})

test("heroState: ahead only counts commits waiting to be uploaded", () => {
  const hero = Model.heroState(HERO.ahead)
  assert.equal(hero.title, "2 commits waiting to be uploaded")
  assert.equal(hero.hint, "in dotfiles")
  assert.equal(hero.tone, "accent")
})

test("heroState: behind offers updates from GitHub", () => {
  const hero = Model.heroState(HERO.behind)
  assert.equal(hero.title, "Updates available from GitHub")
  assert.equal(hero.hint, "in wallpapers")
  assert.equal(hero.tone, "accent")
})

test("heroState: diverged is attention and names the repo and problem", () => {
  const hero = Model.heroState(HERO.diverged)
  assert.equal(hero.glyph, GLYPH_WARN)
  assert.equal(hero.title, "Needs your attention")
  assert.equal(hero.tone, "urgent")
  assert.ok(hero.hint.indexOf("dotfiles") !== -1, hero.hint)
})

test("heroState: an in-progress operation is attention", () => {
  const hero = Model.heroState(HERO.operation)
  assert.equal(hero.title, "Needs your attention")
  assert.equal(hero.tone, "urgent")
  assert.ok(hero.hint.toLowerCase().indexOf("merge") !== -1, hero.hint)
})

test("heroState: a stow conflict is attention", () => {
  const hero = Model.heroState(HERO.conflict)
  assert.equal(hero.glyph, GLYPH_WARN)
  assert.equal(hero.title, "Needs your attention")
  assert.equal(hero.tone, "urgent")
})

test("heroState: new configs only counts files not in Stow", () => {
  const hero = Model.heroState(HERO.newConfigs)
  assert.equal(hero.title, "2 new config files not in Stow")
  assert.equal(hero.tone, "accent")
})

test("heroState: attention outranks local changes", () => {
  assert.equal(Model.heroState(HERO.diverged).title, "Needs your attention")
})

test("primaryAction precedence and labels", () => {
  assert.equal(Model.primaryAction(HERO.conflict).kind, "review")
  assert.equal(Model.primaryAction(HERO.conflict).label, "Review")
  assert.equal(Model.primaryAction(HERO.changes).kind, "publish")
  assert.equal(Model.primaryAction(HERO.changes).label, "Publish")
  assert.equal(Model.primaryAction(HERO.ahead).kind, "upload")
  assert.equal(Model.primaryAction(HERO.ahead).label, "Upload")
  assert.equal(Model.primaryAction(HERO.behind).kind, "update")
  assert.equal(Model.primaryAction(HERO.behind).label, "Update")
  assert.equal(Model.primaryAction(HERO.newConfigs).kind, "review-new")
  assert.equal(Model.primaryAction(HERO.newConfigs).label, "Review new configs")
  const none = Model.primaryAction(HERO.clean)
  assert.equal(none.kind, "none")
  assert.equal(none.label, "")
})

// --- tab builders (Unit 4c) ----------------------------------------------

test("repoDisplayName strips the dot-prefixed basename", () => {
  assert.equal(Model.repoDisplayName("~/.dotfiles"), "dotfiles")
  assert.equal(Model.repoDisplayName("~/wallpapers"), "wallpapers")
  assert.equal(Model.repoDisplayName("~/wallpapers/"), "wallpapers")
  assert.equal(Model.repoDisplayName(""), "")
})

test("repoPlainStatus describes a repo in plain words", () => {
  assert.equal(Model.repoPlainStatus({ exists: true, changes: [{ path: "a" }], untracked: [], packages: [] }), "1 change to publish")
  assert.equal(Model.repoPlainStatus({ exists: true, changes: [], untracked: [], ahead: 2, packages: [] }), "2 commits to upload")
  assert.equal(Model.repoPlainStatus({ exists: true, behind: 1, changes: [], untracked: [], packages: [] }), "1 update available")
  assert.equal(Model.repoPlainStatus({ exists: false }), "Repository is missing")
  assert.equal(Model.repoPlainStatus({ exists: true, changes: [], untracked: [], packages: [{ name: "p", health: "conflicts" }] }), "1 package needs fixing")
  assert.equal(Model.repoPlainStatus({ exists: true, changes: [], untracked: [], ahead: 0, behind: 0, packages: [] }), "Everything is saved and synced")
})

test("overviewTabRows lists each repo then its unhealthy packages", () => {
  const rows = Model.overviewTabRows(fixture("status-mixed.json"))
  same(rows.map((r) => r.type), ["repo", "health", "health", "repo", "repo"])
  assert.equal(rows[0].statusText, "4 changes to publish")
  same(rows.slice(1, 3).map((r) => r.package), ["fish", "hypr"])
  assert.equal(rows[1].attention, true)
  assert.equal(rows[3].statusText, "Changes on both sides — needs a manual merge")
  assert.equal(rows[4].statusText, "Repository is missing")
})

test("changeTabRows groups by repo then package and stamps headers", () => {
  const rows = Model.changeTabRows(fixture("status-mixed.json"))
  same(rows.map((r) => r.type), ["change", "change", "change", "change"])
  same(rows.map((r) => r.path), [
    "fish/.config/fish/conf.d/abbr.fish",
    "fish/.config/fish/config.fish",
    "hypr/.config/hypr/hyprland.conf",
    "omarchy/.config/omarchy/backgrounds/nord/new.png"
  ])
  same(rows.map((r) => r.header), [
    "dotfiles  ›  fish", "", "dotfiles  ›  hypr", "dotfiles  ›  omarchy"
  ])
})

test("candidateTabRows splits new from a collapsible existing group", () => {
  const collapsed = Model.candidateTabRows(fixture("status-candidates.json"), { showExisting: false })
  same(collapsed.rows.map((r) => r.type), ["candidate", "candidate", "group"])
  same(collapsed.rows.slice(0, 2).map((r) => r.path), ["~/.config/systemd/user/a.timer", "~/.config/zzz"])
  assert.equal(collapsed.newCount, 2)
  assert.equal(collapsed.existingCount, 2)
  same(collapsed.existingPaths, ["~/.local/bin/foo", "~/.config/aaa"])
  assert.equal(collapsed.rows[0].header, "New configs (2)")
  assert.equal(collapsed.rows[2].label, "Existing untracked (2)")
  assert.equal(collapsed.rows[2].expanded, false)
  assert.equal(collapsed.rows[2].showAction, false)

  const expanded = Model.candidateTabRows(fixture("status-candidates.json"), { showExisting: true })
  same(expanded.rows.map((r) => r.type), ["candidate", "candidate", "group", "candidate", "candidate"])
  assert.equal(expanded.rows[2].expanded, true)
  assert.equal(expanded.rows[2].showAction, true)
  same(expanded.rows.slice(3).map((r) => r.path), ["~/.local/bin/foo", "~/.config/aaa"])
})

test("publishPlan commits then pushes every repo with selected changes", () => {
  const plan = Model.publishPlan(fixture("status-mixed.json"), {}, "chore: update", false)
  same(plan.map((s) => s.tag), ["publish-commit", "publish-push"])
  assert.equal(plan[0].args.join(" "), "commit --repo ~/.dotfiles")
  assert.equal(plan[1].args.join(" "), "push --repo ~/.dotfiles")
  same(JSON.parse(plan[0].stdin), { message: "chore: update", paths: [
    "fish/.config/fish/conf.d/abbr.fish",
    "fish/.config/fish/config.fish",
    "hypr/.config/hypr/hyprland.conf",
    "omarchy/.config/omarchy/backgrounds/nord/new.png"
  ] })

  const twoRepos = {
    repos: [
      { path: "~/.dotfiles", upstream: "origin/main", changes: [{ path: "a", package: "p" }], untracked: [] },
      { path: "~/wallpapers", upstream: "origin/main", changes: [], untracked: [{ path: "w", package: "walls" }] }
    ],
    candidates: []
  }
  const both = Model.publishPlan(twoRepos, {}, "m", true)
  same(both.map((s) => s.tag), ["publish-commit", "publish-push", "publish-commit", "publish-push"])
  same(JSON.parse(both[0].stdin).allow_secrets, true)
  same(both[0].args, ["commit", "--repo", "~/.dotfiles"])
  same(both[2].args, ["commit", "--repo", "~/wallpapers"])
})

test("publishPlan honours the checked map", () => {
  const rows = Model.changeTabRows(fixture("status-mixed.json"))
  const checked = {}
  for (const row of rows) checked[row.key] = true
  checked["change:~/.dotfiles:fish/.config/fish/config.fish"] = false
  const plan = Model.publishPlan(fixture("status-mixed.json"), checked, "m", false)
  const paths = JSON.parse(plan[0].stdin).paths
  assert.equal(paths.indexOf("fish/.config/fish/config.fish"), -1)
  assert.equal(paths.length, 3)
})

test("publishPlan is empty when nothing is selected", () => {
  same(Model.publishPlan(fixture("status-clean.json"), {}, "m", false), [])
})

test("publishCard flattens file lines and names each target", () => {
  const card = Model.publishCard(HERO.changes, {}, "")
  same(card.lines, ["fish/a", "fish/b", "walls/x.png"])
  same(card.targets, ["dotfiles → origin/main", "wallpapers → origin/main"])
  const filtered = Model.publishCard(HERO.changes, {}, "~/.dotfiles")
  same(filtered.lines, ["fish/a", "fish/b"])
  assert.equal(Model.commitStepCount(Model.publishPlan(HERO.changes, {}, "m", false)), 2)
})

// --- B2: adopt prefill (never the first package) --------------------------

test("packageFor never falls back to the first package", () => {
  // The suggestion wins over any package list ordering.
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "stow-sync", path: "~/.config/stow-sync" }, {}), "stow-sync")
  // An explicit override wins.
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "cava", path: "~/.config/x" }, { k: "mine" }), "mine")
  // No suggestion: derive from the basename, not from a list.
  assert.equal(Model.packageFor({ key: "k", suggestedPackage: "", path: "~/.config/MyTool" }, {}), "mytool")
})

test("pickerOptions offers the repo packages plus the suggestion", () => {
  same(Model.pickerOptions(["cava", "fish"], "stow-sync", "stow-sync"), ["stow-sync", "cava", "fish"])
  same(Model.pickerOptions([], "stow-sync", ""), ["stow-sync"])
})

test("publishRepos pairs each repo with its selected paths and upstream", () => {
  const list = Model.publishRepos(HERO.changes, {})
  same(list.map((r) => r.repo), ["~/.dotfiles", "~/wallpapers"])
  same(list[0].paths, ["fish/a", "fish/b"])
  same(list[1].paths, ["walls/x.png"])
  assert.equal(list[0].upstream, "origin/main")
})

test("uploadPlan and updatePlan target only ahead/behind repos", () => {
  const status = {
    repos: [
      { path: "~/a", upstream: "origin/main", ahead: 2, behind: 0 },
      { path: "~/b", upstream: "origin/main", ahead: 0, behind: 1 },
      { path: "~/c", upstream: "", ahead: 1, behind: 0 }
    ],
    candidates: []
  }
  same(Model.uploadPlan(status).map((s) => s.args.join(" ")), ["push --repo ~/a"])
  same(Model.updatePlan(status).map((s) => s.args.join(" ")), ["pull --repo ~/b"])
  same(Model.uploadPlan({ repos: [] }), [])
})

test("confirmSpec covers upload and update in plain words", () => {
  assert.equal(Model.confirmSpec("upload", { repos: ["~/.dotfiles"] }).confirmText, "Upload")
  assert.equal(Model.confirmSpec("update", { repos: ["~/.dotfiles"] }).confirmText, "Update")
  assert.equal(Model.confirmSpec("pull", { repo: "~/.dotfiles" }).confirmText, "Update")
})

// --- Unit 4d: config-sync parity view models ------------------------------

test("relativeTime formats ISO deltas and tolerates junk", () => {
  assert.equal(Model.relativeTime("2026-10-09T15:00:00-05:00", "2026-10-09T18:00:00-05:00"), "3h ago")
  assert.equal(Model.relativeTime("2026-10-09T15:00:00Z", Date.parse("2026-10-09T15:00:20Z")), "just now")
  assert.equal(Model.relativeTime("2026-10-09T15:00:00Z", "2026-10-09T15:30:00Z"), "30m ago")
  assert.equal(Model.relativeTime("2026-10-08T15:00:00Z", "2026-10-09T15:00:00Z"), "1d ago")
  assert.equal(Model.relativeTime("2026-10-01T15:00:00Z", "2026-10-09T15:00:00Z"), "1w ago")
  assert.equal(Model.relativeTime("2026-08-09T15:00:00Z", "2026-10-09T15:00:00Z"), "2mo ago")
  assert.equal(Model.relativeTime("2025-10-09T15:00:00Z", "2026-10-09T15:00:00Z"), "1y ago")
  assert.equal(Model.relativeTime(null, "2026-10-09T15:00:00Z"), "")
  assert.equal(Model.relativeTime("bogus", "2026-10-09T15:00:00Z"), "")
})

test("relativeTime accepts the panel's epoch-milliseconds now string", () => {
  // Panel passes `now` as String(Date.now()) (epoch milliseconds as a string).
  const now = String(Date.parse("2026-10-09T17:00:00Z"))
  assert.equal(Model.relativeTime("2026-10-09T15:00:00Z", now), "2h ago")
  assert.equal(Model.relativeTime("2026-10-06T17:00:00Z", now), "3d ago")
  assert.equal(Model.relativeTime("2026-10-09T19:00:00Z", now), "just now")
})

test("explain describes each state in plain words", () => {
  assert.ok(Model.explain(HERO.clean).indexOf("Everything is saved and synced") !== -1)
  const changes = Model.explain(HERO.changes)
  assert.ok(changes.indexOf("Your dotfiles and wallpapers have 3 local changes.") !== -1, changes)
  assert.ok(Model.explain(HERO.changes).indexOf("Publish") !== -1)
  const ahead = Model.explain(HERO.ahead)
  assert.ok(ahead.indexOf("2 commits waiting to upload in dotfiles") !== -1, ahead)
  const behind = Model.explain(HERO.behind)
  assert.ok(behind.indexOf("3 newer commits for wallpapers") !== -1, behind)
  const attention = Model.explain(HERO.diverged)
  assert.ok(attention.indexOf("attention") !== -1, attention)
  assert.ok(attention.indexOf("dotfiles") !== -1, attention)
  const fresh = Model.explain(HERO.newConfigs)
  assert.ok(fresh.indexOf("2 new config files are not in Stow yet") !== -1, fresh)
})

test("statTiles returns four tiles with real nerd-font glyphs", () => {
  const tiles = Model.statTiles(HERO.changes)
  same(tiles.map((t) => t.key), ["changes", "upload", "updates", "newConfigs"])
  assert.equal(tiles[0].value, "3")
  assert.equal(tiles[0].label, "Changes")
  assert.equal(tiles[0].icon, "\uf040")
  assert.equal(tiles[0].tone, "accent")
  assert.equal(tiles[1].value, "0")
  assert.equal(tiles[1].label, "To upload")
  assert.equal(tiles[1].icon, "\uf0ee")
  assert.equal(tiles[1].tone, "muted")
  assert.equal(tiles[2].value, "0")
  assert.equal(tiles[2].label, "Updates")
  assert.equal(tiles[2].icon, "\uf0ed")
  assert.equal(tiles[2].tone, "muted")
  assert.equal(tiles[3].value, "0")
  assert.equal(tiles[3].label, "New configs")
  assert.equal(tiles[3].icon, "\uf0752")
  assert.equal(Model.statTiles(HERO.newConfigs)[3].value, "2")
  assert.equal(Model.statTiles(HERO.newConfigs)[3].tone, "accent")
})

test("overviewGroups builds only the non-empty collapsible groups", () => {
  const groups = Model.overviewGroups(fixture("status-mixed.json"))
  same(groups.map((g) => g.key), ["outgoing", "fixing"])
  const outgoing = groups[0]
  assert.equal(outgoing.title, "Outgoing \u2014 this machine")
  assert.equal(outgoing.count, 4)
  assert.equal(outgoing.unit, "files")
  assert.equal(outgoing.subtitle, "4 items included")
  assert.equal(outgoing.expanded, false)
  assert.equal(outgoing.items.length, 4)
  assert.equal(outgoing.items[0].package, "fish")
  assert.equal(outgoing.items[0].chip, "A")
  const fixing = groups[1]
  assert.equal(fixing.title, "Needs fixing")
  assert.equal(fixing.count, 2)
  assert.equal(fixing.unit, "packages")
  same(fixing.items.map((i) => i.package), ["fish", "hypr"])
  assert.equal(fixing.items[1].stateColor, "urgent")
})

test("overviewGroups lists incoming commits supplied by the backend", () => {
  const status = {
    repos: [{
      path: "~/a", exists: true, state: "behind", ahead: 0, behind: 2,
      changes: [], untracked: [], packages: [],
      incoming_commits: [
        { hash: "abc1234", subject: "fix fish" },
        { hash: "def5678", subject: "add walls" }
      ]
    }],
    candidates: []
  }
  const groups = Model.overviewGroups(status)
  const incoming = groups.find((g) => g.key === "incoming")
  assert.equal(incoming.title, "Incoming \u2014 from GitHub")
  assert.equal(incoming.count, 2)
  assert.equal(incoming.unit, "commits")
  assert.equal(incoming.subtitle, "2 items included")
  same(incoming.items.map((i) => i.hash), ["abc1234", "def5678"])
  assert.equal(incoming.items[0].subject, "fix fish")
})

test("changesGroups nests repos then packages with checkbox rows", () => {
  const groups = Model.changesGroups(fixture("status-mixed.json"), {})
  same(groups.map((g) => g.repo), ["~/.dotfiles"])
  const dotfiles = groups[0]
  assert.equal(dotfiles.title, "dotfiles")
  assert.equal(dotfiles.count, 4)
  assert.equal(dotfiles.unit, "files")
  same(dotfiles.packages.map((p) => p.package), ["fish", "hypr", "omarchy"])
  const fish = dotfiles.packages[0]
  assert.equal(fish.count, 2)
  same(fish.items.map((i) => i.path), [
    "fish/.config/fish/conf.d/abbr.fish",
    "fish/.config/fish/config.fish"
  ])
  same(fish.items.map((i) => i.chip), ["A", "M"])
  assert.equal(fish.items[0].checked, true)
  assert.equal(fish.items[0].hidden, false)
  assert.equal(dotfiles.packages[2].items[0].chip, "?")
})

test("changesGroups honours hiddenPaths and selectedRepos", () => {
  const hidden = Model.changesGroups(fixture("status-mixed.json"), {
    hiddenPaths: ["fish/.config/fish/config.fish"]
  })
  const target = hidden[0].packages[0].items.find((i) => i.path === "fish/.config/fish/config.fish")
  assert.equal(target.hidden, true)
  same(Model.changesGroups(fixture("status-mixed.json"), { selectedRepos: ["~/wallpapers"] }), [])
  same(Model.changesGroups(null, {}), [])
})

test("changesGroups hides known untracked rows unless showExisting", () => {
  const status = {
    repos: [{ path: "~/a", exists: true, changes: [], untracked: [{ path: "p/known", package: "p", known: true }], packages: [] }],
    candidates: []
  }
  assert.equal(Model.changesGroups(status, { showExisting: true })[0].packages[0].items[0].hidden, false)
  assert.equal(Model.changesGroups(status, { showExisting: false })[0].packages[0].items[0].hidden, true)
})

test("packageCards describes each package and maps a real icon", () => {
  const status = {
    repos: [{
      path: "~/.dotfiles", exists: true,
      packages: [
        { name: "fish", health: "ok", pending_links: [], conflicts: [], dangling: [] },
        { name: "nvim", health: "conflicts", pending_links: [], conflicts: [{ message: "x" }], dangling: [] },
        { name: "omarchy", health: "ok", pending_links: [], conflicts: [], dangling: [] }
      ],
      changes: [
        { path: "fish/.config/fish/config.fish", package: "fish", x: "M", y: " ", kind: "modified" },
        { path: "fish/.config/fish/conf.d/abbr.fish", package: "fish", x: "A", y: " ", kind: "added" }
      ],
      untracked: []
    }],
    candidates: []
  }
  const cards = Model.packageCards(status)
  same(cards.map((c) => c.name), ["fish", "nvim", "omarchy"])
  const fish = cards[0]
  assert.equal(fish.repo, "~/.dotfiles")
  assert.equal(fish.icon, "\uf120")
  assert.equal(fish.title, "fish")
  assert.equal(fish.description, "~/.config/fish \u00b7 2 changes")
  assert.equal(fish.count, 2)
  assert.equal(fish.unit, "files")
  same(fish.files.map((f) => f.path), [
    "fish/.config/fish/conf.d/abbr.fish",
    "fish/.config/fish/config.fish"
  ])
  same(fish.files.map((f) => f.state), ["added", "modified"])
  assert.equal(fish.expanded, false)
  assert.equal(cards[1].icon, "\ue83a")
  assert.ok(cards[1].description.indexOf("Needs fixing") !== -1, cards[1].description)
  assert.equal(cards[2].icon, "\uf03d8")
  assert.ok(cards[2].description.indexOf("Stowed") !== -1, cards[2].description)
  assert.equal(cards[2].count, 0)
})

test("packageCards defaults maps each documented package to a glyph", () => {
  const status = {
    repos: [{
      path: "~/r", exists: true, changes: [], untracked: [],
      packages: [
        { name: "walls", health: "ok", pending_links: [], conflicts: [], dangling: [] },
        { name: "ai-tools", health: "ok", pending_links: [], conflicts: [], dangling: [] },
        { name: "misc", health: "ok", pending_links: [], conflicts: [], dangling: [] }
      ]
    }],
    candidates: []
  }
  const cards = Model.packageCards(status)
  const byName = {}
  for (const card of cards) byName[card.name] = card.icon
  assert.equal(byName["walls"], "\uf03e")
  assert.equal(byName["ai-tools"], "\uf0ad")
  assert.equal(byName["misc"], "\uf07b")
})

test("changesView drops hidden rows unless showHidden and flattens the visible ones", () => {
  const view = Model.changesView(fixture("status-mixed.json"), {
    hiddenPaths: ["fish/.config/fish/config.fish"]
  })
  same(view.groups.map((g) => g.repo), ["~/.dotfiles"])
  same(view.groups[0].packages.map((p) => p.package), ["fish", "hypr", "omarchy"])
  assert.equal(view.groups[0].packages[0].count, 1)
  same(view.groups[0].packages[0].items.map((i) => i.path), ["fish/.config/fish/conf.d/abbr.fish"])
  same(view.rows.map((r) => r.path), [
    "fish/.config/fish/conf.d/abbr.fish",
    "hypr/.config/hypr/hyprland.conf",
    "omarchy/.config/omarchy/backgrounds/nord/new.png"
  ])
  assert.equal(view.rows[0].key, "change:~/.dotfiles:fish/.config/fish/conf.d/abbr.fish")
  assert.equal(view.groups[0].count, 3)
})

test("changesView keeps hidden rows when showHidden and drops empty groups", () => {
  const shown = Model.changesView(fixture("status-mixed.json"), {
    hiddenPaths: ["fish/.config/fish/config.fish"],
    showHidden: true
  })
  assert.equal(shown.groups[0].packages[0].count, 2)
  assert.equal(shown.rows.length, 4)
  // Selecting a repo with no changes yields no groups and no rows.
  const none = Model.changesView(fixture("status-mixed.json"), { selectedRepos: ["~/wallpapers"] })
  same(none.groups, [])
  same(none.rows, [])
  // Tolerates missing data.
  same(Model.changesView(null, {}).groups, [])
})

test("healthLabel spells out each package health", () => {
  assert.equal(Model.healthLabel("conflicts"), "conflict")
  assert.equal(Model.healthLabel("pending"), "pending link")
  assert.equal(Model.healthLabel("dangling"), "dangling link")
  assert.equal(Model.healthLabel("weird"), "weird")
  assert.equal(Model.healthLabel(null), "ok")
})

test("firstUnhealthy finds the first unhealthy package in config order", () => {
  const status = {
    repos: [
      { path: "~/a", packages: [{ name: "ok1", health: "ok" }] },
      { path: "~/b", packages: [{ name: "ok2", health: "ok" }, { name: "bad", health: "pending" }, { name: "worse", health: "conflicts" }] }
    ]
  }
  same(Model.firstUnhealthy(status), { repo: "~/b", package: "bad" })
  assert.equal(Model.firstUnhealthy({ repos: [{ path: "~/a", packages: [{ name: "x", health: "ok" }] }] }), null)
  assert.equal(Model.firstUnhealthy(null), null)
  assert.equal(Model.firstUnhealthy({}), null)
})

test("repoInfoRows renders the info table with relative times", () => {
  const repo = {
    path: "~/.dotfiles", remote_url: "https://github.com/u/r.git", branch: "main", head: "abc1234",
    ahead: 0, behind: 0, head_time: "2026-10-09T15:00:00-05:00",
    last_publish: "2026-10-08T15:00:00-05:00", stowed_packages: 16
  }
  const rows = Model.repoInfoRows(repo, "0.1.0", "2026-10-09T18:00:00-05:00")
  same(rows.map((r) => r.label), [
    "Repo", "Remote", "Branch", "Sync", "Last commit", "Last publish", "Packages", "Plugin"
  ])
  assert.equal(rows[0].value, "~/.dotfiles")
  assert.equal(rows[1].value, "https://github.com/u/r.git")
  assert.equal(rows[1].copy, true)
  assert.equal(rows[2].value, "main @ abc1234")
  assert.equal(rows[3].value, "\u21910 \u21930")
  assert.equal(rows[4].value, "3h ago")
  assert.equal(rows[5].value, "1d ago")
  assert.equal(rows[6].value, "16 packages")
  assert.equal(rows[7].value, "stow-sync 0.1.0")
})

test("repoInfoRows shows never for an unknown last publish", () => {
  const repo = {
    path: "~/x", branch: "main", head: "abc", ahead: 0, behind: 0,
    head_time: "2026-10-09T15:00:00Z", last_publish: null, stowed_packages: 1
  }
  const rows = Model.repoInfoRows(repo, "0.1.0", "2026-10-09T18:00:00Z")
  assert.equal(rows[5].label, "Last publish")
  assert.equal(rows[5].value, "never")
})

// --- nits: pluralized counts ----------------------------------------------

test("pluralCount pluralizes 0, 1, 2 and keeps irregular forms", () => {
  assert.equal(Model.pluralCount(0, "item"), "0 items")
  assert.equal(Model.pluralCount(1, "item"), "1 item")
  assert.equal(Model.pluralCount(2, "item"), "2 items")
  assert.equal(Model.pluralCount(1, "person", "people"), "1 person")
  assert.equal(Model.pluralCount(2, "person", "people"), "2 people")
  assert.equal(Model.pluralUnit(0, "file"), "files")
  assert.equal(Model.pluralUnit(1, "file"), "file")
  assert.equal(Model.pluralUnit(2, "file"), "files")
  assert.equal(Model.pluralUnit(1, "person", "people"), "person")
  assert.equal(Model.pluralUnit(2, "person", "people"), "people")
  // The legacy leading-space helper keeps working unchanged.
  assert.equal(Model.plural(1, " change", " changes"), "1 change")
  assert.equal(Model.plural(3, " change", " changes"), "3 changes")
})

test("repoInfoRows pluralizes the stowed package count", () => {
  const one = Model.repoInfoRows({ path: "~/x", stowed_packages: 1 }, "0.1.0")
  assert.equal(one.find((r) => r.label === "Packages").value, "1 package")
  const many = Model.repoInfoRows({ path: "~/x", stowed_packages: 16 }, "0.1.0")
  assert.equal(many.find((r) => r.label === "Packages").value, "16 packages")
})

test("packageCards keeps a singular file unit at one", () => {
  const status = {
    repos: [{
      path: "~/.dotfiles", exists: true,
      packages: [
        { name: "fish", health: "ok", pending_links: [], conflicts: [], dangling: [] },
        { name: "nvim", health: "ok", pending_links: [], conflicts: [], dangling: [] }
      ],
      changes: [{ path: "fish/.config/fish/config.fish", package: "fish", kind: "modified" }],
      untracked: [{ path: "nvim/init.lua", package: "nvim" }]
    }],
    candidates: []
  }
  const cards = Model.packageCards(status)
  assert.equal(cards[0].count, 1)
  assert.equal(cards[0].unit, "file")
  assert.equal(Model.pluralCount(cards[0].count, cards[0].unit), "1 file")
  assert.equal(cards[1].count, 1)
  assert.equal(cards[1].unit, "file")
})

test("overviewGroups renders a single-item group with a singular unit", () => {
  const status = {
    repos: [{ path: "~/a", exists: true, changes: [{ path: "p/x", package: "p" }], untracked: [], packages: [] }],
    candidates: []
  }
  const outgoing = Model.overviewGroups(status).find((g) => g.key === "outgoing")
  assert.equal(outgoing.count, 1)
  assert.equal(outgoing.unit, "file")
  assert.ok(outgoing.subtitle.indexOf("1 item") !== -1, outgoing.subtitle)
})

test("changesGroups renders a single-change group with a singular unit and subtitle", () => {
  const status = {
    repos: [{ path: "~/.dotfiles", exists: true, changes: [{ path: "p/x", package: "p" }], untracked: [], packages: [] }],
    candidates: []
  }
  const repo = Model.changesGroups(status, {})[0]
  assert.equal(repo.count, 1)
  assert.equal(repo.unit, "file")
  assert.ok(repo.subtitle.indexOf("1 change") !== -1, repo.subtitle)
})

test("changesView carries the singular unit and subtitle the panel renders", () => {
  const status = {
    repos: [{ path: "~/.dotfiles", exists: true, changes: [{ path: "p/x", package: "p" }], untracked: [], packages: [] }],
    candidates: []
  }
  const group = Model.changesView(status, {}).groups[0]
  assert.equal(group.count, 1)
  assert.equal(group.unit, "file")
  assert.ok(group.subtitle.indexOf("1 change") !== -1, group.subtitle)
  // The per-package line the panel renders pluralizes too.
  assert.equal(Model.pluralCount(group.packages[0].count, "file"), "1 file")
})

// --- Unit 6: own visual identity view models ------------------------------

test("bridgeState: clean bridge has no chips, no badge and an accent line", () => {
  const bridge = Model.bridgeState(HERO.clean)
  assert.equal(bridge.leftLabel, "This PC")
  assert.equal(bridge.rightLabel, "GitHub")
  assert.equal(bridge.up, 0)
  assert.equal(bridge.down, 0)
  assert.equal(bridge.hasUp, false)
  assert.equal(bridge.hasDown, false)
  assert.equal(bridge.upText, "")
  assert.equal(bridge.downText, "")
  assert.equal(bridge.badge, 0)
  assert.equal(bridge.badgeText, "")
  assert.equal(bridge.hasChanges, false)
  assert.equal(bridge.lineTone, "accent")
})

test("bridgeState: to-upload shows an up chip in accent", () => {
  const bridge = Model.bridgeState(HERO.ahead)
  assert.equal(bridge.up, 2)
  assert.equal(bridge.hasUp, true)
  assert.equal(bridge.upText, "\u21912")
  assert.equal(bridge.hasDown, false)
  assert.equal(bridge.downText, "")
  assert.equal(bridge.lineTone, "accent")
})

test("bridgeState: updates show a down chip", () => {
  const bridge = Model.bridgeState(HERO.behind)
  assert.equal(bridge.down, 3)
  assert.equal(bridge.hasDown, true)
  assert.equal(bridge.downText, "\u21933")
  assert.equal(bridge.hasUp, false)
})

test("bridgeState: local changes put a count badge on the This PC node", () => {
  const bridge = Model.bridgeState(HERO.changes)
  assert.equal(bridge.badge, 3)
  assert.equal(bridge.badgeText, "3")
  assert.equal(bridge.hasChanges, true)
})

test("bridgeState: both flows at once keep both chips", () => {
  const bridge = Model.bridgeState({
    repos: [{ path: "~/a", ahead: 2, behind: 5, upstream: "origin/main", changes: [], untracked: [], packages: [] }],
    candidates: []
  })
  assert.equal(bridge.up, 2)
  assert.equal(bridge.down, 5)
  assert.equal(bridge.upText, "\u21912")
  assert.equal(bridge.downText, "\u21935")
})

test("bridgeState: attention turns the line urgent", () => {
  assert.equal(Model.bridgeState(HERO.conflict).lineTone, "urgent")
  assert.equal(Model.bridgeState(HERO.diverged).lineTone, "urgent")
})

test("bridgeState: a fresh machine draws a neutral line, not urgent", () => {
  const fresh = { repos: [{ path: "~/.dotfiles", exists: false, state: "missing" }, { path: "~/wallpapers", exists: false, state: "missing" }] }
  // Without the opt-in flag a missing repo is attention (urgent).
  assert.equal(Model.bridgeState(fresh).lineTone, "urgent")
  assert.equal(Model.bridgeState(fresh, { notSetUp: true }).lineTone, "neutral")
})

test("bridgeState: badge caps at 99+ and tolerates missing data", () => {
  const big = Model.bridgeState({
    repos: [{ path: "~/a", changes: new Array(150).fill({ path: "x" }), untracked: [], packages: [] }],
    candidates: []
  })
  assert.equal(big.badge, 150)
  assert.equal(big.badgeText, "99+")
  const empty = Model.bridgeState(null)
  assert.equal(empty.up, 0)
  assert.equal(empty.badge, 0)
  assert.equal(empty.lineTone, "accent")
})

test("repoLaneSummary: collapsed lane carries name, branch, hash, time and count", () => {
  const lane = Model.repoLaneSummary({
    path: "~/.dotfiles", branch: "main", head: "abcdef1234567",
    stowed_packages: 16, head_time: "2026-10-09T15:00:00-05:00", state: "clean"
  }, "2026-10-09T18:00:00-05:00")
  assert.equal(lane.name, "dotfiles")
  assert.equal(lane.branch, "main")
  assert.equal(lane.branchChip, "main")
  assert.equal(lane.shortHash, "abcdef1")
  assert.equal(lane.timeText, "3h ago")
  assert.equal(lane.countText, "16 pkgs")
  assert.equal(lane.count, 16)
  assert.equal(lane.stripeTone, "accent")
  assert.equal(lane.stripeAlpha, 0.5)
})

test("repoLaneSummary: pending work brightens the accent stripe", () => {
  const dirty = Model.repoLaneSummary({ path: "~/.dotfiles", branch: "main", state: "dirty", changes: [{ path: "a" }], untracked: [], packages: [] })
  assert.equal(dirty.stripeTone, "accent")
  assert.equal(dirty.stripeAlpha, 1)
  const pending = Model.repoLaneSummary({ path: "~/r", state: "clean", changes: [], untracked: [], packages: [{ name: "p", health: "pending" }] })
  assert.equal(pending.stripeTone, "accent")
  assert.equal(pending.stripeAlpha, 1)
})

test("repoLaneSummary: attention states use the urgent stripe", () => {
  assert.equal(Model.repoLaneSummary({ path: "~/r", state: "diverged", packages: [] }).stripeTone, "urgent")
  assert.equal(Model.repoLaneSummary({ path: "~/r", state: "clean", packages: [{ name: "p", health: "conflicts" }] }).stripeTone, "urgent")
  assert.equal(Model.repoLaneSummary({ path: "~/gone", exists: false, state: "missing", packages: [] }).stripeTone, "urgent")
})

test("repoLaneSummary: singular count, short hash and empty data", () => {
  const one = Model.repoLaneSummary({ path: "~/r", branch: "main", head: "abc", stowed_packages: 1 })
  assert.equal(one.countText, "1 pkg")
  assert.equal(one.shortHash, "abc")
  assert.equal(one.branchChip, "main")
  const detached = Model.repoLaneSummary({ path: "~/r", branch: "", packages: [] })
  assert.equal(detached.branchChip, "")
  const empty = Model.repoLaneSummary(null)
  assert.equal(empty.name, "")
  assert.equal(empty.countText, "0 pkgs")
})

test("packageChipState: ok, changed and needs-fixing tones", () => {
  same(Model.packageChipState({ health: "ok", count: 0 }), { tone: "ok", fillAlpha: 0.06, outline: false, outlineTone: "" })
  same(Model.packageChipState({ health: "ok", count: 2 }), { tone: "changed", fillAlpha: 0.06, outline: true, outlineTone: "accent" })
  same(Model.packageChipState({ health: "pending", count: 0 }), { tone: "fixing", fillAlpha: 0.06, outline: true, outlineTone: "urgent" })
  same(Model.packageChipState({ health: "conflicts", count: 0 }), { tone: "fixing", fillAlpha: 0.06, outline: true, outlineTone: "urgent" })
  same(Model.packageChipState(null), { tone: "ok", fillAlpha: 0.06, outline: false, outlineTone: "" })
})

test("packageCards exposes health so the chip grid can colour it", () => {
  const status = {
    repos: [{
      path: "~/r", exists: true, changes: [], untracked: [],
      packages: [{ name: "a", health: "ok", pending_links: [], conflicts: [], dangling: [] }]
    }],
    candidates: []
  }
  assert.equal(Model.packageCards(status)[0].health, "ok")
})

test("tweenValue eases out cubic and clamps", () => {  assert.equal(Model.tweenValue(0, 100, 0), 0)
  assert.equal(Model.tweenValue(0, 100, 1), 100)
  assert.equal(Model.tweenValue(0, 100, 0.5), Math.round(100 * (1 - Math.pow(0.5, 3))))
  assert.equal(Model.tweenValue(0, 100, -0.5), 0)
  assert.equal(Model.tweenValue(0, 100, 1.5), 100)
  assert.equal(Model.tweenValue(100, 0, 0), 100)
  assert.equal(Model.tweenValue(100, 0, 1), 0)
  assert.equal(Model.tweenValue(0, 50, Number.NaN), 0)
  assert.equal(Model.tweenValue(0, 100, "0.5"), Math.round(100 * (1 - Math.pow(0.5, 3))))
})

test("firstNewCandidate prefers an unknown candidate and falls back", () => {
  const unknown = { path: "~/.config/x", known: false }
  const known = { path: "~/.config/y", known: true }
  assert.equal(Model.firstNewCandidate([known, unknown]), unknown)
  assert.equal(Model.firstNewCandidate([known]), known)
  assert.equal(Model.firstNewCandidate([]), null)
  assert.equal(Model.firstNewCandidate(null), null)
  // A null entry is skipped, not returned.
  assert.equal(Model.firstNewCandidate([null, known]), known)
})

test("shortRemote trims scheme, host and .git for the lane chip", () => {
  assert.equal(Model.shortRemote("https://github.com/pwn27sbx/dotfiles.git"), "pwn27sbx/dotfiles")
  assert.equal(Model.shortRemote("git@github.com:pwn27sbx/dotfiles.git"), "pwn27sbx/dotfiles")
  assert.equal(Model.shortRemote("https://github.com/u/r"), "u/r")
  assert.equal(Model.shortRemote("ssh://git@host.example.com:22/team/repo.git"), "team/repo")
  assert.equal(Model.shortRemote(""), "")
  assert.equal(Model.shortRemote(null), "")
  assert.equal(Model.shortRemote("single"), "single")
})

// --- Unit 7: bar icon overlays -------------------------------------------

function iconRepo(state, extra) {
  return Object.assign({ exists: true, path: "~/.dotfiles", state: state, packages: [] }, extra || {})
}

test("barIconState: clean has no overlay and no chevrons", () => {
  same(Model.barIconState({ repos: [iconRepo("clean")], candidates: [] }), { dot: "none", up: false, down: false })
  same(Model.barIconState(null), { dot: "none", up: false, down: false })
  same(Model.barIconState({}), { dot: "none", up: false, down: false })
})

test("barIconState: changes or new configs give an accent dot", () => {
  const withChange = { repos: [iconRepo("dirty", { changes: [{ path: "fish/x", package: "fish" }] })], candidates: [] }
  assert.equal(Model.barIconState(withChange).dot, "accent")
  const withNew = { repos: [iconRepo("clean")], candidates: [{ path: "~/.config/x", known: false }] }
  assert.equal(Model.barIconState(withNew).dot, "accent")
})

test("barIconState: attention wins with an urgent dot", () => {
  assert.equal(Model.barIconState({ repos: [iconRepo("diverged")], candidates: [] }).dot, "urgent")
  assert.equal(Model.barIconState({ repos: [iconRepo("operation", { operation: "rebase" })], candidates: [] }).dot, "urgent")
  assert.equal(Model.barIconState({ repos: [iconRepo("clean", { packages: [{ name: "fish", health: "conflicts" }] })], candidates: [] }).dot, "urgent")
  // urgent beats accent even with pending changes
  assert.equal(Model.barIconState({ repos: [iconRepo("diverged", { changes: [{ path: "a", package: "a" }] })], candidates: [] }).dot, "urgent")
  // a secret-scan block forces the urgent dot
  assert.equal(Model.barIconState({ repos: [iconRepo("clean")], candidates: [] }, { blocked: true }).dot, "urgent")
})

test("barIconState: ahead/behind give the up/down chevrons", () => {
  same(Model.barIconState({ repos: [iconRepo("ahead", { ahead: 2 })], candidates: [] }), { dot: "none", up: true, down: false })
  same(Model.barIconState({ repos: [iconRepo("behind", { behind: 3 })], candidates: [] }), { dot: "none", up: false, down: true })
  same(Model.barIconState({ repos: [iconRepo("diverged", { ahead: 1, behind: 1 })], candidates: [] }), { dot: "urgent", up: true, down: true })
})

test("barIconGlyph: folder-sync idle, autorenew busy", () => {
  assert.equal(Model.barIconGlyph(false), "\u{F0D0B}")
  assert.equal(Model.barIconGlyph(true), "\u{F006A}")
  assert.equal(Model.barIconGlyph(undefined), "\u{F0D0B}")
})

test("bar glyphs are single supplementary-plane code points (no 4-digit escape split)", () => {
  for (const g of [Model.barIconGlyph(false), Model.barIconGlyph(true),
                   Model.barArrowGlyph({ up: true }), Model.barArrowGlyph({ down: true })]) {
    assert.equal(Array.from(g).length, 1)
    assert.ok(g.codePointAt(0) >= 0xF0000)
  }
  assert.equal(Model.barIconGlyph(false).codePointAt(0), 0xF0D0B)
})

test("barArrowGlyph: up wins, then down, else nothing", () => {
  assert.equal(Model.barArrowGlyph({ up: true, down: false }), "\u{F005D}")
  assert.equal(Model.barArrowGlyph({ up: false, down: true }), "\u{F0045}")
  assert.equal(Model.barArrowGlyph({ up: true, down: true }), "\u{F005D}")
  assert.equal(Model.barArrowGlyph({ up: false, down: false }), "")
  assert.equal(Model.barArrowGlyph(null), "")
})

// --- Unit 8b: "Set up this machine" view model ---------------------------

function setupPlan(overrides) {
  return Object.assign({
    version: 1,
    clone: [],
    link: [],
    services: [],
    requires: [],
    post: [],
    notes: [],
    summary: {}
  }, overrides || {})
}

test("setupVisible: only when machineSetup is truthy", () => {
  assert.equal(Model.setupVisible(null, null), false)
  assert.equal(Model.setupVisible({}, null), false)
  assert.equal(Model.setupVisible({ machineSetup: false }, null), false)
  assert.equal(Model.setupVisible({ machineSetup: "false" }, null), false)
  assert.equal(Model.setupVisible({ machineSetup: true }, null), true)
  assert.equal(Model.setupVisible({ machineSetup: "true" }, null), true)
})

test("anyRepoMissing: true when a configured repo is absent", () => {
  assert.equal(Model.anyRepoMissing(null), false)
  assert.equal(Model.anyRepoMissing({ repos: [] }), false)
  assert.equal(Model.anyRepoMissing({ repos: [{ exists: true }, { exists: true }] }), false)
  assert.equal(Model.anyRepoMissing({ repos: [{ exists: true }, { exists: false }] }), true)
})

test("allReposMissing: true only when every repo is absent", () => {
  assert.equal(Model.allReposMissing(null), false)
  assert.equal(Model.allReposMissing({ repos: [] }), false)
  assert.equal(Model.allReposMissing({ repos: [{ exists: true }] }), false)
  assert.equal(Model.allReposMissing({ repos: [{ exists: false }, { exists: true }] }), false)
  assert.equal(Model.allReposMissing({ repos: [{ exists: false }, { exists: false }] }), true)
})

test("heroState: a fresh machine with machineSetup on is not the publish state", () => {
  const status = {
    repos: [
      { path: "~/.dotfiles", exists: false, state: "missing" },
      { path: "~/wallpapers", exists: false, state: "missing" }
    ]
  }
  const hero = Model.heroState(status, "12:00", { machineSetup: true })
  assert.equal(hero.title, "This machine is not set up yet")
  assert.equal(hero.hint, "Use Set up to download and link everything")
  // Without the opt-in switch, a missing repo is still the attention state.
  assert.equal(Model.heroState(status, "12:00").title, "Needs your attention")
  // One missing repo of two is not "not set up".
  const partial = { repos: [{ exists: false, state: "missing" }, { path: "~/wallpapers", exists: true }] }
  assert.notEqual(Model.heroState(partial, "12:00", { machineSetup: true }).title, "This machine is not set up yet")
})

test("explain: a fresh machine points to Set up", () => {
  const status = { repos: [{ path: "~/.dotfiles", exists: false, state: "missing" }] }
  assert.ok(Model.explain(status, { machineSetup: true }).indexOf("not set up") !== -1)
  assert.ok(Model.explain(status).indexOf("attention") !== -1)
})

test("repoLaneSummary: neutral stripe on a fresh machine", () => {
  const lane = Model.repoLaneSummary({ path: "~/.dotfiles", state: "missing" }, "12:00", { neutral: true })
  assert.equal(lane.stripeTone, "neutral")
  assert.equal(Model.repoLaneSummary({ path: "~/.dotfiles", state: "missing" }, "12:00").stripeTone, "urgent")
})

test("setupPrefillUrl: uses the dotfiles remote when present", () => {
  assert.equal(Model.setupPrefillUrl(null), "")
  assert.equal(Model.setupPrefillUrl({ repos: [{ path: "~/.dotfiles", remote_url: "" }] }), "")
  assert.equal(Model.setupPrefillUrl({ repos: [{ path: "~/.dotfiles", remote_url: "git@github.com:me/dotfiles.git" }] }), "git@github.com:me/dotfiles.git")
  assert.equal(Model.setupPrefillUrl({ repos: [{ path: "~/wallpapers", remote_url: "x" }] }), "")
})

test("setupConnectRows: waiting/cloning/cloned/ready/error checklist", () => {
  same(Model.setupConnectRows(null), [])
  const rows = Model.setupConnectRows([
    { path: "~/.dotfiles", state: "cloned" },
    { path: "~/wallpapers", state: "cloning" },
    { path: "~/third", state: "waiting" },
    { path: "~/bad", state: "error", error: "The wallpapers repo is private." },
    { path: "~/auth", state: "error", error: "GitHub login is needed.", authError: true }
  ])
  same(rows.map(function(r) { return r.status }), ["done", "running", "waiting", "failed", "failed"])
  assert.equal(rows[0].detail, "Cloned")
  assert.equal(rows[1].detail, "Cloning\u2026")
  assert.equal(rows[3].detail, "The wallpapers repo is private.")
  assert.equal(rows[3].tone, "urgent")
  assert.equal(rows[3].authError, false)
  assert.equal(rows[4].authError, true)
})

test("setupValidUrl: github URL or a .git suffix", () => {
  assert.equal(Model.setupValidUrl(""), false)
  assert.equal(Model.setupValidUrl("   "), false)
  assert.equal(Model.setupValidUrl("not a url"), false)
  assert.equal(Model.setupValidUrl("https://github.com/me/dotfiles.git"), true)
  assert.equal(Model.setupValidUrl("https://github.com/me/dotfiles"), true)
  assert.equal(Model.setupValidUrl("git@github.com:me/dotfiles.git"), true)
  assert.equal(Model.setupValidUrl("/tmp/whatever.git"), true)
})

test("setupPrereqRows: labelled checks with fixes", () => {
  same(Model.setupPrereqRows(null), [])
  const rows = Model.setupPrereqRows({
    ok: true, needs_gh: true, ok_to_connect: false,
    checks: [
      { id: "stow", ok: true, detail: "found at /usr/bin/stow", fix: "omarchy pkg add stow" },
      { id: "git", ok: false, detail: "git is not installed", fix: "omarchy pkg add git" },
      { id: "pacman-db", ok: false, detail: "No pacman sync database", fix: "omarchy update" },
      { id: "gh", ok: true, detail: "found", fix: "omarchy pkg add github-cli" },
      { id: "gh-auth", ok: false, detail: "not logged in", fix: "gh auth login, then gh auth setup-git" }
    ]
  })
  const byId = {}
  rows.forEach(function(r) { byId[r.id] = r })
  assert.equal(byId.stow.label, "GNU Stow")
  assert.equal(byId.git.label, "Git")
  assert.equal(byId.git.tone, "urgent")
  assert.equal(byId["pacman-db"].label, "Package database")
  assert.equal(byId.gh.label, "GitHub CLI")
  assert.equal(byId["gh-auth"].label, "GitHub login")
  assert.equal(byId["gh-auth"].fix, "gh auth login, then gh auth setup-git")
})

test("setupLoginDetail: the GitHub login row detail, or empty", () => {
  assert.equal(Model.setupLoginDetail(null), "")
  assert.equal(Model.setupLoginDetail({ checks: [] }), "")
  assert.equal(Model.setupLoginDetail({
    checks: [
      { id: "gh", ok: true, detail: "found" },
      { id: "gh-auth", ok: true, detail: "signed in as me" }
    ]
  }), "signed in as me")
  assert.equal(Model.setupLoginDetail({
    checks: [{ id: "gh-auth", ok: false, detail: "not signed in" }]
  }), "not signed in")
})

test("setupAuthFix: needs gh auth when a connect entry failed on auth", () => {
  assert.equal(Model.setupAuthFix(null), null)
  assert.equal(Model.setupAuthFix([]), null)
  assert.equal(Model.setupAuthFix([{ path: "~/.dotfiles", state: "error" }]), null)
  assert.equal(Model.setupAuthFix([{ path: "~/.dotfiles", state: "ready" }]), null)
  const fix = Model.setupAuthFix([
    { path: "~/.dotfiles", state: "error", authError: true, error: "GitHub login is needed to clone dotfiles." }
  ])
  assert.equal(fix.command, "gh auth login, then gh auth setup-git")
  assert.ok(fix.detail.indexOf("GitHub login") !== -1)
  const commandFix = Model.setupAuthFix([], true)
  assert.equal(commandFix.command, "gh auth login, then gh auth setup-git")
})

test("setupCandidateRows: groups by tier, stars definitive and likely", () => {
  same(Model.setupCandidateRows(null), { definitive: [], likely: [], others: [] })
  const groups = Model.setupCandidateRows({
    definitive: [{ name: "dotfiles", url: "u1", private: false, detail: "setup recipe", hint: true }],
    likely: [{ name: "myconf", url: "u2", private: true, detail: "stow-like", hint: false }],
    others: [{ name: "portfolio", url: "u3", private: false, detail: "", hint: false }]
  })
  assert.equal(groups.definitive[0].value, "u1")
  assert.equal(groups.definitive[0].likely, true)
  assert.equal(groups.definitive[0].tier, "definitive")
  assert.equal(groups.definitive[0].sentence, "Has a Stow Sync recipe")
  assert.equal(groups.likely[0].sentence, "Looks like a dotfiles repo")
  assert.equal(groups.likely[0].detail, "stow-like \u00b7 private")
  assert.equal(groups.likely[0].likely, true)
  assert.equal(groups.likely[0].badges.indexOf("private") !== -1, true)
  assert.equal(groups.definitive[0].badges.indexOf("recipe") !== -1, true)
  assert.equal(groups.others[0].value, "u3")
  assert.equal(groups.others[0].likely, false)
  assert.equal(groups.others[0].tier, "other")
  assert.equal(groups.others[0].sentence, "")
})

test("setupCandidateFirstUrl: first definitive repo fills the URL", () => {
  assert.equal(Model.setupCandidateFirstUrl(null), "")
  assert.equal(Model.setupCandidateFirstUrl({ definitive: [] }), "")
  assert.equal(Model.setupCandidateFirstUrl({ definitive: [{ url: "u1" }] }), "u1")
})

test("setupFilterRows: case-insensitive match on label and url", () => {
  const rows = [
    { label: "myconf", value: "https://github.com/me/myconf" },
    { label: "notes", value: "https://github.com/me/notes" }
  ]
  assert.equal(Model.setupFilterRows(rows, "").length, 2)
  assert.equal(Model.setupFilterRows(rows, "conf").length, 1)
  assert.equal(Model.setupFilterRows(rows, "NOTES")[0].label, "notes")
  assert.equal(Model.setupFilterRows(rows, "github.com/me").length, 2)
  assert.equal(Model.setupFilterRows(rows, "zzz").length, 0)
})

test("setupSelectedPostIds: defaults, overrides and explicit off", () => {
  const plan = { post: [
    { id: "a", default: true },
    { id: "b", default: false },
    { id: "c", default: true }
  ] }
  same(Model.setupSelectedPostIds(plan, {}), ["a", "c"])
  same(Model.setupSelectedPostIds(plan, { b: true }), ["a", "b", "c"])
  same(Model.setupSelectedPostIds(plan, { a: false }), ["c"])
  same(Model.setupSelectedPostIds(null, null), [])
})

test("setupPrereqReady: only when ok_to_connect", () => {
  assert.equal(Model.setupPrereqReady(null), false)
  assert.equal(Model.setupPrereqReady({ ok: true, ok_to_connect: true }), true)
  assert.equal(Model.setupPrereqReady({ ok: true, ok_to_connect: false }), false)
  assert.equal(Model.setupPrereqReady({ ok: false }), false)
})

test("setupPlanGroups: full plan produces every ordered group", () => {
  const plan = setupPlan({
    clone: [{ path: "~/wallpapers", private: true }],
    link: [
      { repo: "~/.dotfiles", package: "fish", status: "conflicts", links: [], files_to_backup: 1, conflicts: [{ target: "~/.config/fish/config.fish", kind: "identical" }] },
      { repo: "~/.dotfiles", package: "ghostty", status: "conflicts", links: [], files_to_backup: 1, conflicts: [{ target: "~/.config/ghostty/config", kind: "different" }] },
      { repo: "~/wallpapers", package: "walls", status: "new", links: [{ target: "~/.config/walls/w.png" }], files_to_backup: 0, conflicts: [] },
      { repo: "~/.dotfiles", package: "omarchy", status: "already", links: [], files_to_backup: 0, conflicts: [] },
      { repo: "~/.dotfiles", package: "app", status: "blocked", links: [], files_to_backup: 0, conflicts: [{ target: "~/.config/app/conf", kind: "blocked", reason: "target is a symlink not owned by stow" }] }
    ],
    requires: [{ name: "git", found: true }, { name: "gowall", found: false }],
    post: [
      { id: "wallpaper-tint", label: "Recolor wallpapers", default: true, available: true, missing: [], timeout_s: 900 },
      { id: "zen-sync", label: "Link Zen", default: false, available: false, missing: ["gowall"], timeout_s: 120 }
    ],
    notes: ["Restore ~/.config/hypr with config-sync."]
  })
  const groups = Model.setupPlanGroups(plan)
  same(groups.map(function(g) { return g.key }), ["download", "link", "backup", "skipped", "missing", "after", "notes"])
  const byKey = {}
  groups.forEach(function(g) { byKey[g.key] = g })
  assert.equal(byKey.download.title, "Will download")
  assert.equal(byKey.download.items[0].label, "~/wallpapers")
  assert.equal(byKey.link.count, 3)
  assert.equal(byKey.backup.items.length, 2)
  // Backup files are grouped by package; the meaning is stated once per package
  // and only bare file names are listed under it (finding 69).
  assert.equal(byKey.backup.items[0].label, "fish")
  assert.equal(byKey.backup.items[0].detail, "1 file \u00b7 1 same as yours")
  same(byKey.backup.items[0].sub, ["config.fish"])
  assert.equal(byKey.backup.items[1].detail, "1 file \u00b7 1 saved to backup")
  same(byKey.backup.items[1].sub, ["config"])
  assert.equal(byKey.skipped.tone, "urgent")
  assert.equal(byKey.skipped.items[0].label, "~/.dotfiles · app")
  assert.equal(byKey.missing.items[0].label, "gowall")
  assert.equal(byKey.missing.expandByDefault, true)
  assert.equal(byKey.notes.expandByDefault, true)
  assert.equal(byKey.after.expandByDefault, false)
  assert.equal(byKey.after.items[0].label, "Recolor wallpapers")
  assert.equal(byKey.after.items[0].default, true)
  assert.equal(byKey.after.items[0].available, true)
  assert.equal(byKey.after.items[1].available, false)
  assert.equal(byKey.after.items[1].detail, "needs gowall")
  assert.equal(byKey.notes.items[0].label, "Restore ~/.config/hypr with config-sync.")
  same(Model.setupPlanGroups(setupPlan({})), [])
  same(Model.setupPlanGroups(null), [])
})

test("setupPlanGroups: units are singular at count 1", () => {
  const plan = setupPlan({
    clone: [{ path: "~/wallpapers", private: true }],
    link: [
      { repo: "~/.dotfiles", package: "fish", status: "new", links: [{ target: "x" }], files_to_backup: 1, conflicts: [{ target: "~/.config/fish/config.fish", kind: "different" }] },
      { repo: "~/.dotfiles", package: "app", status: "blocked", links: [], conflicts: [{ kind: "blocked", reason: "x" }], files_to_backup: 0 }
    ],
    requires: [{ name: "gowall", found: false }],
    post: [{ id: "p", label: "P", default: true, available: true, missing: [], timeout_s: 1 }],
    notes: []
  })
  const byKey = {}
  Model.setupPlanGroups(plan).forEach(function(g) { byKey[g.key] = g })
  assert.equal(byKey.download.unit, "repository")
  assert.equal(byKey.link.unit, "package")
  assert.equal(byKey.backup.unit, "file")
  assert.equal(byKey.skipped.unit, "package")
  assert.equal(byKey.missing.unit, "tool")
  assert.equal(byKey.after.unit, "step")
})

test("setupBackupsRows: singular counts read cleanly", () => {
  const rows = Model.setupBackupsRows([{ id: "x", created: "d", undone: false, counts: { packages: 1, moved: 1, services: 1 } }])
  assert.equal(rows[0].detail, "1 package \u00b7 1 file \u00b7 1 service")
})

test("setupPrimaryLabel: names exactly what will happen", () => {
  const p = function(link, backup, clone) {
    return setupPlan({ clone: Array(clone || 0).fill({ path: "~/x" }), link: link, requires: [], post: [], notes: [] })
  }
  const links = function(n, files) {
    const out = []
    for (let i = 0; i < n; i++) out.push({ repo: "~/.dotfiles", package: "p" + i, status: "new", links: [], conflicts: [], files_to_backup: i === 0 ? files : 0 })
    return out
  }
  assert.equal(Model.setupPrimaryLabel(p(links(2, 6), 6, 0)), "Set up · link 2 packages, back up 6 files")
  assert.equal(Model.setupPrimaryLabel(p(links(1, 1), 1, 0)), "Set up · link 1 package, back up 1 file")
  assert.equal(Model.setupPrimaryLabel(p([], 0, 2)), "Set up · download 2 repositories")
  assert.equal(Model.setupPrimaryLabel(p(links(3, 0), 0, 1)), "Set up · download 1 repository, link 3 packages")
  assert.equal(Model.setupPrimaryLabel(setupPlan({})), "Nothing to set up")
  const blocked = setupPlan({ link: [{ repo: "~/.dotfiles", package: "app", status: "blocked", links: [], conflicts: [{ kind: "blocked", reason: "x" }], files_to_backup: 0 }] })
  assert.equal(Model.setupPrimaryLabel(blocked), "Set up · review 1 blocked package")
})

test("setupStepState: done/failed/skipped from the rich apply result", () => {
  same(Model.setupStepState(null), [])
  const rows = Model.setupStepState({
    packages: [
      { repo: "~/.dotfiles", package: "fish", state: "applied" },
      { repo: "~/.dotfiles", package: "ghostty", state: "failed" },
      { repo: "~/.dotfiles", package: "app", state: "blocked" }
    ],
    services: [{ unit: "ai-tools-check.timer", state: "enabled" }],
    post: [
      { id: "wallpaper-tint", state: "ran", exit: 0, last_line: "recolored" },
      { id: "zen-sync", state: "skipped", reason: "needs gowall" },
      { id: "boom", state: "failed", exit: 1, last_line: "kaboom" }
    ]
  })
  const byLabel = {}
  rows.forEach(function(r) { byLabel[r.label] = r })
  assert.equal(byLabel["~/.dotfiles · fish"].status, "done")
  assert.equal(byLabel["~/.dotfiles · ghostty"].status, "failed")
  assert.equal(byLabel["~/.dotfiles · app"].status, "failed")
  assert.equal(byLabel["ai-tools-check.timer"].status, "done")
  assert.equal(byLabel["wallpaper-tint"].status, "done")
  assert.equal(byLabel["wallpaper-tint"].detail, "recolored")
  assert.equal(byLabel["zen-sync"].status, "skipped")
  assert.equal(byLabel["zen-sync"].detail, "needs gowall")
  assert.equal(byLabel["boom"].status, "failed")
  assert.equal(byLabel["boom"].detail, "kaboom")
})

test("setupReport: grouped sections, counts and collapse defaults", () => {
  same(Model.setupReport(null).sections, [])
  const report = Model.setupReport({
    ok: true,
    backup: "20261010T043006Z",
    backup_dir: "/home/u/.local/state/stow-sync/setup-backups/20261010T043006Z",
    packages: [{ repo: "~/.dotfiles", package: "fish", state: "applied" }],
    applied: [{ repo: "~/.dotfiles", package: "fish" }],
    moved: [{ path: "~/.config/fish/config.fish", backup: "/b/files/.config/fish/config.fish" }],
    services: [{ unit: "ai-tools-check.timer", state: "enabled" }],
    post: [
      { id: "wallpaper-tint", state: "ran", exit: 0, last_line: "recolored" },
      { id: "zen-sync", state: "skipped", reason: "needs gowall" }
    ],
    notes: ["Restore hypr with config-sync."]
  })
  assert.equal(report.backup, "20261010T043006Z")
  assert.equal(report.backupDir, "/home/u/.local/state/stow-sync/setup-backups/20261010T043006Z")
  assert.equal(report.linked, 1)
  assert.equal(report.moved, 1)
  const keys = report.sections.map(function(s) { return s.key })
  assert.ok(keys.indexOf("moved") !== -1)
  assert.ok(keys.indexOf("notes") !== -1)
  const byKey = {}
  report.sections.forEach(function(s) { byKey[s.key] = s })
  // Packages and Moved collapse by default; Services, Steps and notes do not.
  assert.equal(byKey.packages.expandByDefault, false)
  assert.equal(byKey.packages.count, 1)
  assert.equal(byKey.moved.expandByDefault, false)
  assert.equal(byKey.services.expandByDefault, true)
  assert.equal(byKey.steps.expandByDefault, true)
  assert.equal(byKey.notes.expandByDefault, true)
  assert.equal(byKey.steps.count, 2)
  assert.equal(byKey.steps.items[0].state, "ran")
  assert.equal(byKey.steps.items[0].sub, "recolored")
  assert.equal(byKey.steps.items[1].state, "skipped: needs gowall \u2014 then run Set up again")
})

test("setupReport: every post step is listed with ran/skipped/not selected", () => {
  const report = Model.setupReport(
    { ok: true, post: [{ id: "mise", state: "ran", last_line: "installed 6 tools" }] },
    { post: [
      { id: "mise", label: "Install tools", default: true },
      { id: "wallpaper-tint", label: "Recolor wallpapers", default: true },
      { id: "zen-sync", label: "Link Zen", default: false }
    ] }
  )
  const steps = report.sections.filter(function(s) { return s.key === "steps" })[0]
  same(steps.items.map(function(i) { return [i.label, i.state] }), [
    ["Install tools", "ran"],
    ["Recolor wallpapers", "not selected"],
    ["Link Zen", "not selected"]
  ])
  assert.equal(steps.items[0].sub, "installed 6 tools")
  // A result-only step (no plan) still appears, labelled by its id.
  const solo = Model.setupReport({ ok: true, post: [{ id: "extra", state: "ran" }] }, { post: [] })
  assert.equal(solo.sections.filter(function(s) { return s.key === "steps" })[0].items[0].label, "extra")
})

test("setupProgressPath: points at the progress file, not the state dir", () => {
  assert.equal(Model.setupProgressPath("/state"), "/state/setup-progress.json")
  assert.equal(Model.setupProgressPath("/state/"), "/state/setup-progress.json")
  assert.equal(Model.setupProgressPath(""), "")
  assert.equal(Model.setupProgressPath(null), "")
})

test("setupReport: an unavailable step reads skipped, never not-selected", () => {
  const report = Model.setupReport(
    { ok: true, post: [] },
    { post: [
      { id: "wallpaper-tint", label: "Recolor wallpapers", available: false, missing: ["gowall"] },
      { id: "zen-sync", label: "Link Zen", available: true, missing: [] }
    ] }
  )
  const steps = report.sections.filter(function(s) { return s.key === "steps" })[0]
  same(steps.items.map(function(i) { return [i.label, i.state] }), [
    ["Recolor wallpapers", "skipped: needs gowall \u2014 then run Set up again"],
    ["Link Zen", "not selected"]
  ])
})

test("setupReport: undone marks every section undone", () => {
  const report = Model.setupReport(
    { ok: true, services: [{ unit: "t.timer", state: "enabled" }], post: [{ id: "a", state: "ran" }] },
    { post: [{ id: "a", label: "A" }] },
    true
  )
  assert.ok(report.sections.length > 0)
  assert.ok(report.sections.every(function(s) { return s.undone === true }))
  const live = Model.setupReport({ ok: true, services: [{ unit: "t.timer", state: "enabled" }] })
  assert.ok(live.sections.every(function(s) { return s.undone !== true }))
})

test("setupReport: notes stay live and a service reads disabled after Undo", () => {
  const report = Model.setupReport(
    { ok: true, services: [{ unit: "t.timer", state: "enabled" }], notes: ["a note"] },
    { post: [] },
    true
  )
  const byKey = {}
  report.sections.forEach(function(s) { byKey[s.key] = s })
  // Notes are not undone, only the setup sections are (finding 74).
  assert.equal(byKey.notes.undone, false)
  assert.equal(byKey.services.undone, true)
  // The greyed timer row shows the post-undo state, not stale "enabled" (finding 74).
  assert.equal(byKey.services.items[0].detail, "disabled")
  assert.equal(byKey.services.items[0].tone, "muted")
})

test("overviewState: a not-set-up machine shows only the setup card", () => {
  const fresh = Model.overviewState({ repos: [] }, { notSetUp: true })
  assert.equal(fresh.notSetUp, true)
  assert.equal(fresh.showSetupCard, true)
  assert.equal(fresh.showManagement, false)
  assert.equal(fresh.showUpdateHint, false)
  // A behind repo only adds a one-line hint while not set up (finding 76).
  const behind = Model.overviewState({ repos: [{ path: "~/.dotfiles", behind: 2 }] }, { notSetUp: true })
  assert.equal(behind.showUpdateHint, true)
  assert.equal(behind.updateHint, "Updates available on GitHub")
  // A normal machine keeps the management UI.
  const normal = Model.overviewState({ repos: [{ path: "~/.dotfiles", behind: 0 }] }, {})
  assert.equal(normal.showSetupCard, false)
  assert.equal(normal.showManagement, true)
  // setupNeeded alone forces the setup card without hiding management.
  const needed = Model.overviewState({ repos: [] }, { setupNeeded: true })
  assert.equal(needed.showSetupCard, true)
  assert.equal(needed.showManagement, true)
})

test("setupUndoneFromBackups: true only when the newest backup is undone", () => {
  assert.equal(Model.setupUndoneFromBackups(null), false)
  assert.equal(Model.setupUndoneFromBackups([]), false)
  assert.equal(Model.setupUndoneFromBackups([{ id: "1", undone: true }]), true)
  // Backups are oldest-first: a newer non-undone backup means the machine is set up.
  assert.equal(Model.setupUndoneFromBackups([{ id: "1", undone: true }, { id: "2", undone: false }]), false)
  assert.equal(Model.setupUndoneFromBackups([{ id: "1", undone: false }, { id: "2", undone: true }]), true)
})

// --- Unit 12c: approved redesign helpers ---------------------------------

test("setupWizardStepState: done / current / next for the stepper", () => {
  assert.equal(Model.setupWizardStepState(0, 2), "done")
  assert.equal(Model.setupWizardStepState(2, 2), "current")
  assert.equal(Model.setupWizardStepState(3, 2), "next")
  assert.equal(Model.setupWizardStepState(0, 0), "current")
})

test("setupSizeLabel: real decimal byte estimates only, never invented", () => {
  assert.equal(Model.setupSizeLabel(0), "")
  assert.equal(Model.setupSizeLabel(-5), "")
  assert.equal(Model.setupSizeLabel(3e6), "3 MB")
  assert.equal(Model.setupSizeLabel(1e9), "~1 GB")
  assert.equal(Model.setupSizeLabel(500e3), "500 KB")
})

test("parseSizeBytes: git binary units and decimal units to bytes", () => {
  assert.equal(Model.parseSizeBytes(""), 0)
  assert.equal(Model.parseSizeBytes("garbage"), 0)
  assert.equal(Model.parseSizeBytes("410.20 MiB"), Math.round(410.2 * 1024 * 1024))
  assert.equal(Model.parseSizeBytes("944.81 KiB"), Math.round(944.81 * 1024))
  assert.equal(Model.parseSizeBytes("1.2 GiB"), Math.round(1.2 * 1024 * 1024 * 1024))
  assert.equal(Model.parseSizeBytes("34 MB"), 34 * 1000 * 1000)
  assert.equal(Model.parseSizeBytes("955 GB"), 955 * 1000 * 1000 * 1000)
})

test("formatBytesDecimal: one decimal unit system for every size", () => {
  assert.equal(Model.formatBytesDecimal(0), "")
  assert.equal(Model.formatBytesDecimal(-1), "")
  // git's binary "410.20 MiB" renders as one decimal number (finding 66).
  assert.equal(Model.formatBytesDecimal(Model.parseSizeBytes("410.20 MiB")), "430 MB")
  assert.equal(Model.formatBytesDecimal(34 * 1000 * 1000), "34 MB")
  assert.equal(Model.formatBytesDecimal(1.2e9), "1.2 GB")
  assert.equal(Model.formatBytesDecimal(500 * 1000), "500 KB")
})

test("setupDownloadCards: one card per repo with the live clone percent", () => {
  same(Model.setupDownloadCards(null, null), [])
  const cards = Model.setupDownloadCards([
    { path: "~/.dotfiles", state: "cloned", sizeLabel: "3 MB" },
    { path: "~/wallpapers", state: "cloning", sizeLabel: "~1 GB" }
  ], { item: "~/wallpapers", percent: 45, size: "410 MB", label: "Downloading 45% \u00b7 410 MB" })
  assert.equal(cards[0].detail, "done")
  assert.equal(cards[0].size, "3 MB")
  assert.equal(cards[0].tone, "accent")
  assert.equal(cards[1].percent, 45)
  assert.equal(cards[1].detail, "Downloading 45% \u00b7 410 MB")
  assert.equal(cards[1].size, "410 MB")
  const waiting = Model.setupDownloadCards([{ path: "~/x", state: "waiting" }], null)
  assert.equal(waiting[0].detail, "Waiting")
  const failed = Model.setupDownloadCards([{ path: "~/y", state: "error", error: "private" }], null)
  assert.equal(failed[0].tone, "urgent")
  assert.equal(failed[0].detail, "private")
  // A cloning card uses the decimal human size when bytes are known (finding 66).
  const withBytes = Model.setupDownloadCards([{ path: "~/wallpapers", state: "cloning" }], {
    item: "~/wallpapers", percent: 45, size: "410.20 MiB", bytes: Model.parseSizeBytes("410.20 MiB"), label: "Downloading 45% \u00b7 430 MB"
  })
  assert.equal(withBytes[0].size, "430 MB")
})

test("downloadRate: unknown inputs hide the speed and ETA", () => {
  same(Model.downloadRate(0, 0, 0, 100), { ok: false, speedText: "", etaText: "" })
  same(Model.downloadRate(10, 20, 1, 100), { ok: false, speedText: "", etaText: "" })
  same(Model.downloadRate(20, 10, 0, 100), { ok: false, speedText: "", etaText: "" })
  same(Model.downloadRate(NaN, 10, 1, 100), { ok: false, speedText: "", etaText: "" })
})

test("downloadRate: a known delta yields a speed and an ETA", () => {
  const r = Model.downloadRate(10 * 1000 * 1000, 0, 5, 40 * 1000 * 1000)
  assert.equal(r.ok, true)
  assert.equal(r.speedText, "2 MB/s")
  assert.equal(r.etaText, "about 15 s left")
  const minutes = Model.downloadRate(2 * 1000 * 1000, 0, 1, 602 * 1000 * 1000)
  assert.equal(minutes.etaText, "about 5 min left")
  // A completed transfer has no remaining time.
  const done = Model.downloadRate(40 * 1000 * 1000, 20 * 1000 * 1000, 10, 40 * 1000 * 1000)
  assert.equal(done.ok, true)
  assert.equal(done.etaText, "")
})

test("setupDownloadCards: the active card carries the speed line", () => {
  const rate = { ok: true, speedText: "2.1 MB/s", etaText: "about 6 min left" }
  const cards = Model.setupDownloadCards(
    [{ path: "~/wallpapers", state: "cloning" }],
    { item: "~/wallpapers", percent: 45, bytes: 1000, size: "1 KB", label: "Downloading 45%" },
    rate
  )
  assert.equal(cards[0].speed, "2.1 MB/s \u00b7 about 6 min left")
  // No rate (or an unusable one) leaves the line empty so the UI hides it.
  const none = Model.setupDownloadCards([{ path: "~/y", state: "cloning" }], null, null)
  assert.equal(none[0].speed, "")
})

test("setupDownloadSummary: overall line and success state", () => {
  assert.equal(Model.setupDownloadSummary([]), "")
  assert.equal(Model.setupDownloadSummary([{ state: "cloning" }, { state: "cloned" }]), "Downloading 2 repos \u00b7 1 of 2 done")
  assert.equal(Model.setupDownloadSummary([{ state: "cloned" }, { state: "ready" }]), "All 2 repos downloaded")
  assert.equal(Model.setupDownloadSummary([{ state: "cloned" }]), "Repository downloaded")
  // A single in-progress repo reads "1 repo", never "1 repos" (finding 65).
  assert.equal(Model.setupDownloadSummary([{ state: "cloning" }]), "Downloading 1 repo \u00b7 0 of 1 done")
})

test("setupReviewSummary: one plain sentence for the whole step", () => {
  const plan = {
    clone: [{ path: "~/wallpapers" }],
    link: [
      { repo: "~/.dotfiles", package: "fish", status: "conflicts", files_to_backup: 1, conflicts: [] },
      { repo: "~/.dotfiles", package: "omarchy", status: "already", files_to_backup: 0, conflicts: [] },
      { repo: "~/.dotfiles", package: "app", status: "new", files_to_backup: 0, conflicts: [] }
    ]
  }
  const text = Model.setupReviewSummary(plan)
  assert.ok(text.indexOf("download 1 repository") !== -1, text)
  assert.ok(text.indexOf("link 2 packages") !== -1, text)
  assert.ok(text.indexOf("keep a backup of 1 file") !== -1, text)
  assert.ok(text.indexOf("Nothing is deleted") !== -1, text)
  assert.equal(Model.setupReviewSummary({}), "Nothing to set up.")
})

test("setupConflictWording: plain words for identical/different", () => {
  assert.equal(Model.setupConflictWording("identical"), "same as yours \u2192 replaced")
  assert.ok(Model.setupConflictWording("different").indexOf("saved to backup") !== -1)
  assert.equal(Model.setupConflictWording(""), "")
})

test("setupBackupByPackage: files grouped by package, blocked skipped", () => {
  const plan = { link: [
    { repo: "~/.dotfiles", package: "nvim", conflicts: [
      { target: "~/.config/nvim/init.lua", kind: "different" },
      { target: "~/.config/nvim/lua/x.lua", kind: "identical" }
    ] },
    { repo: "~/.dotfiles", package: "app", conflicts: [{ target: "~/.config/app/conf", kind: "blocked" }] }
  ] }
  const groups = Model.setupBackupByPackage(plan)
  assert.equal(groups.length, 1)
  assert.equal(groups[0].package, "nvim")
  assert.equal(groups[0].count, 2)
  assert.equal(groups[0].unit, "files")
  assert.equal(groups[0].files[0].wording, "Omarchy's version \u2192 saved to backup, yours is used")
  // Per-kind counts and bare basenames are returned (finding 69).
  assert.equal(groups[0].savedToBackup, 1)
  assert.equal(groups[0].identical, 1)
  assert.equal(groups[0].files[0].name, "init.lua")
  assert.equal(groups[0].files[1].name, "x.lua")
})

test("setupPlanGroups: per-package backup detail counts saved vs identical", () => {
  const plan = setupPlan({ link: [
    { repo: "~/.dotfiles", package: "nvim", status: "conflicts", files_to_backup: 10, conflicts: [
      { target: "~/.config/nvim/a.lua", kind: "different" },
      { target: "~/.config/nvim/b.lua", kind: "different" },
      { target: "~/.config/nvim/c.lua", kind: "identical" }
    ] }
  ] })
  const backup = Model.setupPlanGroups(plan).filter(function(g) { return g.key === "backup" })[0]
  assert.equal(backup.items[0].detail, "3 files \u00b7 2 saved to backup, 1 same as yours")
  same(backup.items[0].sub, ["a.lua", "b.lua", "c.lua"])
})

test("setupToggleLabel: explicit On / Off wording", () => {
  assert.equal(Model.setupToggleLabel(true), "On")
  assert.equal(Model.setupToggleLabel(false), "Off")
  assert.equal(Model.setupToggleLabel(undefined), "Off")
})

test("groupCountLabel: a count and a bare unit render once", () => {
  assert.equal(Model.groupCountLabel(6, "packages"), "6 packages")
  assert.equal(Model.groupCountLabel(1, "file"), "1 file")
  assert.equal(Model.groupCountLabel(2, "notes"), "2 notes")
  assert.equal(Model.groupCountLabel(0, "steps"), "0 steps")
  assert.equal(Model.groupCountLabel(-1, "packages"), "")
  assert.equal(Model.groupCountLabel(3, ""), "3")
  // Every group unit is a BARE noun, so count + unit is one label, never "6 6 packages".
  const report = Model.setupReport({
    ok: true,
    packages: Array(6).fill({ state: "applied", repo: "~/.dotfiles", package: "p" }),
    moved: Array(4).fill({ path: "~/.config/x" })
  })
  const byKey = {}
  report.sections.forEach(function(s) { byKey[s.key] = s })
  assert.equal(byKey.packages.unit, "packages")
  assert.equal(Model.groupCountLabel(byKey.packages.count, byKey.packages.unit), "6 packages")
  assert.equal(byKey.moved.unit, "files")
  assert.equal(Model.groupCountLabel(byKey.moved.count, byKey.moved.unit), "4 files")
  const groups = Model.setupPlanGroups({ notes: ["a", "b"] })
  const notes = groups.filter(function(g) { return g.key === "notes" })[0]
  assert.equal(notes.unit, "notes")
  assert.equal(Model.groupCountLabel(notes.count, notes.unit), "2 notes")
})

test("setupUndoSentence: names what undo does", () => {
  assert.equal(
    Model.setupUndoSentence({ packages: Array(17).fill({ state: "applied" }), moved: Array(16).fill({}) }),
    "Unlink the 17 packages and put back the 16 original files"
  )
  assert.equal(
    Model.setupUndoSentence({ packages: Array(1).fill({ state: "applied" }), moved: Array(1).fill({}) }),
    "Unlink the 1 package and put back the 1 original file"
  )
  assert.equal(Model.setupUndoSentence(null), "Unlink the 0 packages and put back the 0 original files")
})

test("setupBackupsRows: id, date, counts and undone", () => {
  same(Model.setupBackupsRows(null), [])
  const rows = Model.setupBackupsRows([
    { id: "20261010T043006Z", created: "2026-10-10T04:30:06+00:00", undone: false, counts: { packages: 17, moved: 16, services: 1 } }
  ])
  assert.equal(rows.length, 1)
  assert.equal(rows[0].id, "20261010T043006Z")
  assert.equal(rows[0].detail, "17 packages \u00b7 16 files \u00b7 1 service")
  assert.equal(rows[0].undone, false)
})

test("setupProgressRows: one row per item with its state", () => {
  same(Model.setupProgressRows(null), [])
  const rows = Model.setupProgressRows({
    phase: "apply", item: "fish", done: 1, total: 3,
    items: [
      { kind: "package", id: "~/.dotfiles \u00b7 fish", state: "done" },
      { kind: "service", id: "ai-tools-check.timer", state: "running" },
      { kind: "post", id: "wallpaper-tint", state: "waiting" }
    ]
  })
  assert.equal(rows.length, 3)
  assert.equal(rows[0].kind, "package")
  assert.equal(rows[0].label, "~/.dotfiles \u00b7 fish")
  assert.equal(rows[0].status, "done")
  assert.equal(rows[1].status, "running")
  assert.equal(rows[2].status, "waiting")
})

test("setupGroupExpanded / setupToggleGroup: toggling flips a group", () => {
  const collapsed = { key: "link", expandByDefault: false }
  const expandedGroup = { key: "notes", expandByDefault: true }
  assert.equal(Model.setupGroupExpanded({}, collapsed), false)
  assert.equal(Model.setupGroupExpanded({}, expandedGroup), true)
  const once = Model.setupToggleGroup({}, collapsed)
  assert.equal(Model.setupGroupExpanded(once, collapsed), true)
  const twice = Model.setupToggleGroup(once, collapsed)
  assert.equal(Model.setupGroupExpanded(twice, collapsed), false)
  const notesToggled = Model.setupToggleGroup({}, expandedGroup)
  assert.equal(Model.setupGroupExpanded(notesToggled, expandedGroup), false)
})

test("setupCloneProgress: percent, size and an indeterminate fallback", () => {
  assert.equal(Model.setupCloneProgress(null), null)
  assert.equal(Model.setupCloneProgress({ phase: "apply" }), null)
  const p = Model.setupCloneProgress({ phase: "clone", item: "~/wallpapers", percent: 45, size: "410.20 MiB", state: "running" })
  assert.equal(p.item, "~/wallpapers")
  assert.equal(p.percent, 45)
  assert.equal(p.bytes, Model.parseSizeBytes("410.20 MiB"))
  // git's binary size renders in the one decimal system (finding 66).
  assert.equal(p.label, "Downloading 45% \u00b7 430 MB")
  const indet = Model.setupCloneProgress({ phase: "clone", item: "x", percent: null, size: "", state: "running" })
  assert.equal(indet.percent, -1)
  assert.equal(indet.label, "Downloading \u2026")
})

test("setupUndoResult: unlinked/restored/disabled counts and problems", () => {
  const r = Model.setupUndoResult({
    ok: true, backup: "20261010T043006Z",
    unstowed: [{ package: "a" }, { package: "b" }],
    restored: [{ path: "~/.config/fish/config.fish" }],
    services_disabled: [{ unit: "t.timer" }],
    refused: [{ package: "c", paths: ["x"] }],
    errors: [{ path: "~/.y", error: "dest changed" }]
  })
  assert.equal(r.backup, "20261010T043006Z")
  assert.ok(r.lines.some((l) => l.label === "2 packages unlinked"))
  assert.ok(r.lines.some((l) => l.label === "1 file restored"))
  assert.ok(r.lines.some((l) => l.label === "1 service disabled"))
  assert.ok(r.lines.some((l) => l.tone === "urgent"))
  assert.equal(Model.setupUndoResult(null).ok, false)
})

test("groupFor / nextGroupKey: Review keyboard navigation", () => {
  const groups = [{ key: "a" }, { key: "b" }, { key: "c" }]
  assert.equal(Model.nextGroupKey(groups, "", 1), "a")
  assert.equal(Model.nextGroupKey(groups, "a", 1), "b")
  assert.equal(Model.nextGroupKey(groups, "c", 1), "c")
  assert.equal(Model.nextGroupKey(groups, "b", -1), "a")
  assert.equal(Model.nextGroupKey(groups, "a", -1), "a")
  assert.equal(Model.nextGroupKey([], "a", 1), "")
  assert.equal(Model.groupFor(groups, "b").key, "b")
  assert.equal(Model.groupFor(groups, "z"), null)
})

test("setupStepName covers the five wizard steps", () => {
  assert.equal(Model.setupWizardSteps.length, 5)
  same(Model.setupWizardSteps, ["Check", "Connect", "Review", "Apply", "Report"])
  assert.equal(Model.setupStepName(0), "Check")
  assert.equal(Model.setupStepName(4), "Report")
  assert.equal(Model.setupStepName(9), "")
})

test("selectRepoCycle / toggleHiddenPath / nextCursor: pure panel helpers", () => {
  const view = { groups: [{ repo: "~/.dotfiles" }, { repo: "~/wallpapers" }] }
  const rows = [
    { key: "a", repo: "~/.dotfiles" },
    { key: "b", repo: "~/wallpapers" }
  ]
  const first = Model.selectRepoCycle(view, rows, 0)
  assert.equal(first.index, 1)
  assert.equal(first.checked.a, true)
  assert.equal(first.checked.b, false)
  assert.ok(first.message.indexOf("dotfiles") !== -1)
  assert.equal(Model.selectRepoCycle({ groups: [] }, rows, 0).message, "")

  const added = Model.toggleHiddenPath(["x"], { path: "y" })
  same(added.paths, ["x", "y"])
  assert.equal(added.removed, false)
  const removed = Model.toggleHiddenPath(["x", "y"], { path: "x" })
  same(removed.paths, ["y"])
  assert.equal(removed.removed, true)

  assert.equal(Model.nextCursor(rows, "a", 1), "b")
  assert.equal(Model.nextCursor(rows, "b", 5), "b")
  assert.equal(Model.nextCursor(rows, "a", -3), "a")
  assert.equal(Model.nextCursor([], "a", 1), "a")
})

// --- hardening: bounded progress parse (README 11) ------------------------

test("parseSetupProgress: caps the polled progress file", () => {
  const obj = Model.parseSetupProgress('{"phase":"apply","done":1}', 262144)
  assert.equal(obj.phase, "apply")
  assert.equal(Model.setupProgressPath("/tmp/s"), "/tmp/s/setup-progress.json")
  assert.equal(Model.parseSetupProgress("   ", 262144), null)
  assert.equal(Model.parseSetupProgress("{not json", 262144), null)
  const big = '{"pad":"' + "x".repeat(300000) + '"}'
  assert.equal(Model.parseSetupProgress(big, 262144), null)
  assert.equal(Model.parseSetupProgress(big), null)
  assert.equal(Model.SETUP_PROGRESS_MAX_BYTES, 262144)
})

// --- Unit 15 Group A: state and feedback (78, 80, 81) ----------------------

test("setupActiveBackups: keeps only un-undone setups", () => {
  same(Model.setupActiveBackups(null), [])
  same(Model.setupActiveBackups([]), [])
  const rows = Model.setupActiveBackups([
    { id: "1", undone: true, counts: { packages: 1 } },
    { id: "2", undone: false, counts: { packages: 1 } },
    { id: "3", counts: { packages: 1 } }
  ])
  assert.equal(rows.length, 2)
  assert.equal(rows[0].id, "2")
  assert.equal(rows[1].id, "3")
})

test("setupUndoSummary: plain sentence from the undo result", () => {
  assert.equal(Model.setupUndoSummary(null), "")
  assert.equal(Model.setupUndoSummary({ ok: false }), "")
  assert.equal(
    Model.setupUndoSummary({ ok: true, unstowed: [1, 2, 3], restored: [1], services_disabled: [1] }),
    "Setup undone \u00b7 3 packages unlinked \u00b7 1 file restored \u00b7 1 service disabled"
  )
  assert.equal(
    Model.setupUndoSummary({ ok: true, unstowed: [1], restored: [], services_disabled: [] }),
    "Setup undone \u00b7 1 package unlinked"
  )
})

test("setupMachineNotSetUp: linked packages and an undone setup decide it (81)", () => {
  assert.equal(Model.setupMachineNotSetUp({ repos: [] }, { setupOn: false }), false)
  assert.equal(
    Model.setupMachineNotSetUp({ repos: [{ path: "~/.dotfiles", exists: false }] }, { setupOn: true }),
    true
  )
  // A surviving stray conflict must not re-enable management after an Undo.
  const conflict = {
    repos: [
      { path: "~/.dotfiles", exists: true, stowed_packages: 0, packages: [{ name: "ghostty", health: "conflicts" }] }
    ]
  }
  assert.equal(Model.setupMachineNotSetUp(conflict, { setupOn: true, backups: [] }), true)
  assert.equal(Model.setupMachineNotSetUp(conflict, { setupOn: true, backups: [{ id: "1", undone: true }] }), true)
  assert.equal(Model.setupMachineNotSetUp(conflict, { setupOn: true, backups: [{ id: "1", undone: false, counts: { packages: 3 } }] }), false)
  const linked = { repos: [{ path: "~/.dotfiles", exists: true, stowed_packages: 3 }] }
  assert.equal(Model.setupMachineNotSetUp(linked, { setupOn: true, backups: [{ id: "1", undone: true }] }), false)
})

// --- Unit 15 Group B: labels and interaction (79, 83, 84) ------------------

test("overviewGroups: a Needs fixing row title is the package name (79)", () => {
  const data = {
    repos: [
      { path: "~/.dotfiles", packages: [{ name: "ghostty", health: "conflicts" }, { name: "nvim", health: "ok" }] }
    ]
  }
  const groups = Model.overviewGroups(data)
  let fixing = null
  for (const g of groups) if (g.key === "fixing") fixing = g
  assert.ok(fixing, "fixing group exists")
  assert.equal(fixing.items.length, 1)
  assert.equal(fixing.items[0].title, "ghostty")
  assert.ok(String(fixing.items[0].subtitle).indexOf("dotfiles") !== -1)
  assert.ok(String(fixing.items[0].subtitle).indexOf("conflict") !== -1)
})

test("accordionKey: expanding one key replaces the previous", () => {
  assert.equal(Model.accordionKey("", "fixing"), "fixing")
  assert.equal(Model.accordionKey("fixing", "outgoing"), "outgoing")
  assert.equal(Model.accordionKey("fixing", "fixing"), "")
})

test("setupAccordionToggle: one group expanded at a time", () => {
  const groups = [{ key: "a" }, { key: "b", expandByDefault: true }, { key: "c" }]
  const onlyA = Model.setupAccordionToggle({}, groups[0], groups)
  assert.equal(onlyA.a, true)
  assert.equal(onlyA.b, false)
  assert.equal(onlyA.c, false)
  const openC = Model.setupAccordionToggle(onlyA, groups[2], groups)
  assert.equal(openC.a, false)
  assert.equal(openC.b, false)
  assert.equal(openC.c, true)
  const closed = Model.setupAccordionToggle(openC, groups[2], groups)
  assert.equal(closed.a, false)
  assert.equal(closed.b, false)
  assert.equal(closed.c, false)
  // Toggling an expandByDefault group closes it instead of opening it again.
  const closedB = Model.setupAccordionToggle({}, groups[1], groups)
  assert.equal(closedB.a, false)
  assert.equal(closedB.b, false)
  assert.equal(closedB.c, false)
})

// --- Unit 15b: header undo decision (87) -----------------------------------

test("headerUndo: one un-undone setup confirms directly", () => {
  assert.equal(Model.headerUndo(null).direct, false)
  assert.equal(Model.headerUndo([]).direct, false)
  assert.equal(Model.headerUndo([{ id: "1", undone: true }]).direct, false)
  assert.equal(Model.headerUndo([{ id: "1" }, { id: "2", undone: false }]).direct, false)
  const one = Model.headerUndo([{ id: "9", undone: false, counts: { packages: 17, moved: 16, services: 1 } }])
  assert.equal(one.direct, true)
  assert.equal(one.backup, "9")
  assert.ok(one.sentence.indexOf("17 packages") !== -1)
  assert.ok(one.sentence.indexOf("16 original files") !== -1)
  assert.ok(one.sentence.indexOf("1 service") !== -1)
})

test("setupUndoSentenceFromCounts names the service when present", () => {
  const s = Model.setupUndoSentenceFromCounts({ packages: 1, moved: 0, services: 2 })
  assert.ok(s.indexOf("1 package") !== -1)
  assert.ok(s.indexOf("2 services") !== -1)
  assert.equal(Model.setupUndoSentenceFromCounts({ packages: 0, moved: 0, services: 0 }).indexOf("service"), -1)
})

// --- Unit 15c: steps-only run (89) ----------------------------------------

test("setupSelectedPostCount: counts the on post steps", () => {
  const plan = { post: [{ id: "a", default: true }, { id: "b", default: false }, { id: "c", default: true }] }
  assert.equal(Model.setupSelectedPostCount(plan, {}), 2)
  assert.equal(Model.setupSelectedPostCount(plan, { b: true }), 3)
  assert.equal(Model.setupSelectedPostCount(plan, { a: false, c: false }), 0)
  assert.equal(Model.setupSelectedPostCount(null, null), 0)
})

test("setupPrimaryLabel / setupReviewSummary: a steps-only run is work", () => {
  const stepsPlan = setupPlan({
    clone: [],
    link: [{ repo: "~/.dotfiles", package: "fish", status: "already", links: [], conflicts: [], files_to_backup: 0 }],
    post: [{ id: "a", default: true }, { id: "b", default: true }]
  })
  assert.equal(Model.setupPrimaryLabel(stepsPlan, 2), "Run 2 steps")
  assert.equal(Model.setupPrimaryLabel(stepsPlan, 1), "Run 1 step")
  assert.equal(Model.setupPrimaryLabel(stepsPlan, 0), "Nothing to set up")
  assert.equal(Model.setupReviewSummary(stepsPlan, 2), "Nothing to link. 2 steps will run.")
  assert.equal(Model.setupReviewSummary(stepsPlan, 1), "Nothing to link. 1 step will run.")
  assert.equal(Model.setupReviewSummary(stepsPlan, 0), "Nothing to set up.")
  // A run with real work keeps the normal wording, even with steps on.
  const workPlan = setupPlan({ link: [{ repo: "~/.dotfiles", package: "fish", status: "new", links: [], conflicts: [], files_to_backup: 0 }] })
  assert.equal(Model.setupPrimaryLabel(workPlan, 2), "Set up · link 1 package")
  assert.equal(Model.setupReviewSummary(workPlan, 2), "Stow Sync will link 1 package. Nothing is deleted, and you can undo it.")
})

test("setupHasWork: real work or a step on enables the button", () => {
  const already = setupPlan({ link: [{ repo: "r", package: "p", status: "already", links: [], conflicts: [], files_to_backup: 0 }] })
  assert.equal(Model.setupHasWork(already, 0), false)
  assert.equal(Model.setupHasWork(already, 2), true)
  assert.equal(Model.setupHasWork(setupPlan({ clone: [{ path: "~/x" }] }), 0), true)
  assert.equal(Model.setupHasWork(setupPlan({ link: [{ repo: "r", package: "p", status: "new", links: [], conflicts: [], files_to_backup: 0 }] }), 0), true)
  assert.equal(Model.setupHasWork(setupPlan({ link: [{ repo: "r", package: "p", status: "blocked", links: [], conflicts: [], files_to_backup: 0 }] }), 0), true)
})

test("setupReport: a steps-only run is flagged with no backup", () => {
  const report = Model.setupReport(
    { ok: true, steps_only: true, backup: "", backup_dir: "", post: [{ id: "mise", state: "ran" }] },
    { post: [{ id: "mise", label: "Install tools" }] }
  )
  assert.equal(report.stepsOnly, true)
  assert.equal(report.backup, "")
  const normal = Model.setupReport({ ok: true, backup: "20260101T000000Z" }, { post: [] })
  assert.equal(normal.stepsOnly, false)
})

test("setupReportSteps: a skipped step says how to run it later", () => {
  const items = Model.setupReportSteps(
    { post: [
      { id: "wallpaper-tint", label: "Recolor wallpapers", available: false, missing: ["gowall"] },
      { id: "zen-sync", label: "Link Zen", available: false, requires_path: "~/.zen/*/prefs.js", reason: "Install Zen Browser and open it once first" }
    ] },
    []
  )
  assert.equal(items[0].state, "skipped: needs gowall \u2014 then run Set up again")
  assert.equal(items[1].state, "skipped: Install Zen Browser and open it once first \u2014 then run Set up again")
})

// --- Unit 15d: Overview setup line (owner decision) ------------------------

test("formatSetupDate: ISO and compact timestamps render as day month", () => {
  assert.equal(Model.formatSetupDate("2026-10-12T03:29:06+00:00"), "12 Oct")
  assert.equal(Model.formatSetupDate("2026-01-05T00:00:00Z"), "5 Jan")
  assert.equal(Model.formatSetupDate("20261012T032906Z"), "12 Oct")
  assert.equal(Model.formatSetupDate(""), "")
})

test("setupLine: quiet Overview line while a real setup can be undone", () => {
  assert.equal(Model.setupLine([], {}), null)
  assert.equal(Model.setupLine(null, {}), null)
  const backups = [
    { id: "1", label: "2026-10-01T00:00:00+00:00", undone: true, counts: { packages: 3 } },
    { id: "2", label: "2026-10-12T03:29:06+00:00", undone: false, counts: { packages: 17, moved: 16, services: 1 } }
  ]
  const line = Model.setupLine(backups, {})
  assert.equal(line.id, "2")
  assert.equal(line.label, "Set up 12 Oct \u00b7 17 packages linked")
  assert.equal(line.multi, false)
  // Hidden while not set up or busy.
  assert.equal(Model.setupLine(backups, { notSetUp: true }), null)
  assert.equal(Model.setupLine(backups, { busy: true }), null)
  // All undone -> nothing to undo.
  assert.equal(Model.setupLine([{ id: "1", label: "x", undone: true, counts: {} }], {}), null)
  // Two active setups -> the newest drives the line, multi is true.
  const two = Model.setupLine(
    [{ id: "a", label: "2026-10-10T00:00:00Z", counts: { packages: 1 } }, { id: "b", label: "2026-10-11T00:00:00Z", counts: { packages: 2 } }],
    {}
  )
  assert.equal(two.id, "b")
  assert.equal(two.multi, true)
})

// --- Unit 15e: empty backups are not setups (91) ---------------------------

test("setupBackupIsReal: a backup that did nothing is not a setup", () => {
  assert.equal(Model.setupBackupIsReal({ counts: { packages: 0, moved: 0, services: 0 } }), false)
  assert.equal(Model.setupBackupIsReal({ counts: { packages: 1 } }), true)
  assert.equal(Model.setupBackupIsReal({ counts: { moved: 1 } }), true)
  assert.equal(Model.setupBackupIsReal({ counts: { services: 1 } }), true)
  assert.equal(Model.setupBackupIsReal({}), false)
  assert.equal(Model.setupBackupIsReal(null), false)
})

test("setupActiveBackups ignores empty backups", () => {
  const rows = Model.setupActiveBackups([
    { id: "empty", counts: { packages: 0, moved: 0, services: 0 } },
    { id: "real", counts: { packages: 17 } },
    { id: "undone", undone: true, counts: { packages: 3 } }
  ])
  same(rows.map(function(r) { return r.id }), ["real"])
})

test("setupLine counts the real setup, not the empty one", () => {
  const empty = { id: "empty", label: "2026-10-12T03:29:06+00:00", counts: { packages: 0, moved: 0, services: 0 } }
  const real = { id: "real", label: "2026-10-11T10:00:00+00:00", counts: { packages: 17 } }
  const line = Model.setupLine([empty, real], {})
  assert.equal(line.id, "real")
  assert.ok(line.label.indexOf("17 packages linked") !== -1)
  // Only the empty one -> no line at all.
  assert.equal(Model.setupLine([empty], {}), null)
})

test("headerUndo goes direct to the real setup, ignoring the empty one", () => {
  const d = Model.headerUndo([
    { id: "empty", counts: { packages: 0, moved: 0, services: 0 } },
    { id: "real", counts: { packages: 17, moved: 16, services: 1 } }
  ])
  assert.equal(d.direct, true)
  assert.equal(d.backup, "real")
})

test("setupMachineNotSetUp ignores an empty backup (91)", () => {
  const status = { repos: [{ path: "~/.dotfiles", exists: true, stowed_packages: 0, packages: [{ name: "ghostty", health: "conflicts" }] }] }
  const empty = { id: "empty", counts: { packages: 0, moved: 0, services: 0 } }
  // real undone + empty un-undone -> still the not-set-up card
  assert.equal(Model.setupMachineNotSetUp(status, { setupOn: true, backups: [{ id: "real", undone: true, counts: { packages: 17 } }, empty] }), true)
  // real un-undone -> set up
  assert.equal(Model.setupMachineNotSetUp(status, { setupOn: true, backups: [{ id: "real", counts: { packages: 17 } }, empty] }), false)
  // only the empty one -> not set up
  assert.equal(Model.setupMachineNotSetUp(status, { setupOn: true, backups: [empty] }), true)
})

test("setupBackupsRows flags an empty backup", () => {
  const rows = Model.setupBackupsRows([
    { id: "empty", created: "2026-10-12T03:29:06+00:00", counts: { packages: 0, moved: 0, services: 0 } },
    { id: "real", created: "2026-10-11T10:00:00+00:00", counts: { packages: 17, moved: 16, services: 1 } }
  ])
  assert.equal(rows[0].empty, true)
  assert.equal(rows[1].empty, false)
})
