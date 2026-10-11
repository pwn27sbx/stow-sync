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
  property string selectedUrl: ""
  property var connectEntries: []
  property bool connectRunning: false
  property var plan: null
  property bool planLoading: false
  property var expanded: ({})
  property string focusedKey: ""
  property var progress: null
  property var report: null
  property string undoSentence: ""
  property var postChecked: ({})
  property bool busy: false
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)
  signal checkAgainRequested()
  signal repoPicked(string url)
  signal groupToggled(string key)
  signal undoRequested()

  readonly property var prereqRows: Model.setupPrereqRows(root.prereqs)
  readonly property var prereqReady: Model.setupPrereqReady(root.prereqs)
  readonly property var connectRows: Model.setupConnectRows(root.connectEntries)
  readonly property var progressRows: Model.setupProgressRows(root.progress)
  readonly property int progressDone: root.progress ? Number(root.progress.done) || 0 : 0
  readonly property int progressTotal: root.progress ? Number(root.progress.total) || 0 : 0
  readonly property bool showPicker: root.repoPicker.length > 0 && !root.connectRunning && root.connectEntries.length === 0

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  function statusGlyph(status) {
    if (status === "done") return "\uf00c"
    if (status === "failed") return "\uf00d"
    if (status === "skipped") return "\uf05e"
    if (status === "running") return "\uf110"
    return "\uf10c"
  }

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
      visible: root.showPicker
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
            selected: String(modelData.value || "") === root.selectedUrl
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
            text: root.statusGlyph(String(modelData.status))
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
    expanded: root.expanded
    focusedKey: root.focusedKey
    busy: root.busy
    foreground: root.foreground
    onPostToggled: function(id, value) { root.postToggled(id, value) }
    onGroupToggled: function(key) { root.groupToggled(key) }
  }

  // ---- Step 3: Apply ---------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 3
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Setting up this machine\u2026" + (root.progressTotal > 0 ? "  " + root.progressDone + "/" + root.progressTotal : "")
      color: root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Repeater {
      model: root.progressRows

      RowLayout {
        required property var modelData
        width: parent.width
        spacing: Style.spacing.md

        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: root.statusGlyph(String(modelData.status))
          color: modelData.status === "done" ? Color.accent : (modelData.status === "failed" ? Color.urgent : Util.alpha(root.foreground, 0.72))
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(modelData.label || "")
          color: modelData.status === "waiting" ? Util.alpha(root.foreground, 0.6) : root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
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
}
