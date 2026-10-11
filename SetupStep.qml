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
  property bool repoLoading: false
  property string repoError: ""
  property var connectEntries: []
  property bool connectRunning: false
  property var plan: null
  property bool planLoading: false
  property var expanded: ({})
  property string focusedKey: ""
  property var progress: null
  property var report: null
  property var undoResult: null
  property string undoSentence: ""
  property var postChecked: ({})
  property bool busy: false
  property bool motion: true
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)
  signal checkAgainRequested()
  signal repoPicked(string url)
  signal repoRetryRequested()
  signal groupToggled(string key)
  signal undoRequested()

  readonly property var prereqRows: Model.setupPrereqRows(root.prereqs)
  readonly property var prereqReady: Model.setupPrereqReady(root.prereqs)
  readonly property var progressRows: Model.setupProgressRows(root.progress)
  readonly property var clone: Model.setupCloneProgress(root.progress)
  readonly property int progressDone: root.progress ? Number(root.progress.done) || 0 : 0
  readonly property int progressTotal: root.progress ? Number(root.progress.total) || 0 : 0

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

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
  SetupConnect {
    width: parent.width
    visible: root.step === 1
    repoPicker: root.repoPicker
    selectedUrl: root.selectedUrl
    repoLoading: root.repoLoading
    repoError: root.repoError
    connectEntries: root.connectEntries
    connectRunning: root.connectRunning
    clone: root.clone
    motion: root.motion
    foreground: root.foreground
    onRepoPicked: function(url) { root.repoPicked(url) }
    onRepoRetryRequested: root.repoRetryRequested()
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

    SetupProgress {
      width: parent.width
      value: root.progressTotal > 0 ? root.progressDone / root.progressTotal : -1
      active: true
      motion: root.motion
      foreground: root.foreground
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
    undoResult: root.undoResult
    undoSentence: root.undoSentence
    undoVisible: root.report !== null && root.report.backup !== ""
    busy: root.busy
    foreground: root.foreground
    onUndoRequested: root.undoRequested()
  }
}
