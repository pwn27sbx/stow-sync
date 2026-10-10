pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Body of the setup wizard, one branch per step. Pure rendering: every value
// comes from SetupWizard.qml, every interaction leaves through a signal.
Column {
  id: root

  property int step: 0
  property var prereqs: null
  property bool checking: false
  property var repoPicker: []
  property var connectEntries: []
  property bool connectRunning: false
  property var plan: null
  property bool planLoading: false
  property var stepRows: []
  property var report: null
  property string undoSentence: ""
  property var postChecked: ({})
  property bool busy: false
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)
  signal checkAgainRequested()
  signal repoPicked(string url)
  signal undoRequested()

  readonly property var prereqRows: Model.setupPrereqRows(root.prereqs)
  readonly property var prereqReady: Model.setupPrereqReady(root.prereqs)
  readonly property var connectRows: Model.setupConnectRows(root.connectEntries)

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  // ---- Step 0: Check ---------------------------------------------------
  SetupCheck {
    width: parent.width
    visible: root.step === 0
    rows: root.prereqRows
    ready: root.prereqReady
    checking: root.checking
    foreground: root.foreground
    onResendRequested: root.checkAgainRequested()
  }

  // ---- Step 1: Connect -------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 1
    spacing: Style.spacing.lg

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Cloning is safe and repeatable. Stow Sync downloads your dotfiles repo, reads its recipe and downloads the other repos it lists, one at a time."
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Column {
      width: parent.width
      visible: root.repoPicker.length > 0
      spacing: Style.spacing.xs

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: "Your GitHub repos"
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Flow {
        width: parent.width
        spacing: Style.spacing.xs

        Repeater {
          model: root.repoPicker

          Button {
            required property var modelData
            text: String(modelData.label || "") + (modelData.likely ? " \u2605" : "") + (String(modelData.detail || "") !== "" ? " \u00b7 " + String(modelData.detail) : "")
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(3)
            onClicked: root.repoPicked(String(modelData.value || ""))
          }
        }
      }
    }

    Column {
      width: parent.width
      visible: root.connectRows.length > 0
      spacing: Style.spacing.xs

      Repeater {
        model: root.connectRows

        RowLayout {
          required property var modelData
          width: parent.width
          spacing: Style.spacing.md

          Text {
            Layout.alignment: Qt.AlignVCenter
            textFormat: Text.PlainText
            text: modelData.status === "done" ? "\uf00c" : (modelData.status === "failed" ? "\uf00d" : (modelData.status === "running" ? "\uf110" : "\uf10c"))
            color: modelData.status === "done" ? Color.accent : (modelData.status === "failed" ? Color.urgent : Util.alpha(root.foreground, 0.72))
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(modelData.label || "")
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }

          Text {
            Layout.maximumWidth: Style.space(280)
            textFormat: Text.PlainText
            text: String(modelData.detail || "")
            color: root.toneColor(String(modelData.tone || "muted"))
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignRight
          }
        }
      }
    }
  }

  // ---- Step 2: Review --------------------------------------------------
  SetupReview {
    width: parent.width
    visible: root.step === 2
    plan: root.plan
    planLoading: root.planLoading
    postChecked: root.postChecked
    busy: root.busy
    foreground: root.foreground
    onPostToggled: function(id, value) { root.postToggled(id, value) }
  }

  // ---- Step 3: Apply ---------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 3
    spacing: Style.spacing.md

    RowLayout {
      width: parent.width
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "Setting up this machine\u2026"
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Item {
        Layout.preferredWidth: Style.space(44)
        Layout.preferredHeight: Style.space(10)

        Rectangle {
          width: Style.space(8)
          height: width
          radius: width / 2
          y: (parent.height - height) / 2
          color: Color.accent
          visible: root.busy

          SequentialAnimation on x {
            running: root.busy
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 36; duration: 600; easing.type: Easing.InOutSine }
            NumberAnimation { from: 36; to: 0; duration: 600; easing.type: Easing.InOutSine }
          }
        }
      }
    }
  }

  // ---- Step 4: Report --------------------------------------------------
  SetupReport {
    width: parent.width
    visible: root.step === 4
    report: root.report
    undoSentence: root.undoSentence
    undoVisible: root.report !== null && root.report.backup !== ""
    busy: root.busy
    foreground: root.foreground
    onUndoRequested: root.undoRequested()
  }

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }
}
