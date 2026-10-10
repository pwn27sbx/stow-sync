import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Overview banner shown only while `machineSetup` is on and a configured repo is
// missing on disk: "This machine is not set up yet · Set up".
Item {
  id: root

  property color foreground: Color.foreground
  signal setupRequested()

  implicitHeight: banner.implicitHeight

  BorderSurface {
    id: banner
    width: parent.width
    implicitHeight: row.implicitHeight + Style.spacing.lg * 2
    color: Util.alpha(Color.accent, 0.10)
    borderSpec: Border.none()
    radius: Style.space(10)

    RowLayout {
      id: row
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.spacing.xxl
      anchors.rightMargin: Style.spacing.xxl
      spacing: Style.spacing.lg

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "This machine is not set up yet"
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideRight
      }

      Text {
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: "Set up"
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }

    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.setupRequested() }
  }
}
