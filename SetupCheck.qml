pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Check step body of the setup wizard (README 10b.3). One row per prerequisite
// with a check/cross, its detail and the exact fix command in a selectable mono
// text with a copy button. "Check again" re-runs setup-prereqs.
Column {
  id: root

  property var rows: []
  property bool ready: false
  property bool checking: false
  property color foreground: Color.foreground

  signal resendRequested()

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function copyFix(text) {
    if (String(text) !== "") Util.execArgv(["wl-copy", String(text)])
  }

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: root.checking ? "Checking what this machine needs\u2026" : "Before downloading anything, Stow Sync checks the tools it needs."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Repeater {
    model: root.rows

    RowLayout {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.md

      Text {
        Layout.alignment: Qt.AlignTop
        textFormat: Text.PlainText
        text: modelData.ok ? "\uf00c" : "\uf00d"
        color: modelData.ok ? Color.accent : Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(modelData.label || "")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: modelData.ok ? Util.alpha(root.foreground, 0.72) : Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        RowLayout {
          Layout.fillWidth: true
          visible: !modelData.ok && String(modelData.fix || "") !== ""
          spacing: Style.spacing.sm

          TextEdit {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            text: String(modelData.fix || "")
            color: Color.accent
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
            onClicked: root.copyFix(String(modelData.fix || ""))
          }
        }
      }
    }
  }

  Button {
    text: "Check again"
    iconText: "\uf021"
    fontSize: Style.font.caption
    // Only offer "Check again" once the current check finished (finding 62).
    visible: !root.checking
    enabled: !root.checking
    onClicked: root.resendRequested()
  }
}
