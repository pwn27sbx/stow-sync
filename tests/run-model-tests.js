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

test("buildRows on a clean repo yields one repo row and one health row", () => {
  const rows = Model.buildRows(fixture("status-clean.json"))
  same(rows.map((r) => r.type), ["repo", "health"])
  const repo = rows[0]
  assert.equal(repo.key, "repo:~/.dotfiles")
  assert.equal(repo.name, "~/.dotfiles")
  assert.equal(repo.basename, ".dotfiles")
  assert.equal(repo.state, "clean")
  assert.equal(repo.stateColor, "muted")
  assert.equal(repo.canCommit, false)
  assert.equal(repo.canPush, false)
  assert.equal(repo.canPull, false)
  assert.equal(rows[1].package, "fish")
  assert.equal(rows[1].attention, false)
})

test("buildRows groups changes by package and sorts health rows", () => {
  const rows = Model.buildRows(fixture("status-mixed.json"))
  same(rows.map((r) => r.type), [
    "repo",
    "change", "change", "change", "change",
    "health", "health", "health",
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
  // Health rows alphabetised: fish, hypr, omarchy.
  same(rows.slice(5, 8).map((r) => r.package), ["fish", "hypr", "omarchy"])
  assert.equal(rows[5].stateColor, "accent")   // pending
  assert.equal(rows[6].stateColor, "urgent")   // conflicts
  assert.equal(rows[7].stateColor, "muted")    // ok
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
  const collapsed = Model.panelRows(fixture("status-candidates.json"), false)
  same(collapsed.rows.filter((r) => r.type === "candidate").map((r) => r.path), [
    "~/.config/systemd/user/a.timer",
    "~/.config/zzz"
  ])
  assert.equal(collapsed.newCount, 2)
  assert.equal(collapsed.existingCount, 2)
  same(collapsed.existingPaths, [])
  assert.equal(collapsed.rows.find((r) => r.type === "candidate").header, "New configs (2)")

  const expanded = Model.panelRows(fixture("status-candidates.json"), true)
  assert.equal(expanded.rows.filter((r) => r.type === "candidate").length, 4)
  same(expanded.existingPaths, ["~/.local/bin/foo", "~/.config/aaa"])
  const existingHeader = expanded.rows.find((r) => r.type === "candidate" && r.known)
  assert.equal(existingHeader.header, "Existing untracked (2)")
  assert.equal(existingHeader.showBulk, true)
  // Non-candidate rows never carry a header.
  assert.equal(expanded.rows[0].header, undefined)
})

test("panelRows tolerates missing data", () => {
  const result = Model.panelRows(null, true)
  same(result.rows, [])
  assert.equal(result.newCount, 0)
  assert.equal(result.existingCount, 0)
  same(result.existingPaths, [])
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
  assert.equal(Model.activateIntent({ type: "candidate" }).kind, "adopt")
  assert.equal(Model.activateIntent(null).kind, "none")
})
