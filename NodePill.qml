import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One node of the sync bridge: a rounded pill with a label and an optional
// count badge. The "This PC" node carries the badge when local changes exist.
Item {
  id: root

  property string label: ""
  property string badgeText: ""
  property string icon: ""
  property color tone: Color.accent
  property color foreground: Color.foreground

  implicitWidth: content.implicitWidth + Style.spacing.lg * 2
  implicitHeight: pill.implicitHeight

  BorderSurface {
    id: pill
    width: parent.width
    implicitHeight: content.implicitHeight + Style.spacing.lg * 2
    radius: 999
    color: Util.alpha(Color.foreground, 0.06)
    borderSpec: Border.none()

    RowLayout {
      id: content
      anchors.centerIn: parent
      spacing: Style.spacing.sm

      Text {
        Layout.alignment: Qt.AlignVCenter
        visible: root.icon !== ""
        textFormat: Text.PlainText
        text: root.icon
        color: root.tone
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Text {
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: root.label
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }

    Rectangle {
      visible: root.badgeText !== ""
      width: Math.max(Style.space(14), badge.implicitWidth + Style.space(6))
      height: Style.space(14)
      radius: height / 2
      color: Color.accent
      anchors.horizontalCenter: parent.right
      anchors.verticalCenter: parent.top

      Text {
        id: badge
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: root.badgeText
        color: Color.background
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }
}
