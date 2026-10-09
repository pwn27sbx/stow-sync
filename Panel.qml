import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Stow Sync popup: a fixed hero with one primary button, three tabs and a
// scrolling content list. Thin shell over Model.js (pure view model) and
// Runner.qml (process queue); ConfirmCard.qml owns every overlay. Every
// mutation is confirmed before Runner runs it.
Panel {
  id: root
  moduleName: "pwnsxb.stow-sync"
  ipcTarget: "pwnsxb.stow-sync"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property string scriptPath: String(Qt.resolvedUrl("scripts/stow_sync.py")).replace(/^file:\/\//, "")

  property var data: null
  property int activeTab: 0
  property var checkedPaths: ({})
  property bool showExisting: false
  property int cursor: 0
  property string errorText: ""
  property bool started: false
  property string clock: Qt.formatTime(new Date(), "HH:mm")
  // Feedback under the hero; `busyVerb` drives the "Publishing…" label.
  property string resultText: ""
  property bool resultError: false
  property string busyVerb: ""

  property string overlayMode: ""
  property string confirmKind: ""
  property var confirmPayload: ({})

  // Publish card and cumulative batch state (publish / upload / update).
  property string publishMessage: ""
  property var publishLines: []
  property var publishTargets: []
  property var publishSecrets: []
  property bool publishAllowSecrets: false
  property string publishError: ""
  property string publishRepoFilter: ""
  property string publishUpstream: "origin/main"
  property int publishCommitDone: 0
  property bool publishHadError: false
  property string batchKind: ""
  property int batchRemaining: 0
  property string batchError: ""

  // Adopt and diff cards.
  property string adoptRepo: ""
  property string adoptPath: ""
  property string adoptPackage: ""
  property var adoptSuggestions: []
  property string adoptError: ""
  property string diffTitle: ""
  property string diffBody: ""
  property bool diffTruncated: false

  readonly property var repos: data && data.repos ? data.repos : []
  readonly property var hero: Model.heroState(root.data, root.clock)
  readonly property var primary: Model.primaryAction(root.data)
  readonly property var tabs: ["Overview", "Changes", "New configs"]
  readonly property var overviewRows: Model.overviewTabRows(root.data)
  readonly property var changeRows: Model.changeTabRows(root.data)
  readonly property var candidateResult: Model.candidateTabRows(root.data, { showExisting: root.showExisting })
  readonly property var rows: root.activeTab === 0 ? root.overviewRows : (root.activeTab === 1 ? root.changeRows : root.candidateResult.rows)
  readonly property int newCount: Model.newCandidateCount(root.data)
  readonly property int existingCount: root.candidateResult.existingCount
  readonly property var existingPaths: root.candidateResult.existingPaths
  readonly property bool busy: runner.busy
  readonly property bool primaryVisible: root.primary.kind !== "none"
  readonly property string busyLabel: root.busyVerb !== "" ? root.busyVerb + "…" : "Working…"
  readonly property string feedbackText: root.resultText !== "" ? root.resultText : root.errorText
  readonly property bool feedbackError: root.resultText === "" ? root.errorText !== "" : root.resultError
  readonly property int refreshMinutes: Math.max(1, Number(root.setting("refreshMinutes", 5)) || 5)
  readonly property int fetchMinutes: Math.max(1, Number(root.setting("fetchMinutes", 15)) || 15)
  Runner {
    id: runner
    scriptPath: root.scriptPath
    settings: root.settings
    onStatusReady: function(result, fetch) { root.applyStatus(result) }
    onActionReady: function(tag, result) { root.applyAction(tag, result) }
    onFailed: function(tag, message) { root.applyFailure(tag, message) }
  }
  function refresh() { runner.refreshStatus(false) }
  function refreshWithFetch() { runner.refreshStatus(true) }
  function ensureStarted() { if (root.started) return; root.started = true; root.refresh() }
  function setCursor(index) { if (index >= 0 && index < root.rows.length) root.cursor = index }
  function isChecked(key) { return root.checkedPaths[key] !== false }
  function applyStatus(payload) { root.data = payload; root.errorText = "" }
  function setChecked(key, value) { var next = {}; for (var k in root.checkedPaths) next[k] = root.checkedPaths[k]; next[key] = value; root.checkedPaths = next }
  function openConfirm(kind, payload) { root.confirmKind = kind; root.confirmPayload = payload || {}; root.overlayMode = "confirm" }
  function bulkIgnore() { if (root.existingPaths.length > 0) root.openConfirm("ignore-all", { paths: root.existingPaths }) }
  function markAllKnown() { root.openConfirm("baseline", { count: root.newCount }) }
  function toggleExisting() { root.showExisting = !root.showExisting }
  function switchTabTo(index) { root.activeTab = index; root.cursor = 0 }
  function switchTab(dx) { var n = root.tabs.length; if (n > 0) root.switchTabTo((root.activeTab + dx + n) % n) }
  function moveCursor(dy) { root.setCursor(Model.moveCursorIndex(root.rows, root.cursor, 0, dy)) }
  function setResult(text, isError) {
    root.resultText = String(text === undefined || text === null ? "" : text); root.resultError = isError === true
    if (root.resultError) resultTimer.stop(); else resultTimer.restart()
  }
  function acceptConfirm() {
    if (root.busy) return
    if (root.confirmKind === "upload") { root.startBatch("push", Model.uploadPlan(root.data)); return }
    if (root.confirmKind === "update") { root.startBatch("pull", Model.updatePlan(root.data)); return }
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
    var card = Model.publishCard(root.data, root.checkedPaths, root.publishRepoFilter)
    if (card.list.length === 0) { root.setResult("Nothing to publish.", true); return }
    root.publishLines = card.lines; root.publishTargets = card.targets
    root.publishMessage = ""; root.publishSecrets = []; root.publishAllowSecrets = false; root.publishError = ""
    root.overlayMode = "publish"
    runner.runAction("suggest", ["suggest-message", "--repo", card.list[0].repo], JSON.stringify(card.list[0].paths))
  }
  function publishConfirmed() {
    if (root.busy) return
    if (String(root.publishMessage).trim() === "") { root.publishError = "Commit message must not be empty."; return }
    var card = Model.publishCard(root.data, root.checkedPaths, root.publishRepoFilter)
    var plan = Model.publishPlanFrom(card.list, root.publishMessage, root.publishAllowSecrets)
    if (plan.length === 0) { root.publishError = "Nothing to publish."; return }
    root.publishUpstream = card.list.length > 0 && card.list[0].upstream !== "" ? card.list[0].upstream : "GitHub"
    root.publishCommitDone = 0; root.publishHadError = false; root.publishSecrets = []; root.publishError = ""
    root.startBatch("publish", plan)
  }
  function adoptCandidate(row) {
    if (!row) return
    var target = Model.adoptTarget(root.repos)
    if (target.repo === "") { root.setResult("No repository is configured to adopt into.", true); return }
    root.adoptRepo = target.repo; root.adoptPath = String(row.path || "")
    root.adoptPackage = Model.packageFor(row, {})
    root.adoptSuggestions = Model.pickerOptions(target.packages, root.adoptPackage, root.adoptPackage)
    root.adoptError = ""; root.overlayMode = "adopt"
  }
  function adoptConfirmed() {
    if (root.busy) return
    if (String(root.adoptPackage).trim() === "") { root.adoptError = "Package name must not be empty."; return }
    runner.runAction("adopt", ["adopt", "--repo", root.adoptRepo, "--package", root.adoptPackage, "--path", root.adoptPath])
  }
  function applyAction(tag, payload) {
    var outcome = Model.actionOutcome(tag, payload)
    if (outcome.kind === "diff") { root.diffBody = outcome.body; root.diffTruncated = outcome.truncated; root.overlayMode = "diff"; return }
    if (outcome.kind === "suggest") { if (root.overlayMode === "publish") root.publishMessage = outcome.message; return }
    if (root.batchKind === "publish") { root.publishResult(outcome); return }
    if (root.batchKind === "push" || root.batchKind === "pull") { root.batchStep(outcome); return }
    root.overlayMode = ""
    if (outcome.kind === "mutation-error" || outcome.kind === "commit-error") { root.setResult(outcome.error, true); return }
    if (outcome.kind === "commit-secrets") { root.setResult("Secrets detected — review before publishing.", true); return }
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

  function activateRow(row) {
    if (!row) return
    if (row.type === "group") root.toggleExisting()
    else if (row.type === "change") root.openDiff(String(row.repo || ""), String(row.path || ""))
    else if (row.type === "health") root.openConfirm("restow", { repo: row.repo, package: row.package })
    else if (row.type === "candidate") root.adoptCandidate(row)
    else if (row.type === "repo" && (row.changesCount > 0 || row.untrackedCount > 0)) root.openPublish(String(row.name || ""))
    else if (row.type === "repo" && row.behind > 0) root.openConfirm("pull", { repo: String(row.name || "") })
  }

  function openDiff(repo, path) { root.diffTitle = "Diff — " + path; root.diffBody = ""; root.diffTruncated = false; runner.runAction("diff", ["diff", "--repo", repo, "--path", path]) }

  function primaryClicked() {
    var kind = root.primary.kind
    if (kind === "review") root.switchTabTo(1)
    else if (kind === "review-new") root.switchTabTo(2)
    else if (kind === "publish") root.openPublish("")
    else if (kind === "upload") { root.confirmKind = "upload"; root.confirmPayload = { repos: Model.repoNames(root.data, "ahead") }; root.overlayMode = "confirm" }
    else if (kind === "update") { root.confirmKind = "update"; root.confirmPayload = { repos: Model.repoNames(root.data, "behind") }; root.overlayMode = "confirm" }
  }

  function activateCursor() { if (root.overlayMode === "diff") { root.overlayMode = ""; return } root.activateRow(root.rows[root.cursor]) }
  function overlayCancel() { if (!root.busy) root.overlayMode = "" }
  function handleEscape() { if (root.overlayMode !== "") root.overlayCancel(); else root.close() }

  function handleTextKey(text) {
    if (text >= "1" && text <= "3") root.switchTabTo(parseInt(text) - 1)
    else if (text === "r") root.refreshWithFetch()
    else if (text === "p" || text === "u") root.primaryClicked()
    else if (text === "a") { var row = root.rows[root.cursor]; if (row && row.type === "candidate") root.adoptCandidate(row) }
    else if (text === "i") { var cand = root.rows[root.cursor]; if (cand && cand.type === "candidate") root.openConfirm("ignore", { path: cand.path }) }
  }

  onOpenedChanged: if (root.opened) { root.ensureStarted(); root.refresh(); Qt.callLater(function() { keyCatcher.forceActiveFocus() }) }
  onRowsChanged: if (root.cursor >= root.rows.length) root.cursor = Math.max(0, root.rows.length - 1)
  onCursorChanged: { list.currentIndex = root.cursor; list.positionViewAtIndex(root.cursor, ListView.Contain) }

  Timer { interval: 30000; running: true; repeat: true; onTriggered: root.clock = Qt.formatTime(new Date(), "HH:mm") }
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
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(Style.space(360), Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: overlay.contentActiveFocus || overlay.contentPopupOpen
      onMoveRequested: function(dx, dy) { if (root.overlayMode !== "") return; if (dx !== 0) root.switchTab(dx > 0 ? 1 : -1); else root.moveCursor(dy) }
      onActivateRequested: if (root.overlayMode === "") root.activateCursor()
      onCloseRequested: root.handleEscape()
      onTabRequested: function(direction) { if (root.overlayMode === "") root.switchTab(direction >= 0 ? 1 : -1) }
      onTextKey: function(text) { if (root.overlayMode === "") root.handleTextKey(text) }

      ColumnLayout {
        anchors.fill: parent
        spacing: Style.spacing.sm

        Hero {
          Layout.fillWidth: true
          glyph: root.hero.glyph
          title: root.hero.title
          hint: root.hero.hint
          tone: root.hero.tone
          primaryLabel: root.primary.label
          primaryVisible: root.primaryVisible
          primaryEnabled: !root.busy
          busy: root.busy
          busyLabel: root.busyLabel
          resultText: root.feedbackText
          resultError: root.feedbackError
          refreshEnabled: !root.busy
          onPrimaryClicked: root.primaryClicked()
          onRefreshClicked: root.refreshWithFetch()
        }
        Tabs {
          Layout.fillWidth: true
          tabs: root.tabs
          current: root.activeTab
          onSelected: function(index) { root.switchTabTo(index) }
        }

        // The list is the scroll region under the fixed hero and tabs.
        ListView {
          id: list
          Layout.fillWidth: true
          Layout.fillHeight: true
          clip: true
          model: root.rows
          boundsBehavior: Flickable.StopAtBounds
          spacing: Style.spacing.xs

          delegate: Item {
            id: delegateRoot
            required property var modelData
            required property int index
            width: list.width
            implicitHeight: Math.max(repoCard.implicitHeight, itemRow.implicitHeight, candRow.implicitHeight)

            RepoSection {
              id: repoCard
              width: parent.width
              visible: delegateRoot.modelData.type === "repo"
              row: delegateRoot.modelData
              rowIndex: delegateRoot.index
              focused: root.cursor === delegateRoot.index
              onHovered: root.setCursor(delegateRoot.index)
              onPublishRequested: root.openPublish(String(delegateRoot.modelData.name || ""))
              onUpdateRequested: root.openConfirm("pull", { repo: String(delegateRoot.modelData.name || "") })
              onActivated: root.activateRow(delegateRoot.modelData)
            }

            ItemRow {
              id: itemRow
              width: parent.width
              visible: delegateRoot.modelData.type === "change" || delegateRoot.modelData.type === "health" || delegateRoot.modelData.type === "group"
              row: delegateRoot.modelData
              rowIndex: delegateRoot.index
              focused: root.cursor === delegateRoot.index
              header: String(delegateRoot.modelData.header || "")
              checked: root.isChecked(delegateRoot.modelData.key)
              showCheckbox: delegateRoot.modelData.type === "change"
              showAction: delegateRoot.modelData.type === "health" || delegateRoot.modelData.showAction === true
              actionText: delegateRoot.modelData.type === "group" ? "Ignore all" : "Fix"
              onHovered: root.setCursor(delegateRoot.index)
              onToggled: function(value) { root.setChecked(delegateRoot.modelData.key, value) }
              onActivated: root.activateRow(delegateRoot.modelData)
              onActionClicked: function() { if (delegateRoot.modelData.type === "group") root.bulkIgnore(); else root.openConfirm("restow", { repo: delegateRoot.modelData.repo, package: delegateRoot.modelData.package }) }
            }

            CandidateRow {
              id: candRow
              width: parent.width
              visible: delegateRoot.modelData.type === "candidate"
              row: delegateRoot.modelData
              rowIndex: delegateRoot.index
              focused: root.cursor === delegateRoot.index
              header: String(delegateRoot.modelData.header || "")
              showBulk: delegateRoot.modelData.showBulk === true
              packageName: Model.packageFor(delegateRoot.modelData, {})
              onHovered: root.setCursor(delegateRoot.index)
              onAdoptRequested: root.adoptCandidate(delegateRoot.modelData)
              onIgnoreRequested: root.openConfirm("ignore", { path: delegateRoot.modelData.path })
              onBulkIgnoreRequested: root.bulkIgnore()
            }
          }
        }
      }
    }

    ConfirmCard {
      id: overlay
      anchors.fill: parent
      opened: root.overlayMode !== ""
      mode: root.overlayMode
      confirmKind: root.confirmKind
      confirmPayload: root.confirmPayload
      publishMessage: root.publishMessage
      publishLines: root.publishLines
      publishTargets: root.publishTargets
      publishSecrets: root.publishSecrets
      publishAllowSecrets: root.publishAllowSecrets
      publishError: root.publishError
      adoptRepo: root.adoptRepo
      adoptPath: root.adoptPath
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
