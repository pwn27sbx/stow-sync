import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Segmented control: one rounded pill track with three equal segments. The
// active segment is a sliding filled pill that animates its x (160 ms,
// OutCubic). Number keys and arrows are handled by the panel; this component
// only renders the segments and reports clicks.
Item {
  id: root

  property var tabs: []
  property int current: 0
  property bool motion: true
  property color foreground: Color.foreground

  signal selected(int index)

  readonly property int count: Math.max(1, root.tabs.length)
  readonly property real segWidth: track.width / root.count
  readonly property int pad: Style.space(2)

  implicitHeight: track.height

  Rectangle {
    id: track
    anchors.left: parent.left
    anchors.right: parent.right
    height: Style.space(30)
    radius: Style.cornerRadius
    color: Util.alpha(Color.foreground, 0.06)
  }

  Rectangle {
    id: pill
    y: root.pad
    height: track.height - root.pad * 2
    x: root.current * root.segWidth + root.pad
    width: Math.max(0, root.segWidth - root.pad * 2)
    radius: Style.cornerRadius
    color: Util.alpha(Color.accent, 0.22)

    Behavior on x {
      enabled: root.motion
      NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }
  }

  Row {
    anchors.fill: track

    Repeater {
      model: root.tabs

      Item {
        required property var modelData
        required property int index
        width: root.segWidth
        height: track.height

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: String(modelData)
          color: root.current === index ? Color.accent : Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: root.current === index
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: root.selected(index)
        }
      }
    }
  }
}
