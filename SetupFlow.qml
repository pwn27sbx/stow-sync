pragma ComponentBehavior: Bound
import QtQuick
import "Model.js" as Model

// State machine behind the "Set up this machine" wizard (README 8b/10b). A
// non-visual QtObject: every value and transition is here, the shell
// (SetupWizard.qml) only renders it and re-emits `requested`/`closed`.
QtObject {
  id: flow

  property var settings: ({})
  property var statusData: null

  signal requested(string tag, var args)
  signal closed()
  signal undoConfirmRequested(string backup, string sentence)

  property string mode: "wizard"
  property int step: 0
  property string url: ""
  property var prereqs: null
  property bool checking: false
  property var repoPicker: []
  property var connectEntries: []
  property var cloneQueue: []
  property bool connectRunning: false
  property var plan: null
  property string planToken: ""
  property bool planLoading: false
  property var applyResult: null
  property var undoResult: null
  property var backups: []
  property var postChecked: ({})
  property string errorText: ""
  property bool applying: false

  readonly property bool running: flow.applying || flow.connectRunning
  readonly property var stepNames: Model.setupWizardSteps
  readonly property var stepRows: Model.setupStepState(flow.applyResult)
  readonly property var report: Model.setupReport(flow.applyResult)
  readonly property string undoSentence: flow.applyResult !== null ? Model.setupUndoSentence(flow.applyResult) : ""
  readonly property string stepLine: flow.mode === "backups" ? "Setup backups"
    : ("Step " + (flow.step + 1) + " of " + flow.stepNames.length + " \u00b7 " + Model.setupStepName(flow.step))

  function fixture() { return flow.settings ? String(flow.settings.setupFixture || "") : "" }

  function start() {
    flow.mode = "wizard"
    flow.step = 0
    flow.url = Model.setupPrefillUrl(flow.statusData)
    flow.prereqs = null
    flow.checking = false
    flow.repoPicker = []
    flow.connectEntries = []
    flow.cloneQueue = []
    flow.connectRunning = false
    flow.plan = null
    flow.planToken = ""
    flow.planLoading = false
    flow.applyResult = null
    flow.undoResult = null
    flow.postChecked = ({})
    flow.errorText = ""
    flow.applying = false
    var applyFixture = flow.settings ? String(flow.settings.setupApplyFixture || "") : ""
    if (applyFixture !== "") { flow.step = 4; flow.requested("setup-fixture", ["setup-fixture", "--path", applyFixture]); return }
    if (flow.fixture() !== "") { flow.loadPlan(); return }
    flow.runCheck()
  }

  function openBackups() { flow.mode = "backups"; flow.errorText = "" }

  function selectedPostIds() {
    var ids = []
    var post = (flow.plan && flow.plan.post) || []
    for (var i = 0; i < post.length; i++) {
      var id = String(post[i].id || "")
      var checked = flow.postChecked[id] !== undefined ? flow.postChecked[id] === true : post[i].default === true
      if (checked) ids.push(id)
    }
    return ids
  }

  function runCheck() { flow.checking = true; flow.errorText = ""; flow.requested("setup-prereqs", ["setup-prereqs", "--url", flow.url]) }
  function fetchRepos() { flow.requested("setup-repos", ["setup-repos"]) }
  function goConnect() { flow.step = 1; if (flow.repoPicker.length === 0) flow.fetchRepos() }

  function connect() {
    if (!Model.setupValidUrl(flow.url)) { flow.errorText = "Enter a GitHub URL or a URL ending in .git."; return }
    flow.errorText = ""
    flow.connectEntries = []
    flow.cloneQueue = []
    flow.connectRunning = true
    flow.requested("setup-connect", ["setup-connect", "--url", flow.url])
  }

  function setEntryState(path, state, error) {
    var next = []
    for (var i = 0; i < flow.connectEntries.length; i++) {
      var e = flow.connectEntries[i]
      if (String(e.path) === String(path)) next.push({ path: e.path, state: state, error: error })
      else next.push(e)
    }
    flow.connectEntries = next
  }

  function runNextClone() {
    if (flow.cloneQueue.length === 0) { flow.connectRunning = false; return }
    var entry = flow.cloneQueue[0]
    flow.cloneQueue = flow.cloneQueue.slice(1)
    flow.connectRunning = true
    flow.setEntryState(entry.path, "cloning", "")
    flow.requested("setup-clone", ["setup-clone", "--path", entry.path])
  }

  function connectDone() {
    if (flow.connectEntries.length === 0 || flow.connectRunning) return false
    for (var i = 0; i < flow.connectEntries.length; i++) {
      var st = String(flow.connectEntries[i].state || "")
      if (st !== "cloned" && st !== "ready" && st !== "error") return false
    }
    return true
  }

  function loadPlan() {
    flow.step = 2
    flow.planLoading = true
    flow.errorText = ""
    var args = ["setup-plan"]
    if (flow.fixture() !== "") args = args.concat(["--fixture", flow.fixture()])
    flow.requested("setup-plan", args)
  }

  function applyPlan() {
    if (flow.planLoading || flow.plan === null) return
    flow.step = 3
    flow.applying = true
    flow.errorText = ""
    flow.requested("setup-apply", ["setup-apply", "--token", flow.planToken, "--post", flow.selectedPostIds().join(",")])
  }

  function requestUndo(backupId) {
    var id = String(backupId || "")
    if (id === "") return
    var sentence = flow.undoSentence !== "" ? flow.undoSentence : "Unlink the linked packages and put back the original files."
    flow.undoConfirmRequested(id, sentence)
  }

  function primaryLabel() {
    if (flow.mode === "backups") return "Done"
    if (flow.step === 0) return flow.checking ? "Checking\u2026" : "Continue"
    if (flow.step === 1) return flow.connectRunning ? "Connecting\u2026" : (flow.connectDone() ? "Review" : "Connect")
    if (flow.step === 2) return flow.planToken === "fixture" ? "Close" : (flow.planLoading ? "Working\u2026" : Model.setupPrimaryLabel(flow.plan))
    if (flow.step === 3) return flow.applying ? "Setting up\u2026" : "Continue"
    return "Done"
  }

  function primaryEnabled() {
    if (flow.running) return false
    if (flow.mode === "backups") return true
    if (flow.step === 0) return Model.setupPrereqReady(flow.prereqs)
    if (flow.step === 1) return !flow.connectRunning && (flow.connectDone() || Model.setupValidUrl(flow.url))
    if (flow.step === 2) return !flow.planLoading && (flow.planToken === "fixture" || flow.plan !== null)
    if (flow.step === 3) return !flow.applying
    return true
  }

  function primary() {
    if (!flow.primaryEnabled()) return
    if (flow.mode === "backups") { flow.closed(); return }
    if (flow.step === 0) { flow.goConnect(); return }
    if (flow.step === 1) { if (flow.connectDone()) flow.loadPlan(); else flow.connect(); return }
    if (flow.step === 2) { if (flow.planToken === "fixture") { flow.closed(); return } flow.applyPlan(); return }
    if (flow.step === 3) { if (flow.applyResult) flow.step = 4; return }
    flow.closed()
  }

  function back() {
    if (flow.running) { flow.errorText = flow.step === 3 ? "Setup is running" : "Connect is running"; return }
    if (flow.mode === "backups") { flow.closed(); return }
    if (flow.step >= 1 && flow.step <= 3) { flow.step = flow.step - 1; flow.errorText = ""; return }
    if (flow.step === 4) { flow.step = 3; return }
    flow.closed()
  }

  function backLabel() {
    if (flow.mode === "backups") return "Close"
    return flow.step === 0 ? "Cancel" : (flow.step === 4 ? "Close" : "Back")
  }

  function handleResult(tag, payload) {
    if (tag === "setup-prereqs") {
      flow.checking = false
      if (!payload || payload.ok === false) { flow.errorText = String(payload && payload.error || "Could not check this machine."); return }
      flow.prereqs = payload
      return
    }
    if (tag === "setup-repos") {
      flow.repoPicker = (payload && payload.ok === true) ? Model.setupRepoPickerRows(payload.repos) : []
      return
    }
    if (tag === "setup-fixture") {
      if (payload && payload.ok === true) { flow.applyResult = payload.data; flow.step = 4 }
      else { flow.errorText = String(payload && payload.error || "Could not read the fixture.") }
      return
    }
    if (tag === "setup-connect") {
      if (!payload || payload.ok === false) { flow.connectRunning = false; flow.errorText = String(payload && payload.error || "Connect failed."); return }
      var entries = [{ path: String(payload.path || ""), state: String(payload.state || ""), error: payload.error ? String(payload.error) : "" }]
      var queue = []
      var repos = payload.repos || []
      for (var i = 0; i < repos.length; i++) {
        entries.push({ path: String(repos[i].path || ""), state: "waiting", error: "" })
        queue.push({ path: String(repos[i].path || "") })
      }
      flow.connectEntries = entries
      flow.cloneQueue = queue
      if (queue.length === 0) flow.connectRunning = false
      else flow.runNextClone()
      return
    }
    if (tag === "setup-clone") {
      var path = payload && payload.path ? String(payload.path) : ""
      var state = (!payload || payload.ok === false) ? "error" : String(payload.state || "error")
      var error = payload && payload.error ? String(payload.error) : ""
      flow.setEntryState(path, state, error)
      flow.runNextClone()
      return
    }
    if (tag === "setup-plan") {
      flow.planLoading = false
      if (!payload || payload.ok === false) { flow.errorText = String(payload && payload.error || "Could not build the plan."); return }
      flow.plan = payload.plan
      flow.planToken = String(payload.token || "")
      var selection = {}
      var post = (payload.plan && payload.plan.post) || []
      for (var p = 0; p < post.length; p++) selection[String(post[p].id || "")] = post[p].default === true
      flow.postChecked = selection
      return
    }
    if (tag === "setup-apply") {
      flow.applying = false
      if (!payload || payload.ok === false) { flow.errorText = String(payload && payload.error || "Setup failed."); flow.step = 2; return }
      flow.applyResult = payload
      flow.step = 4
      return
    }
    if (tag === "setup-backups") {
      flow.backups = (payload && payload.ok === true) ? Model.setupBackupsRows(payload.backups) : []
      return
    }
    if (tag === "setup-undo") {
      if (!payload || payload.ok === false) { flow.errorText = String(payload && payload.error || "Undo failed."); return }
      flow.undoResult = payload
      return
    }
  }

  function handleFailure(tag, message) {
    flow.applying = false
    flow.checking = false
    flow.planLoading = false
    flow.connectRunning = false
    flow.errorText = String(message || "The helper failed.")
  }
}
