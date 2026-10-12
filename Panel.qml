pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model
// Stow Sync popup: config-sync parity layout. A fixed header and tab bar, a
// scrolling Flickable body (RepoSection.qml renders the active tab) and one
// overlay host. Thin shell over Model.js (pure view model) and Runner.qml
// (process queue); ConfirmCard.qml owns every overlay. Every mutation is
// confirmed before Runner runs it.
Panel {
  id: root
  moduleName: "pwnsxb.stow-sync"
  ipcTarget: "pwnsxb.stow-sync"
  manageIpc: false
  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property string scriptPath: String(Qt.resolvedUrl("scripts/stow_sync.py")).replace(/^file:\/\//, "")
  readonly property string version: "0.1.0"
  readonly property string configPath: String(root.setting("configPath", "")) !== "" ? String(root.setting("configPath", "")) : (Quickshell.env("HOME") + "/.config/stow-sync/config.json")
  property var statusData: null; property int activeTab: 0; property var checkedPaths: ({}); property var hiddenPaths: []
  property bool showHidden: false; property bool showExisting: false; property string focusedKey: ""; property int repoCycleIndex: 0
  property string errorText: ""; property string resultText: ""; property bool started: false; property double nowMs: Date.now(); property bool settingsReady: false
  property string busyVerb: ""; property string overlayMode: ""; property bool setupOpen: false; property bool backupsFetched: false; property bool undoFromHeader: false
  property string confirmKind: ""; property var confirmPayload: ({})
  property string publishMessage: ""; property var publishLines: []; property var publishTargets: []; property var publishSecrets: []
  property bool publishAllowSecrets: false; property string publishError: ""; property string publishRepoFilter: ""; property string publishUpstream: "origin/main"
  property int publishCommitDone: 0; property bool publishHadError: false
  property string batchKind: ""; property int batchRemaining: 0; property string batchError: ""
  // Adopt and diff cards.
  property string adoptRepo: ""; property string adoptPath: ""; property string adoptPackage: ""; property var adoptSuggestions: []
  property string adoptError: ""; property string diffTitle: ""; property string diffBody: ""; property bool diffTruncated: false
  readonly property string clock: Qt.formatTime(new Date(root.nowMs), "HH:mm")
  readonly property var hero: Model.heroState(root.statusData, root.clock, { machineSetup: root.setupOn, notSetUp: root.setupNotSetUp })
  readonly property var primary: Model.primaryAction(root.statusData)
  readonly property var tabs: ["Overview", "Changes", "Packages"]
  readonly property var changeView: Model.changesView(root.statusData, { hiddenPaths: root.hiddenPaths, showHidden: root.showHidden, showExisting: root.showExisting })
  readonly property var changeRows: root.changeView.rows; readonly property var packages: Model.packageCards(root.statusData)
  readonly property int changeCount: Model.changeTotals(root.statusData).count
  readonly property bool busy: runner.busy
  readonly property string stateDirPath: String(root.setting("stateDir", "")) !== "" ? String(root.setting("stateDir", "")) : (Quickshell.env("HOME") + "/.local/state/stow-sync")
  readonly property string feedbackText: root.errorText !== "" ? root.errorText : root.resultText
  readonly property bool feedbackError: root.errorText !== ""
  readonly property bool motionOn: String(root.setting("motion", "on")) !== "off"
  readonly property bool setupOn: Model.setupVisible(root.settings, root.statusData); readonly property bool setupNeeded: root.setupOn && Model.anyRepoMissing(root.statusData); readonly property var activeBackups: Model.setupActiveBackups(setupWizard.backups); readonly property bool setupNotSetUp: Model.setupMachineNotSetUp(root.statusData, { setupOn: root.setupOn, backups: setupWizard.backups })
  property bool helpOpen: false
  readonly property int refreshMinutes: Math.max(1, Number(root.setting("refreshMinutes", 5)) || 5); readonly property int fetchMinutes: Math.max(1, Number(root.setting("fetchMinutes", 15)) || 15)
  Runner {
    id: runner
    scriptPath: root.scriptPath
    settings: root.settings
    settingsReady: root.settingsReady
    onStatusReady: function(result, fetch) { root.applyStatus(result) }
    onActionReady: function(tag, result) { root.applyAction(tag, result) }
    onFailed: function(tag, message) { root.applyFailure(tag, message) }
  }
  function refresh() { runner.refreshStatus(false) }
  function refreshWithFetch() { runner.refreshStatus(true) }
  function ensureStarted() { if (root.started) return; root.started = true; root.refresh(); if (root.setupOn) root.refreshSetupBackups() }
  function refreshSetupBackups() { if (root.setupOn) runner.runAction("setup-backups", ["setup-backups"]) }
  // Refresh the Overview and the backups list after any setup mutation and when
  // the wizard closes, so the panel never shows a stale state (finding 78).
  function refreshAfterSetup() { root.refresh(); root.refreshSetupBackups() }
  function dismissError() { root.errorText = "" }
  function setResult(text, isError) {
    var value = String(text === undefined || text === null ? "" : text)
    if (isError) { root.errorText = value; root.resultText = ""; resultTimer.stop() }
    else { root.resultText = value; resultTimer.restart() }
  }
  function applyStatus(payload) { root.statusData = payload; root.errorText = ""; if (root.setupOn && !root.backupsFetched) { root.backupsFetched = true; root.refreshSetupBackups() } }
  function switchTabTo(index) { root.activeTab = index; root.focusedKey = "" }
  function switchTab(dx) { var n = root.tabs.length; if (n > 0) root.switchTabTo((root.activeTab + dx + n) % n) }
  function isChecked(key) { return root.checkedPaths[key] !== false }
  function setChecked(key, value) { var next = {}; for (var k in root.checkedPaths) next[k] = root.checkedPaths[k]; next[key] = value; root.checkedPaths = next }
  function selectAll() { var next = {}; for (var i = 0; i < root.changeRows.length; i++) next[root.changeRows[i].key] = true; root.checkedPaths = next }
  function clearSelection() { var next = {}; for (var i = 0; i < root.changeRows.length; i++) next[root.changeRows[i].key] = false; root.checkedPaths = next }
  function selectRepoCycle() {
    var s = Model.selectRepoCycle(root.changeView, root.changeRows, root.repoCycleIndex)
    root.repoCycleIndex = s.index; root.checkedPaths = s.checked; if (s.message !== "") root.setResult(s.message, false)
  }
  function toggleHidden(row) {
    if (!row) return
    var h = Model.toggleHiddenPath(root.hiddenPaths, row)
    root.hiddenPaths = h.paths; if (!h.removed) root.setChecked(row.key, false)
  }
  function focusedChange() { for (var i = 0; i < root.changeRows.length; i++) if (root.changeRows[i].key === root.focusedKey) return root.changeRows[i]; return null }
  function moveCursor(dy) { root.focusedKey = Model.nextCursor(root.changeRows, root.focusedKey, dy) }
  function openConfirm(kind, payload) { root.confirmKind = kind; root.confirmPayload = payload || {}; root.overlayMode = "confirm" }
  function requestUpdate() {
    if (Model.flowTotals(root.statusData, "behind").count > 0) { root.confirmKind = "update"; root.confirmPayload = { repos: Model.repoNames(root.statusData, "behind") }; root.overlayMode = "confirm" }
  }
  function acceptConfirm() {
    if (root.busy) return
    if (root.confirmKind === "setup-undo") { runner.runAction("setup-undo", ["setup-undo", "--backup", String(root.confirmPayload.backup || "")]); return }
    if (root.confirmKind === "upload") { root.startBatch("push", Model.uploadPlan(root.statusData)); return }
    if (root.confirmKind === "update") { root.startBatch("pull", Model.updatePlan(root.statusData)); return }
    var mutation = Model.mutationFor(root.confirmKind, root.confirmPayload)
    runner.runAction(mutation.tag, mutation.args, mutation.stdin)
  }
  function startBatch(kind, steps) {
    root.overlayMode = ""
    if (!steps || steps.length === 0) { root.setResult("Nothing to do.", true); return }
    root.batchKind = kind; root.batchRemaining = steps.length; root.batchError = ""
    root.busyVerb = kind === "publish" ? "Publishing" : (kind === "push" ? "Uploading" : "Updating")
    for (var i = 0; i < steps.length; i++) runner.runAction(steps[i].tag, steps[i].args, steps[i].stdin)
  }
  function finishBatch(text, isError) { root.busyVerb = ""; root.batchKind = ""; root.batchRemaining = 0; root.setResult(text, isError) }
  function openPublish(repoFilter) {
    root.publishRepoFilter = String(repoFilter || "")
    var card = Model.publishCard(root.statusData, root.checkedPaths, root.publishRepoFilter)
    if (card.list.length === 0) { root.setResult("Nothing to publish.", true); return }
    root.publishLines = card.lines; root.publishTargets = card.targets
    root.publishMessage = ""; root.publishSecrets = []; root.publishAllowSecrets = false; root.publishError = ""
    root.overlayMode = "publish"
    runner.runAction("suggest", ["suggest-message", "--repo", card.list[0].repo], JSON.stringify(card.list[0].paths))
  }
  function publishConfirmed() {
    if (root.busy) return
    if (String(root.publishMessage).trim() === "") { root.publishError = "Commit message must not be empty."; return }
    var card = Model.publishCard(root.statusData, root.checkedPaths, root.publishRepoFilter)
    var plan = Model.publishPlanFrom(card.list, root.publishMessage, root.publishAllowSecrets)
    if (plan.length === 0) { root.publishError = "Nothing to publish."; return }
    root.publishUpstream = card.list.length > 0 && card.list[0].upstream !== "" ? card.list[0].upstream : "GitHub"
    root.publishCommitDone = 0; root.publishHadError = false; root.publishSecrets = []; root.publishError = ""
    root.startBatch("publish", plan)
  }
  function adoptCandidate(row) {
    if (!row) return
    var target = Model.adoptTarget(root.statusData ? root.statusData.repos : [])
    if (target.repo === "") { root.setResult("No repository is configured to adopt into.", true); return }
    root.adoptRepo = target.repo; root.adoptPath = String(row.path || "")
    root.adoptPackage = Model.packageFor({ key: row.path, suggestedPackage: row.suggested_package || row.package, path: row.path }, {})
    root.adoptSuggestions = Model.pickerOptions(target.packages, root.adoptPackage, root.adoptPackage); root.adoptError = ""; root.overlayMode = "adopt"
  }
  function adoptFirst() {
    var pick = Model.firstNewCandidate(root.statusData ? root.statusData.candidates : [])
    if (pick) root.adoptCandidate(pick); else root.setResult("No new config to adopt.", true)
  }
  function adoptConfirmed() {
    if (root.busy) return
    if (String(root.adoptPackage).trim() === "") { root.adoptError = "Package name must not be empty."; return }
    runner.runAction("adopt", ["adopt", "--repo", root.adoptRepo, "--package", root.adoptPackage, "--path", root.adoptPath])
  }
  function openDiff(repo, path) { root.diffTitle = "Diff \u2014 " + path; root.diffBody = ""; root.diffTruncated = false; runner.runAction("diff", ["diff", "--repo", repo, "--path", path]) }
  function applyAction(tag, payload) {
    if (String(tag).indexOf("setup-") === 0) {
      setupWizard.handleResult(tag, payload)
      if (tag === "setup-undo" || tag === "setup-apply") { root.overlayMode = ""; if (tag === "setup-undo" && root.undoFromHeader) { root.undoFromHeader = false; root.setupOpen = true; setupWizard.openBackups() }; root.refreshAfterSetup() }
      return
    }
    var outcome = Model.actionOutcome(tag, payload)
    if (outcome.kind === "diff") { root.diffBody = outcome.body; root.diffTruncated = outcome.truncated; root.overlayMode = "diff"; return }
    if (outcome.kind === "suggest") { if (root.overlayMode === "publish") root.publishMessage = outcome.message; return }
    if (root.batchKind === "publish") { root.publishResult(outcome); return }
    if (root.batchKind === "push" || root.batchKind === "pull") { root.batchStep(outcome); return }
    root.overlayMode = ""
    if (outcome.kind === "mutation-error" || outcome.kind === "commit-error") { root.setResult(outcome.error, true); return }
    if (outcome.kind === "commit-secrets") { root.setResult("Secrets detected \u2014 review before publishing.", true); return }
    root.busyVerb = ""; root.setResult(Model.actionSuccessText(tag), false); root.refresh()
  }
  function publishResult(outcome) {
    if (outcome.kind === "commit-secrets") { root.publishSecrets = outcome.secrets; root.publishAllowSecrets = true; root.publishError = "" }
    else if (outcome.kind === "commit-ok") root.publishCommitDone++
    else if (outcome.kind === "mutation-error" || outcome.kind === "commit-error") { root.publishHadError = true; root.publishError = outcome.error }
    root.batchRemaining--
    if (root.batchRemaining > 0) return
    root.busyVerb = ""; root.batchKind = ""
    if (root.publishSecrets.length > 0) { root.overlayMode = "publish"; return }
    root.overlayMode = ""
    if (root.publishHadError) root.setResult(root.publishError || "Publish failed.", true)
    else root.setResult(Model.publishSummaryText(root.publishCommitDone, root.publishUpstream), false)
    root.refresh()
  }
  function batchStep(outcome) {
    if (outcome.kind === "mutation-error") root.batchError = outcome.error
    root.batchRemaining--
    if (root.batchRemaining > 0) return
    var text = root.batchKind === "push" ? "Uploaded commits" : "Updated from GitHub"
    root.finishBatch(root.batchError !== "" ? root.batchError : text, root.batchError !== ""); root.refresh()
  }
  function applyFailure(tag, message) {
    if (String(tag).indexOf("setup-") === 0) { setupWizard.handleFailure(tag, message); if (tag === "setup-apply" || tag === "setup-undo") root.refreshAfterSetup(); return }
    var outcome = Model.failureOutcome(tag, message)
    if (outcome.kind === "ignore") return
    if (outcome.kind === "status-error") { root.setResult(outcome.error, true); return }
    if (root.batchKind === "publish") {
      root.publishHadError = true; root.publishError = outcome.error; root.batchRemaining--
      if (root.batchRemaining <= 0) { root.batchKind = ""; root.busyVerb = ""; root.overlayMode = ""; root.setResult(root.publishError, true); root.refresh() }
      return
    }
    if (root.batchKind !== "") {
      root.batchError = outcome.error; root.batchRemaining--
      if (root.batchRemaining <= 0) { root.finishBatch(root.batchError, true); root.refresh() }
      return
    }
    root.overlayMode = ""; root.busyVerb = ""; root.setResult(outcome.error, true)
  }
  function primaryClicked() {
    var kind = root.primary.kind
    if (kind === "review") root.switchTabTo(1)
    else if (kind === "review-new") { root.switchTabTo(0); overviewTab.expandGroup("newConfigs") }
    else if (kind === "publish") root.openPublish("")
    else if (kind === "upload") { root.confirmKind = "upload"; root.confirmPayload = { repos: Model.repoNames(root.statusData, "ahead") }; root.overlayMode = "confirm" }
    else if (kind === "update") root.requestUpdate()
  }
  function editConfig() { Util.execArgv(["xdg-open", root.configPath]) }
  function openSetup() { root.overlayMode = ""; root.setupOpen = true }
  function undoSetupFromHeader() {
    var d = Model.headerUndo(setupWizard.backups)
    if (!d.direct) { root.setupOpen = true; setupWizard.openBackups(); root.refreshSetupBackups(); return }
    root.setupOpen = false; root.undoFromHeader = true; root.confirmKind = "setup-undo"; root.confirmPayload = { backup: d.backup, sentence: d.sentence }; root.overlayMode = "confirm"
  }
  function overlayCancel() { if (!root.busy) root.overlayMode = "" }
  function handleEscape() {
    if (root.setupOpen) { setupWizard.back(); return }
    if (root.helpOpen) { root.helpOpen = false; return }
    if (root.overlayMode !== "") root.overlayCancel(); else root.close()
  }
  function activateCursor() {
    if (root.setupOpen) { if (setupWizard.reviewActive) setupWizard.reviewToggle(); else setupWizard.primary(); return }
    if (root.overlayMode === "diff") { root.overlayMode = ""; return }
    if (root.activeTab === 1) { var row = root.focusedChange(); if (row) root.openDiff(String(row.repo), String(row.path)) }
  }
  function handleTextKey(text) {
    if (root.setupOpen) return
    if (text >= "1" && text <= "3") root.switchTabTo(parseInt(text) - 1)
    else if (text === "r") root.refreshWithFetch()
    else if (text === "p") { if (root.changeCount > 0) root.openPublish(""); else root.primaryClicked() }
    else if (text === "u") root.requestUpdate()
    else if (text === "a") root.adoptFirst()
    else if (text === "i") root.toggleHidden(root.focusedChange())
  }

  onOpenedChanged: if (root.opened) Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  Timer { interval: 30000; running: true; repeat: true; onTriggered: root.nowMs = Date.now() }
  Timer { id: resultTimer; interval: 6000; repeat: false; onTriggered: root.resultText = "" }
  Timer { interval: root.refreshMinutes * 60000; running: true; repeat: true; onTriggered: if (!root.busy && root.overlayMode === "") root.refresh() }
  Timer { interval: root.fetchMinutes * 60000; running: true; repeat: true; onTriggered: if (!root.busy && root.overlayMode === "") root.refreshWithFetch() }
  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    // Equal inset on all sides; the content column adds no extra horizontal margin.
    padding: Style.space(16)
    contentWidth: panel.fittedContentWidth(Style.space(560))
    // While the wizard is open, reserve the fixed dialog height so the wizard
    // never resizes between steps (README 12c finding 57).
    contentHeight: panel.fittedContentHeight(root.setupOpen ? Style.space(560) : contentColumn.implicitHeight, Style.space(580))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: overlay.contentActiveFocus || overlay.contentPopupOpen || setupWizard.contentActiveFocus
      onMoveRequested: function(dx, dy) {
        if (root.setupOpen) { if (setupWizard.reviewActive && dy !== 0) setupWizard.reviewMove(dy); else if (dy !== 0) setupWizard.scrollBy(dy * Style.space(28)); return }
        if (root.overlayMode !== "") return
        if (dx !== 0) root.switchTab(dx > 0 ? 1 : -1)
        else if (root.activeTab === 1) root.moveCursor(dy)
        else flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, flick.contentY + dy * Style.space(28)))
      }
      onActivateRequested: if (root.overlayMode === "") root.activateCursor()
      onCloseRequested: root.handleEscape()
      onTabRequested: function(direction) { if (root.overlayMode === "") root.switchTab(direction >= 0 ? 1 : -1) }
      onTextKey: function(text) { if (root.overlayMode === "") root.handleTextKey(text) }
      ColumnLayout { id: contentColumn
        anchors.fill: parent
        spacing: Style.spacing.sm
        Header {
          Layout.fillWidth: true
          version: root.version
          stateTone: root.hero.tone
          busy: root.busy
          refreshEnabled: !root.busy
          message: root.feedbackText
          isError: root.feedbackError
          showSetup: root.setupOn
          showSetupBackups: root.setupOn && root.activeBackups.length > 0
          onRefreshClicked: root.refreshWithFetch()
          onEditClicked: root.editConfig()
          onCloseClicked: root.close()
          onDismissed: root.dismissError()
          onHelpToggled: root.helpOpen = !root.helpOpen
          onSetupClicked: root.openSetup()
          onUndoSetupClicked: root.undoSetupFromHeader()
        }

        SegmentedTabs {
          Layout.fillWidth: true
          tabs: root.tabs
          current: root.activeTab
          motion: root.motionOn
          onSelected: function(index) { root.switchTabTo(index) }
        }
        Flickable {
          id: flick
          Layout.fillWidth: true
          Layout.fillHeight: true; Layout.preferredHeight: overviewTab.implicitHeight
          clip: true
          contentWidth: width
          contentHeight: overviewTab.height
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          RepoSection {
            id: overviewTab
            x: 0; width: flick.width
            tab: root.activeTab
            statusData: root.statusData
            version: root.version
            now: String(root.nowMs)
            busy: root.busy
            motion: root.motionOn
            checkedPaths: root.checkedPaths
            hiddenPaths: root.hiddenPaths
            showHidden: root.showHidden
            showExisting: root.showExisting
            setupNeeded: root.setupNeeded
            notSetUp: root.setupNotSetUp
            focusedKey: root.focusedKey
            packages: root.packages
            onReviewRequested: root.switchTabTo(1)
            onPublishRequested: root.openPublish("")
            onUpdateRequested: root.requestUpdate()
            onRestowRequested: function(repo, packageName) { root.openConfirm("restow", { repo: repo, package: packageName }) }
            onAdoptRequested: function(candidate) { root.adoptCandidate(candidate) }
            onIgnoreRequested: function(candidate) { root.openConfirm("ignore", { path: String(candidate.path || "") }) }
            onCopyRequested: function(value) { Util.execArgv(["wl-copy", value]) }
            onSelectAllRequested: root.selectAll()
            onSelectRepoRequested: root.selectRepoCycle()
            onClearSelectionRequested: root.clearSelection()
            onShowHiddenToggled: root.showHidden = !root.showHidden
            onShowExistingToggled: root.showExisting = !root.showExisting
            onSetupRequested: root.openSetup()
            onChangeToggled: function(key, value) { root.setChecked(key, value) }
            onChangeHovered: function(key) { root.focusedKey = key }
            onDiffRequested: function(repo, path) { root.openDiff(repo, path) }
          }
        }
      }
      HelpOverlay {
        anchors.fill: parent
        motion: root.motionOn
        foreground: Color.foreground
        open: root.helpOpen
        onToggleRequested: root.helpOpen = !root.helpOpen
        onCloseRequested: root.helpOpen = false
      }
    }

    SetupWizard {
      id: setupWizard
      anchors.fill: parent
      opened: root.setupOpen; settings: root.settings; statusData: root.statusData
      busy: root.busy; motion: root.motionOn; foreground: Color.foreground
      progressPath: Model.setupProgressPath(root.stateDirPath)
      onRequested: function(tag, args) { runner.runAction(tag, args) }
      onClosed: { root.setupOpen = false; root.refreshAfterSetup() }
      onUndoConfirmRequested: function(backup, sentence) { root.confirmKind = "setup-undo"; root.confirmPayload = { backup: backup, sentence: sentence }; root.overlayMode = "confirm" }
    }
    // Declared after the wizard (z above) so a confirm card never opens under it.
    ConfirmCard {
      id: overlay
      anchors.fill: parent
      z: 2
      opened: root.overlayMode !== ""
      mode: root.overlayMode
      confirmKind: root.confirmKind
      confirmPayload: root.confirmPayload
      publishMessage: root.publishMessage; publishLines: root.publishLines
      publishTargets: root.publishTargets; publishSecrets: root.publishSecrets
      publishAllowSecrets: root.publishAllowSecrets; publishError: root.publishError
      adoptRepo: root.adoptRepo; adoptPath: root.adoptPath
      adoptPackage: root.adoptPackage
      adoptSuggestions: root.adoptSuggestions
      adoptError: root.adoptError
      diffTitle: root.diffTitle
      diffBody: root.diffBody
      diffTruncated: root.diffTruncated
      busy: root.busy
      onConfirmed: root.acceptConfirm()
      onCanceled: root.overlayCancel()
      onPublishMessageEdited: function(text) { root.publishMessage = text }
      onPublishAccepted: root.publishConfirmed()
      onAdoptPackageEdited: function(text) { root.adoptPackage = text }
      onAdoptSuggestionClicked: function(value) { root.adoptPackage = value }
      onAdoptAccepted: root.adoptConfirmed()
    }
  }
}
