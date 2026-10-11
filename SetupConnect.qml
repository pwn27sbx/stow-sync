pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Connect step body (README 11a.3 / 11b.2/11b.4): the gh repo picker, the
// "loading your repos" state with a retry, the live clone progress bar and the
// per-repo result checklist.
Column {
  id: root

  property var repoPicker: []
  property string selectedUrl: ""
  property bool repoLoading: false
  property string repoError: ""
  property var connectEntries: []
  property bool connectRunning: false
  property var clone: null
  property bool motion: true
  property color foreground: Color.foreground

  signal repoPicked(string url)
  signal repoRetryRequested()

  readonly property var connectRows: Model.setupConnectRows(root.connectEntries)
  readonly property bool showPicker: root.repoPicker.length > 0 && !root.repoLoading && root.repoError === "" && !root.connectRunning && root.connectEntries.length === 0

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
    if (status === "running") return "\uf110"
    return "\uf10c"
  }

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: "Cloning is safe and repeatable. Stow Sync downloads your dotfiles repo, reads its recipe and downloads the other repos it lists, one at a time."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Text {
    width: parent.width
    visible: root.repoLoading
    textFormat: Text.PlainText
    text: "Loading your GitHub repos\u2026"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  Column {
    width: parent.width
    visible: root.repoError !== "" && root.repoPicker.length === 0 && !root.connectRunning
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.repoError
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Button {
      text: "Retry"
      iconText: "\uf021"
      fontSize: Style.font.caption
      onClicked: root.repoRetryRequested()
    }
  }

  Column {
    width: parent.width
    visible: root.connectRunning && root.clone !== null
    spacing: Style.spacing.xs

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.clone !== null ? (String(root.clone.item) + "  \u00b7  " + String(root.clone.label)) : ""
      color: root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    SetupProgress {
      width: parent.width
      value: (root.clone !== null && root.clone.percent >= 0) ? root.clone.percent / 100 : -1
      active: root.connectRunning
      motion: root.motion
      foreground: root.foreground
    }
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
