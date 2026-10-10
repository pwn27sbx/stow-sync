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
    radius: Style.cornerRadius
    color: Util.alpha(Color.foreground, 0.06)
    borderSpec: Border.none()

    RowLayout {
      id: content
      anchors.centerIn: parent
      spacing: 0

      Text {
        Layout.alignment: Qt.AlignVCenter
        Layout.rightMargin: root.icon !== "" ? Style.spacing.sm : 0
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

      // Count badge inline after the label: Style.space(6) spacing, vertically
      // centered, so it never overlaps the pill border or the label; the pill
      // grows to fit any count.
      Rectangle {
        id: badge
        Layout.alignment: Qt.AlignVCenter
        Layout.leftMargin: root.badgeText !== "" ? Style.space(6) : 0
        visible: root.badgeText !== ""
        implicitWidth: Math.max(Style.space(14), badgeText.implicitWidth + Style.space(6))
        implicitHeight: Style.space(14)
        radius: Style.cornerRadius
        color: Color.accent

        Text {
          id: badgeText
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
}
