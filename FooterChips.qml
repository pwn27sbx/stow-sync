import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Keyboard hint strip pinned under the scrolling content. One bordered chip
// per hint, so the shortcuts stay visible without competing with the content.
Item {
  id: root

  property var chips: ["1-3 tabs", "r refresh", "p publish", "u update", "Esc close"]
  property color foreground: Color.foreground

  implicitHeight: row.implicitHeight

  RowLayout {
    id: row
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.spacing.xs

    Repeater {
      model: root.chips

      BorderSurface {
        required property string modelData
        Layout.alignment: Qt.AlignVCenter
        implicitHeight: chipText.implicitHeight + Style.spacing.xxs * 2
        implicitWidth: chipText.implicitWidth + Style.spacing.sm * 2
        color: Util.alpha(Color.foreground, 0.04)
        borderSpec: Border.controlSpec("normal", Util.alpha(root.foreground, 0.45), Color.accent)
        radius: Style.cornerRadius

        Text {
          id: chipText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: modelData
          color: Util.alpha(root.foreground, 0.8)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }

    Item { Layout.fillWidth: true }
  }
}
