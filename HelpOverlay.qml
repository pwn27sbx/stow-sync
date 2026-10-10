import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Help on demand: a small "? keys" button bottom-right toggles an overlay that
// lists every shortcut. The overlay is dismissible by clicking the scrim or
// pressing Esc (the panel routes Esc here first while it is open).
Item {
  id: root

  property bool motion: true
  property color foreground: Color.foreground
  property bool open: false

  signal toggleRequested()
  signal closeRequested()

  property var keys: [
    { key: "1-3", action: "Tabs" },
    { key: "r", action: "Refresh from GitHub" },
    { key: "p", action: "Publish changes" },
    { key: "u", action: "Update from GitHub" },
    { key: "a", action: "Adopt a new config" },
    { key: "i", action: "Ignore the focused file" },
    { key: "\u2191\u2193 / j k", action: "Move" },
    { key: "\u2190\u2192 / h l", action: "Switch tabs" },
    { key: "Tab", action: "Next section" },
    { key: "Esc", action: "Back / close" }
  ]

  // The toggle button now lives in the header (icon button, tooltip "Keys (?)");
  // this overlay only renders the key list.

  Rectangle {
    anchors.fill: parent
    visible: root.open
    color: Util.alpha(Color.background, 0.72)

    MouseArea {
      anchors.fill: parent
      onClicked: root.closeRequested()
    }

    BorderSurface {
      width: Math.min(parent.width - Style.space(24), Style.space(300))
      implicitHeight: helpColumn.implicitHeight + Style.space(16) * 2
      anchors.centerIn: parent
      color: Color.popups.background
      borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
      radius: Style.space(10)

      Column {
        id: helpColumn
        anchors.centerIn: parent
        width: parent.width - Style.space(16) * 2
        spacing: Style.spacing.sm

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: "Keyboard shortcuts"
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Repeater {
          model: root.keys

          RowLayout {
            required property var modelData
            width: helpColumn.width
            spacing: Style.spacing.lg

            Text {
              Layout.preferredWidth: Style.space(72)
              textFormat: Text.PlainText
              text: String(modelData.key)
              color: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }

            Text {
              Layout.fillWidth: true
              textFormat: Text.PlainText
              text: String(modelData.action)
              color: Util.alpha(root.foreground, 0.72)
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
          }
        }
      }
    }
  }
}
