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
  assert.equal(outgoing.subtitle, "4 items included \u00b7 press to expand")
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
  assert.equal(incoming.subtitle, "2 items included \u00b7 press to expand")
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
