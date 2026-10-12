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
  property var candidates: null
  property bool repoLoading: false
  property string repoError: ""
  property var connectEntries: []
  property var cloneQueue: []
  property bool connectRunning: false
  property bool connectAuthError: false
  property var plan: null
  property string planToken: ""
  property bool planLoading: false
  property var applyResult: null
  property var undoResult: null
  property string undoError: ""
  property var backups: []
  property var postChecked: ({}); property var groupsExpanded: ({}); property string groupKey: ""; property string selectedUrl: ""
  property string errorText: ""
  property bool applying: false

  readonly property bool running: flow.applying || flow.connectRunning
  readonly property var stepNames: Model.setupWizardSteps
  readonly property var stepRows: Model.setupStepState(flow.applyResult)
  readonly property var report: Model.setupReport(flow.applyResult, flow.plan, flow.undoResult !== null)
  readonly property string undoSentence: flow.applyResult !== null ? Model.setupUndoSentence(flow.applyResult) : ""

  function start() {
    flow.mode = "wizard"
    flow.step = 0
    flow.url = Model.setupPrefillUrl(flow.statusData)
    flow.prereqs = null
    flow.checking = false
    flow.candidates = null
    flow.connectEntries = []
    flow.cloneQueue = []
    flow.connectRunning = false
    flow.connectAuthError = false
    flow.plan = null
    flow.planToken = ""
    flow.planLoading = false
    flow.applyResult = null
    flow.undoResult = null
    flow.undoError = ""
    flow.postChecked = ({})
    flow.groupsExpanded = ({})
    flow.groupKey = ""
    flow.selectedUrl = ""
    flow.errorText = ""
    flow.applying = false
    flow.runCheck()
  }

  function openBackups() { flow.mode = "backups"; flow.errorText = "" }

  // Header Undo decision (finding 83): one un-undone setup confirms directly.
  function headerUndo() {
    var active = Model.setupActiveBackups(flow.backups)
    if (active.length !== 1) return { direct: false }
    return { direct: true, backup: String(active[0].id || ""), sentence: Model.setupUndoSentenceFromCounts(active[0].counts) }
  }

  function runCheck() { flow.checking = true; flow.errorText = ""; flow.requested("setup-prereqs", ["setup-prereqs", "--url", flow.url]) }
  function fetchRepos() { flow.repoLoading = true; flow.repoError = ""; flow.requested("setup-candidates", ["setup-candidates"]) }
  function retryRepos() { flow.fetchRepos() }
  function goConnect() { flow.step = 1; if (flow.candidates === null) flow.fetchRepos() }

  function reviewGroups() { return Model.setupPlanGroups(flow.plan) }

  function moveGroup(dy) { flow.groupKey = Model.nextGroupKey(flow.reviewGroups(), flow.groupKey, dy) }

  function toggleGroupKey(key) {
    var group = Model.groupFor(flow.reviewGroups(), String(key || flow.groupKey))
    if (group) flow.groupsExpanded = Model.setupAccordionToggle(flow.groupsExpanded, group, flow.reviewGroups())
  }

  function connect() {
    if (!Model.setupValidUrl(flow.url)) { flow.errorText = "Enter a GitHub URL or a URL ending in .git."; return }
    flow.errorText = ""
    // Replace the picker with the checklist at once: the dotfiles clone runs
    // first, the other repos appear once setup-connect returns the recipe.
    flow.connectEntries = [{ path: "~/.dotfiles", state: "cloning", error: "", authError: false }]
    flow.cloneQueue = []
    flow.connectAuthError = false
    flow.connectRunning = true
    flow.requested("setup-connect", ["setup-connect", "--url", flow.url])
  }

  function setEntryState(path, state, error, authError, sizeBytes) {
    var next = []
    for (var i = 0; i < flow.connectEntries.length; i++) {
      var e = flow.connectEntries[i]
      if (String(e.path) === String(path)) {
        var sb = (sizeBytes === undefined || sizeBytes === null) ? e.sizeBytes : sizeBytes
        next.push({ path: e.path, state: state, error: error, authError: authError === true, sizeBytes: sb, sizeLabel: Model.setupSizeLabel(sb) })
      } else next.push(e)
    }
    flow.connectEntries = next
  }

  function runNextClone() {
    if (flow.cloneQueue.length === 0) { flow.connectRunning = false; return }
    var entry = flow.cloneQueue[0]
    flow.cloneQueue = flow.cloneQueue.slice(1)
    flow.connectRunning = true
    flow.setEntryState(entry.path, "cloning", "", false)
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
    flow.requested("setup-plan", ["setup-plan"])
  }

  function applyPlan() {
    if (flow.planLoading || flow.plan === null) return
    flow.step = 3
    flow.applying = true
    flow.errorText = ""
    flow.requested("setup-apply", ["setup-apply", "--token", flow.planToken, "--post", Model.setupSelectedPostIds(flow.plan, flow.postChecked).join(",")])
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
    if (flow.step === 2) return flow.planLoading ? "Working\u2026" : Model.setupPrimaryLabel(flow.plan)
    if (flow.step === 3) return flow.applying ? "Setting up\u2026" : "Continue"
    return "Done"
  }

  function primaryEnabled() {
    if (flow.running) return false
    if (flow.mode === "backups") return true
    if (flow.step === 0) return Model.setupPrereqReady(flow.prereqs)
    if (flow.step === 1) return !flow.connectRunning && (flow.connectDone() || Model.setupValidUrl(flow.url))
    if (flow.step === 2) return !flow.planLoading && flow.plan !== null
    if (flow.step === 3) return !flow.applying
    return true
  }

  function primary() {
    if (!flow.primaryEnabled()) return
    if (flow.mode === "backups") { flow.closed(); return }
    if (flow.step === 0) { flow.goConnect(); return }
    if (flow.step === 1) { if (flow.connectDone()) flow.loadPlan(); else flow.connect(); return }
    if (flow.step === 2) { flow.applyPlan(); return }
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
    if (tag === "setup-candidates") {
      flow.repoLoading = false
      if (payload && payload.ok === true) {
        flow.candidates = payload
        flow.repoError = ""
        if (flow.url === "") {
          var first = Model.setupCandidateFirstUrl(payload)
          if (first !== "") { flow.url = first; flow.selectedUrl = first }
        }
      } else {
        flow.candidates = null
        flow.repoError = String((payload && payload.error) || "Could not load your GitHub repos.")
      }
      return
    }
    if (tag === "setup-connect") {
      if (!payload || payload.ok === false) {
        flow.connectRunning = false
        flow.errorText = String(payload && payload.error || "Connect failed.")
        if (payload && payload.auth_error === true) {
          flow.connectAuthError = true
          flow.connectEntries = []
        }
        return
      }
      var entries = [{ path: String(payload.path || ""), state: String(payload.state || ""), error: payload.error ? String(payload.error) : "", authError: payload.auth_error === true, sizeBytes: payload.size_bytes, sizeLabel: Model.setupSizeLabel(payload.size_bytes) }]
      var queue = []
      var repos = payload.repos || []
      for (var i = 0; i < repos.length; i++) {
        entries.push({ path: String(repos[i].path || ""), state: "waiting", error: "", sizeBytes: repos[i].size_bytes, sizeLabel: Model.setupSizeLabel(repos[i].size_bytes) })
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
      flow.setEntryState(path, state, error, !!(payload && payload.auth_error), payload ? payload.size_bytes : undefined)
      if (payload && payload.auth_error === true) flow.connectAuthError = true
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
      flow.groupsExpanded = ({})
      flow.groupKey = ""
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
      // Failure lives in `undoError` (never `errorText`, which a status refresh clears).
      if (!payload || payload.ok === false) { flow.undoError = String(payload && payload.error || "Undo failed."); return }
      flow.undoResult = payload; flow.undoError = ""
      return
    }
  }

  function handleFailure(tag, message) {
    flow.applying = false
    flow.checking = false
    flow.planLoading = false
    flow.connectRunning = false
    if (tag === "setup-candidates") { flow.repoLoading = false; flow.repoError = String(message || "Could not load your GitHub repos.") }
    flow.errorText = String(message || "The helper failed.")
  }
}
