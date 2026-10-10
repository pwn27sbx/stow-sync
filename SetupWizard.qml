pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
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

  signal requested(string tag, var args)
  signal closed()
  signal undoConfirmRequested(string backup, string sentence)

  readonly property bool contentActiveFocus: urlField.activeFocus
  readonly property var backups: flow.backups

  function handleResult(tag, payload) { flow.handleResult(tag, payload) }
  function handleFailure(tag, message) { flow.handleFailure(tag, message) }
  function openBackups() { flow.openBackups() }
  function primary() { flow.primary() }
  function back() { flow.back() }

  visible: opened
  onOpenedChanged: if (opened) flow.start()

  SetupFlow {
    id: flow
    settings: root.settings
    statusData: root.statusData
    onRequested: function(tag, args) { root.requested(tag, args) }
    onClosed: root.closed()
    onUndoConfirmRequested: function(backup, sentence) { root.undoConfirmRequested(backup, sentence) }
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.72)

    MouseArea { anchors.fill: parent; onClicked: if (!flow.running) root.closed() }

    BorderSurface {
      id: card
      width: Math.min(parent.width - Style.space(24), Style.space(560))
      height: Math.min(parent.height - Style.space(16), Style.space(480))
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
          spacing: Style.spacing.sm

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: flow.mode === "backups" ? "Setup backups" : "Set up this machine"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: flow.stepLine
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          TextField {
            id: urlField
            width: parent.width
            visible: flow.mode === "wizard" && flow.step === 1
            text: flow.url
            placeholderText: "https://github.com/<you>/dotfiles.git"
            foreground: root.foreground
            onTextEdited: flow.url = text
            onAccepted: flow.primary()
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
          anchors.topMargin: Style.spacing.sm
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(Style.space(60), inner.height - chrome.height - buttonRow.height - Style.space(20))
          clip: true
          contentWidth: width
          contentHeight: body.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          Loader {
            id: body
            width: bodyArea.width
            sourceComponent: flow.mode === "backups" ? backupsView : wizardView
          }
        }

        Row {
          id: buttonRow
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          spacing: Style.spacing.sm

          Button {
            text: flow.backLabel()
            enabled: !flow.running
            onClicked: flow.back()
          }

          Button {
            text: flow.primaryLabel()
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
      repoPicker: flow.repoPicker
      connectEntries: flow.connectEntries
      connectRunning: flow.connectRunning
      plan: flow.plan
      planLoading: flow.planLoading
      stepRows: flow.stepRows
      report: flow.report
      undoSentence: flow.undoSentence
      postChecked: flow.postChecked
      busy: root.busy
      foreground: root.foreground
      onPostToggled: function(id, value) { var next = {}; for (var k in flow.postChecked) next[k] = flow.postChecked[k]; next[id] = value; flow.postChecked = next }
      onCheckAgainRequested: flow.runCheck()
      onRepoPicked: function(url) { flow.url = url }
      onUndoRequested: flow.requestUndo(flow.applyResult ? flow.applyResult.backup : "")
    }
  }

  Component {
    id: backupsView

    SetupBackups {
      rows: flow.backups
      busy: root.busy
      foreground: root.foreground
      onUndoRequested: function(id) { flow.requestUndo(id) }
      onDoneRequested: root.closed()
    }
  }
}
