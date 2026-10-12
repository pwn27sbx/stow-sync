pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Opt-in "Set up this machine" wizard shell (README 8b/10b). Renders the state
// machine in SetupFlow.qml: five steps (Check, Connect, Review, Apply, Report)
// plus the "Setup backups" view. Only instantiated when machineSetup is true.
Item {
  id: root

  property bool opened: false
  property var settings: ({})
  property var statusData: null
  property bool busy: false
  property bool motion: true
  property color foreground: Color.foreground
  property string progressPath: ""
  property var applyProgress: null
  // One fixed dialog height for every step (README 12c answer 1): the tallest
  // body measured so far, never shrinking, capped to the screen.
  property real measuredHeight: Style.space(520)

  function measureBody() {
    var content = chrome.height + buttonRow.height + Style.space(40)
    if (body.item) content += body.item.implicitHeight
    root.measuredHeight = Math.max(root.measuredHeight, content)
  }

  signal requested(string tag, var args)
  signal closed()
  signal undoConfirmRequested(string backup, string sentence)

  // True while the user types in the Connect URL field, so the panel's key
  // catcher never eats keystrokes (README 12c fix). Set by the picker.
  property bool urlFocused: false
  readonly property bool contentActiveFocus: root.urlFocused
  readonly property var backups: flow.backups
  readonly property bool reviewActive: flow.mode === "wizard" && flow.step === 2

  function handleResult(tag, payload) { flow.handleResult(tag, payload) }
  function handleFailure(tag, message) { flow.handleFailure(tag, message) }
  function openBackups() { flow.openBackups() }
  function primary() { flow.primary() }
  function back() { flow.back() }
  function reviewMove(dy) { flow.moveGroup(dy) }
  function reviewToggle() { flow.toggleGroupKey(flow.groupKey) }
  function scrollBy(dy) {
    // Let the step body consume the scroll first (the Apply list, finding 72).
    if (body.item && typeof body.item.scrollBy === "function" && body.item.scrollBy(dy)) return
    bodyArea.contentY = Math.max(0, Math.min(Math.max(0, bodyArea.contentHeight - bodyArea.height), bodyArea.contentY + dy))
  }

  function parseProgress(text) {
    // Bounded parse (README 11 hardening audit): the settled value never
    // carries a file larger than the cap.
    return Model.parseSetupProgress(text, Model.SETUP_PROGRESS_MAX_BYTES)
  }

  visible: opened
  onOpenedChanged: if (opened) flow.start()

  FileView {
    id: progressView
    path: root.progressPath
    watchChanges: false
    printErrors: false
    onLoaded: root.applyProgress = root.parseProgress(text())
    onLoadFailed: root.applyProgress = null
  }

  Timer {
    interval: 500
    running: flow.applying || flow.connectRunning
    repeat: true
    onTriggered: if (root.progressPath !== "") progressView.reload()
  }

  SetupFlow {
    id: flow
    settings: root.settings
    statusData: root.statusData
    onRequested: function(tag, args) { root.requested(tag, args) }
    onClosed: root.closed()
    onUndoConfirmRequested: function(backup, sentence) { root.undoConfirmRequested(backup, sentence) }
  }

  Connections {
    target: flow
    function onStepChanged() { Qt.callLater(root.measureBody) }
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.72)

    MouseArea { anchors.fill: parent; onClicked: if (!flow.running) root.closed() }

    BorderSurface {
      id: card
      width: Math.min(parent.width - Style.space(24), Style.space(560))
      height: Math.min(parent.height - Style.space(16), Math.max(Style.space(520), root.measuredHeight))
      anchors.centerIn: parent
      color: Color.popups.background
      borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
      padding: Style.space(16)
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: inner
        anchors.fill: parent
        anchors.margins: card.contentTopInset

        Column {
          id: chrome
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: Style.space(12) // title -> stepper (finding 63)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: flow.mode === "backups" ? "Setup backups" : "Set up this machine"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
          }

          SetupStepper {
            width: parent.width
            visible: flow.mode !== "backups"
            steps: flow.stepNames
            current: flow.step
            foreground: root.foreground
          }

          Text {
            width: parent.width
            visible: flow.errorText !== ""
            textFormat: Text.PlainText
            text: flow.errorText
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }
        }

        Flickable {
          id: bodyArea
          anchors.top: chrome.bottom
          anchors.topMargin: Style.space(16) // stepper block -> step content (finding 63)
          anchors.left: parent.left
          anchors.right: parent.right
          // End above the footer in every step so the last line is never hidden
          // under the buttons (finding 85): reserve the footer height by anchoring.
          anchors.bottom: buttonRow.top
          anchors.bottomMargin: Style.space(12)
          clip: true
          contentWidth: width
          contentHeight: body.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          Loader {
            id: body
            width: bodyArea.width
            sourceComponent: flow.mode === "backups" ? backupsView : wizardView
            onLoaded: Qt.callLater(root.measureBody)
          }
        }

        ScrollHint { anchors.left: bodyArea.left; anchors.right: bodyArea.right; anchors.bottom: bodyArea.bottom; flick: bodyArea; foreground: root.foreground }

        Row {
          id: buttonRow
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          // Every footer button shares one height and one vertical centre
          // (finding 86): the row takes the tallest implicit height and each
          // button is centred on it, so Undo/Done/Back align.
          height: Math.max(undoFooterButton.implicitHeight, backFooterButton.implicitHeight, primaryFooterButton.implicitHeight)
          spacing: Style.spacing.sm

          Button {
            id: undoFooterButton
            anchors.verticalCenter: parent.verticalCenter
            height: buttonRow.height
            text: "Undo this setup"
            iconText: "\uf0e2"
            foreground: Color.urgent
            bordered: true
            verticalPadding: Style.space(8)
            visible: flow.mode === "wizard" && flow.step === 4 && flow.applyResult !== null && String(flow.applyResult.backup || "") !== "" && flow.undoResult === null
            enabled: !root.busy
            onClicked: flow.requestUndo(String(flow.applyResult.backup || ""))
          }

          Button {
            id: backFooterButton
            anchors.verticalCenter: parent.verticalCenter
            height: buttonRow.height
            text: flow.backLabel()
            visible: flow.backLabel() !== "Close"
            opacity: flow.running ? 0.4 : 1
            verticalPadding: Style.space(8)
            enabled: !flow.running
            onClicked: flow.back()
          }

          Button {
            id: primaryFooterButton
            anchors.verticalCenter: parent.verticalCenter
            height: buttonRow.height
            text: flow.primaryLabel()
            // Filled accent primary action (README 12c finding 51).
            background: Color.accent
            foreground: Color.background
            horizontalPadding: Style.space(16)
            verticalPadding: Style.space(8)
            enabled: flow.primaryEnabled()
            onClicked: flow.primary()
          }
        }
      }
    }
  }

  Component {
    id: wizardView

    SetupStep {
      step: flow.step
      prereqs: flow.prereqs
      checking: flow.checking
      candidates: flow.candidates
      selectedUrl: flow.selectedUrl
      url: flow.url
      repoLoading: flow.repoLoading
      repoError: flow.repoError
      connectEntries: flow.connectEntries
      connectRunning: flow.connectRunning
      connectAuthError: flow.connectAuthError
      plan: flow.plan
      planLoading: flow.planLoading
      expanded: flow.groupsExpanded
      focusedKey: flow.groupKey
      progress: root.applyProgress
      bodyHeight: bodyArea.height
      report: flow.report
      undoResult: flow.undoResult
      undoError: flow.undoError
      postChecked: flow.postChecked
      busy: root.busy
      motion: root.motion
      foreground: root.foreground
      onPostToggled: function(id, value) { var next = {}; for (var k in flow.postChecked) next[k] = flow.postChecked[k]; next[id] = value; flow.postChecked = next }
      onCheckAgainRequested: flow.runCheck()
      onRepoPicked: function(url) { flow.url = url; flow.selectedUrl = url }
      onUrlEdited: function(text) { flow.url = text }
      onUrlFocusChanged: function(focused) { root.urlFocused = focused }
      onRepoRetryRequested: flow.retryRepos()
      onGroupToggled: function(key) { flow.toggleGroupKey(key) }
    }
  }

  Component {
    id: backupsView

    SetupBackups {
      rows: flow.backups
      undoResult: flow.undoResult
      undoError: flow.undoError
      busy: root.busy
      foreground: root.foreground
      onUndoRequested: function(id) { flow.requestUndo(id) }
      onDoneRequested: root.closed()
    }
  }
}
