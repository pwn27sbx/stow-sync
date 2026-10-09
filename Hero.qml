import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Fixed top of the panel: one large state glyph, one plain sentence, one hint
// line, the single primary button and the last action result. It never
// scrolls, so the state is always visible.
Item {
  id: root

  property string glyph: ""
  property string title: ""
  property string hint: ""
  property string tone: "muted"
  property string primaryLabel: ""
  property bool primaryVisible: false
  property bool primaryEnabled: true
  property bool busy: false
  property string busyLabel: "Working…"
  property string resultText: ""
  property bool resultError: false
  property bool refreshEnabled: true
  property color foreground: Color.foreground

  signal primaryClicked()
  signal refreshClicked()

  function toneColor() {
    if (root.tone === "urgent") return Color.urgent
    if (root.tone === "accent") return Color.accent
    return Color.muted
  }

  implicitHeight: column.implicitHeight

  ColumnLayout {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.spacing.sm

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(12)

      Text {
        id: glyphText
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: root.glyph
        color: root.toneColor()
        font.family: Style.font.family
        font.pixelSize: Style.font.display
      }

      ColumnLayout {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        spacing: Style.space(2)

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.title
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.title
          font.bold: true
          wrapMode: Text.WordWrap
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.hint
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        // U+F021 (Font Awesome refresh).
        iconText: "\uf021"
        tooltipText: "Refresh (r)"
        enabled: root.refreshEnabled && !root.busy
        onClicked: root.refreshClicked()
      }

      Button {
        id: primaryButton
        Layout.alignment: Qt.AlignVCenter
        visible: root.primaryVisible
        text: root.busy ? root.busyLabel : root.primaryLabel
        // U+F110 (Font Awesome spinner) rotates while an action is running.
        iconText: root.busy ? "\uf110" : ""
        iconSpinning: root.busy
        enabled: root.primaryEnabled && !root.busy
        onClicked: root.primaryClicked()
      }
    }

    // One-line result of the last action; errors stay until the next success.
    Text {
      Layout.fillWidth: true
      visible: root.resultText !== ""
      textFormat: Text.PlainText
      text: root.resultText
      color: root.resultError ? Color.urgent : Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
  }
}
