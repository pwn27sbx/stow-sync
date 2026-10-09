import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Stow Sync popup. Thin shell over Model.js (pure view model) and Runner.qml
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

  property var data: null
  property var rows: []
  property var existingPaths: []
  property var checkedPaths: ({})
  property var packageOverrides: ({})
  property int cursor: 0
  property int newCount: 0
  property int existingCount: 0
  property bool showExisting: false
  property string lastRefresh: ""
  property string errorText: ""
  // First refresh runs only after the host injects `settings` (see ensureStarted).
  property bool started: false

  property string overlayMode: ""
  property string confirmKind: ""
  property var confirmPayload: ({})
  property string confirmError: ""
  property string commitRepo: ""
  property string commitMessage: ""
  property var commitPaths: []
  property var commitSecrets: []
  property bool commitAllowSecrets: false
  property string commitError: ""
  property string diffTitle: ""
  property string diffBody: ""
  property bool diffTruncated: false
  property string pickerKey: ""
  property string pickerPath: ""
  property string pickerValue: ""
  property var pickerOptions: []

  readonly property var repos: data && data.repos ? data.repos : []
  readonly property var adoptTarget: Model.adoptTarget(repos)
  readonly property bool busy: runner.busy
  readonly property var focusedRow: (cursor >= 0 && cursor < rows.length) ? rows[cursor] : null
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
  // Host calls this after injecting settings; runs the first refresh once.
  function ensureStarted() { if (root.started) return; root.started = true; root.refresh() }
  function setCursor(index) { if (index >= 0 && index < root.rows.length) root.cursor = index }
  function moveCursor(dx, dy) { root.setCursor(Model.moveCursorIndex(root.rows, root.cursor, dx, dy)) }
  function moveSection(direction) { var index = Model.nextSectionIndex(root.rows, root.cursor, direction); if (index >= 0) root.setCursor(index) }
  function setError(message) { root.errorText = String(message || "Something went wrong.") }

  function applyStatus(payload) {
    root.data = payload
    root.errorText = ""
    root.rebuildRows()
    root.lastRefresh = "Updated " + Qt.formatTime(new Date(), "HH:mm:ss")
  }

  function rebuildRows() {
    var result = Model.panelRows(root.data, root.showExisting)
    root.rows = result.rows
    root.newCount = result.newCount
    root.existingCount = result.existingCount
    root.existingPaths = result.existingPaths
    if (root.cursor >= root.rows.length) root.cursor = Math.max(0, root.rows.length - 1)
    var checks = {}
    for (var i = 0; i < root.rows.length; i++) if (root.rows[i].type === "change") checks[root.rows[i].key] = true
    root.checkedPaths = checks
  }

  function setChecked(key, value) {
    var next = {}
    for (var k in root.checkedPaths) next[k] = root.checkedPaths[k]
    next[key] = value
    root.checkedPaths = next
  }

  function applyAction(tag, payload) {
    var outcome = Model.actionOutcome(tag, payload)
    if (outcome.kind === "diff") { root.diffBody = outcome.body; root.diffTruncated = outcome.truncated; root.overlayMode = "diff"; return }
    if (outcome.kind === "suggest") { root.commitMessage = outcome.message; return }
    if (outcome.kind === "commit-secrets") { root.commitSecrets = outcome.secrets; root.commitAllowSecrets = true; root.commitError = "Secrets detected. Review them, then choose Commit anyway."; return }
    if (outcome.kind === "commit-error") { root.commitError = outcome.error; return }
    root.overlayMode = ""
    if (outcome.kind === "commit-ok") { root.commitSecrets = []; root.commitAllowSecrets = false; root.commitError = ""; root.refresh(); return }
    if (outcome.kind === "mutation-error") root.setError(outcome.error)
    else root.refresh()
  }

  function applyFailure(tag, message) {
    var outcome = Model.failureOutcome(tag, message)
    if (outcome.kind === "status-error") { root.setError(outcome.error); return }
    if (outcome.kind === "commit-error") { root.commitError = outcome.error; return }
    if (outcome.kind === "ignore") return
    root.overlayMode = ""
    root.setError(outcome.error)
  }

  function openConfirm(kind, payload) {
    root.confirmKind = kind
    root.confirmPayload = payload || {}
    root.confirmError = ""
    root.overlayMode = "confirm"
  }

  function acceptConfirm() {
    if (root.busy) return
    var mutation = Model.mutationFor(root.confirmKind, root.confirmPayload)
    runner.runAction(mutation.tag, mutation.args, mutation.stdin)
  }

  function overlayConfirm() {
    if (root.overlayMode === "commit") { root.confirmCommit(); return }
    if (root.overlayMode === "picker") { root.applyPackagePick(); return }
    if (root.overlayMode === "diff") { root.overlayMode = ""; return }
    root.acceptConfirm()
  }

  function overlayCancel() {
    if (root.busy) return
    if (root.overlayMode === "commit") { root.commitSecrets = []; root.commitAllowSecrets = false; root.commitError = "" }
    root.overlayMode = ""
  }

  function repoForFocused() {
    var row = root.focusedRow
    if (!row) return ""
    if (row.type === "repo") return row.name
    return row.repo ? String(row.repo) : ""
  }

  function activateRow(row) {
    var intent = Model.activateIntent(row)
    if (intent.kind === "commit") root.openCommit(intent.repo)
    else if (intent.kind === "diff") root.openDiff(intent.repo, intent.path)
    else if (intent.kind === "restow") root.restowPackage(intent.repo, intent.package)
    else if (intent.kind === "adopt") root.adoptCandidate(row)
  }

  function activateCursor() {
    if (root.overlayMode === "diff") { root.overlayMode = ""; return }
    if (root.overlayMode === "commit") { root.confirmCommit(); return }
    if (root.overlayMode === "confirm") { root.acceptConfirm(); return }
    root.activateRow(root.focusedRow)
  }

  function handleEscape() { if (root.overlayMode !== "") root.overlayCancel(); else root.close() }

  function handleTextKey(text) {
    if (text === "r") root.refresh()
    else if (text === "c") root.commitFocusedRepo()
    else if (text === "p") root.pushFocusedRepo()
    else if (text === "u") root.pullFocusedRepo()
    else if (text === "a") { if (root.focusedRow && root.focusedRow.type === "candidate") root.adoptCandidate(root.focusedRow) }
    else if (text === "i") { if (root.focusedRow && root.focusedRow.type === "candidate") root.ignoreCandidate(root.focusedRow) }
  }

  function pushRepo(repo) { var entry = Model.findRepo(root.repos, repo); root.openConfirm("push", { repo: repo, upstream: entry ? entry.upstream : "" }) }
  function pullRepo(repo) { root.openConfirm("pull", { repo: repo }) }
  function restowPackage(repo, package) { root.openConfirm("restow", { repo: repo, package: package }) }
  function pushFocusedRepo() { var repo = root.repoForFocused(); if (repo !== "") root.pushRepo(repo) }
  function pullFocusedRepo() { var repo = root.repoForFocused(); if (repo !== "") root.pullRepo(repo) }
  function commitFocusedRepo() { var repo = root.repoForFocused(); if (repo !== "") root.openCommit(repo) }
  function bulkIgnore() { if (root.existingPaths.length > 0) root.openConfirm("ignore-all", { paths: root.existingPaths }) }
  function markAllKnown() { root.openConfirm("baseline", { count: root.newCount }) }
  function ignoreCandidate(row) { if (row) root.openConfirm("ignore", { path: row.path }) }

  function adoptCandidate(row) {
    if (!row) return
    if (root.adoptTarget.repo === "") { root.setError("No repository is configured to adopt into."); return }
    root.openConfirm("adopt", { repo: root.adoptTarget.repo, package: Model.packageFor(row, root.packageOverrides), path: row.path })
  }

  function openDiff(repo, path) {
    root.diffTitle = "Diff — " + path
    root.diffBody = ""
    root.diffTruncated = false
    runner.runAction("diff", ["diff", "--repo", repo, "--path", path])
  }

  function openCommit(repo) {
    var paths = Model.selectedPaths(root.rows, root.checkedPaths, repo)
    if (paths.length === 0) { root.setError("Select at least one change before committing."); return }
    root.commitRepo = repo
    root.commitPaths = paths
    root.commitMessage = ""
    root.commitSecrets = []
    root.commitAllowSecrets = false
    root.commitError = ""
    root.overlayMode = "commit"
    runner.runAction("suggest", ["suggest-message", "--repo", repo], JSON.stringify(paths))
  }

  function confirmCommit() {
    if (root.busy) return
    root.commitPaths = Model.selectedPaths(root.rows, root.checkedPaths, root.commitRepo)
    if (root.commitPaths.length === 0) { root.commitError = "No paths selected."; return }
    if (String(root.commitMessage).trim() === "") { root.commitError = "Commit message must not be empty."; return }
    runner.runAction("commit", ["commit", "--repo", root.commitRepo], Model.commitPayload(root.commitMessage, root.commitPaths, root.commitAllowSecrets))
  }

  function openPicker(row) {
    root.pickerKey = row.key
    root.pickerPath = row.path
    root.pickerValue = Model.packageFor(row, root.packageOverrides)
    root.pickerOptions = Model.pickerOptions(root.adoptTarget.packages, row.suggestedPackage, root.pickerValue)
    root.overlayMode = "picker"
  }

  function applyPackagePick() {
    var next = {}
    for (var k in root.packageOverrides) next[k] = root.packageOverrides[k]
    next[root.pickerKey] = root.pickerValue
    root.packageOverrides = next
    root.overlayMode = ""
  }

  function toggleExisting() { root.showExisting = !root.showExisting; root.rebuildRows() }

  onOpenedChanged: if (root.opened) { root.ensureStarted(); root.refresh(); Qt.callLater(function() { keyCatcher.forceActiveFocus() }) }
  onCursorChanged: {
    list.currentIndex = root.cursor
    list.positionViewAtIndex(root.cursor, ListView.Contain)
  }

  Timer {
    interval: root.refreshMinutes * 60000
    running: true
    repeat: true
    onTriggered: if (!root.busy && root.overlayMode === "") root.refresh()
  }

  Timer {
    interval: root.fetchMinutes * 60000
    running: true
    repeat: true
    onTriggered: if (!root.busy && root.overlayMode === "") root.refreshWithFetch()
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(Style.space(520), Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: (overlay.mode === "commit" && overlay.contentActiveFocus) || overlay.contentPopupOpen
      onMoveRequested: function(dx, dy) { if (root.overlayMode === "") root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.handleEscape()
      onTabRequested: function(direction) { if (root.overlayMode === "") root.moveSection(direction) }
      onTextKey: function(text) { if (root.overlayMode === "") root.handleTextKey(text) }

      ColumnLayout {
        anchors.fill: parent
        spacing: Style.spacing.sm

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm

          Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: "Stow Sync"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.title; font.bold: true }
          Text { Layout.alignment: Qt.AlignVCenter; visible: root.lastRefresh !== ""; text: root.lastRefresh; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }
          Button { Layout.alignment: Qt.AlignVCenter; visible: root.existingCount > 0; text: (root.showExisting ? "Hide" : "Show") + " untracked (" + root.existingCount + ")"; onClicked: root.toggleExisting() }
          Button { Layout.alignment: Qt.AlignVCenter; visible: root.newCount > 0; text: "Mark all known"; onClicked: root.markAllKnown() }
          Button { Layout.alignment: Qt.AlignVCenter; text: "Refresh"; enabled: !root.busy; onClicked: root.refreshWithFetch() }
        }

        Text { Layout.fillWidth: true; visible: root.errorText !== ""; textFormat: Text.PlainText; text: root.errorText; color: Color.urgent; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }

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
            implicitHeight: Math.max(repoRow.implicitHeight, itemRow.implicitHeight, candRow.implicitHeight)

            RepoSection {
              id: repoRow
              width: parent.width
              visible: delegateRoot.modelData.type === "repo"
              row: delegateRoot.modelData
              focused: root.cursor === delegateRoot.index
              onHovered: root.setCursor(delegateRoot.index)
              onCommitRequested: root.openCommit(delegateRoot.modelData.name)
              onPushRequested: root.pushRepo(delegateRoot.modelData.name)
              onPullRequested: root.pullRepo(delegateRoot.modelData.name)
            }

            ItemRow {
              id: itemRow
              width: parent.width
              visible: delegateRoot.modelData.type === "change" || delegateRoot.modelData.type === "health"
              row: delegateRoot.modelData
              focused: root.cursor === delegateRoot.index
              checked: root.checkedPaths[delegateRoot.modelData.key] !== false
              showCheckbox: delegateRoot.modelData.type === "change"
              showAction: delegateRoot.modelData.type === "health"
              onHovered: root.setCursor(delegateRoot.index)
              onToggled: function(value) { root.setChecked(delegateRoot.modelData.key, value) }
              onActivated: root.activateRow(delegateRoot.modelData)
              onActionClicked: root.restowPackage(delegateRoot.modelData.repo, delegateRoot.modelData.package)
            }

            CandidateRow {
              id: candRow
              width: parent.width
              visible: delegateRoot.modelData.type === "candidate"
              row: delegateRoot.modelData
              focused: root.cursor === delegateRoot.index
              packageName: Model.packageFor(delegateRoot.modelData, root.packageOverrides)
              header: String(delegateRoot.modelData.header || "")
              showBulk: delegateRoot.modelData.showBulk === true
              onHovered: root.setCursor(delegateRoot.index)
              onAdoptRequested: root.adoptCandidate(delegateRoot.modelData)
              onIgnoreRequested: root.ignoreCandidate(delegateRoot.modelData)
              onPickRequested: root.openPicker(delegateRoot.modelData)
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
      confirmError: root.confirmError
      commitRepo: root.commitRepo
      commitPathCount: root.commitPaths.length
      commitMessage: root.commitMessage
      commitSecrets: root.commitSecrets
      commitAllowSecrets: root.commitAllowSecrets
      commitError: root.commitError
      diffTitle: root.diffTitle
      diffBody: root.diffBody
      diffTruncated: root.diffTruncated
      pickerPath: root.pickerPath
      pickerValue: root.pickerValue
      pickerOptions: root.pickerOptions
      busy: root.busy
      onConfirmed: root.overlayConfirm()
      onCanceled: root.overlayCancel()
      onCommitMessageEdited: function(text) { root.commitMessage = text }
      onPickerValueEdited: function(value) { root.pickerValue = value }
      onCommitAccepted: root.confirmCommit()
    }
  }
}
