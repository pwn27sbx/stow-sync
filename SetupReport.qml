pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Report step body of the setup wizard (README 10b.6/finding 22). Grouped
// results, the backup folder path (selectable, copyable), every post step with
// its last line, the notes again, and the destructive Undo button.
Column {
  id: root

  property var report: null
  property string undoSentence: ""
  property bool undoVisible: false
  property bool busy: false
  property color foreground: Color.foreground

  signal undoRequested()

  readonly property var sections: (root.report && root.report.sections) || []

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  function copyText(text) {
    if (String(text) !== "") Util.execArgv(["wl-copy", String(text)])
  }

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: "Setup finished. Everything below is what Stow Sync did on this machine."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  RowLayout {
    width: parent.width
    visible: root.report !== null && String(root.report.backupDir || "") !== ""
    spacing: Style.spacing.sm

    TextEdit {
      Layout.fillWidth: true
      Layout.preferredHeight: implicitHeight
      text: String(root.report ? root.report.backupDir : "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: "monospace"
      font.pixelSize: Style.font.caption
      readOnly: true
      selectByMouse: true
      wrapMode: TextEdit.NoWrap
      clip: true
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Copy"
      iconText: "\uf0c5"
      fontSize: Style.font.caption
      onClicked: root.copyText(String(root.report ? root.report.backupDir : ""))
    }
  }

  Repeater {
    model: root.sections

    Column {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.xs

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: String(modelData.title || "")
        color: root.toneColor(String(modelData.tone || "muted"))
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }

      Repeater {
        model: modelData.items

        RowLayout {
          required property var modelData
          width: parent.width
          spacing: Style.spacing.md

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(modelData.label || "")
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: modelData.tone === "muted" && String(modelData.detail || "") === "" ? Text.WordWrap : Text.NoWrap
            elide: modelData.tone === "muted" && String(modelData.detail || "") === "" ? Text.ElideNone : Text.ElideRight
          }

          Text {
            Layout.maximumWidth: Style.space(200)
            visible: String(modelData.detail || "") !== ""
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

  Column {
    width: parent.width
    visible: root.undoVisible
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: String(root.undoSentence || "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    Button {
      text: "Undo this setup"
      iconText: "\uf0e2"
      foreground: Color.urgent
      bordered: true
      fontSize: Style.font.caption
      enabled: !root.busy
      onClicked: root.undoRequested()
    }
  }

  Text {
    width: parent.width
    visible: root.report !== null && root.report.backup !== ""
    textFormat: Text.PlainText
    text: "Backup " + String(root.report ? root.report.backup : "")
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
