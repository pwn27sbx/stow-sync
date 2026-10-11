import QtQuick
import qs.Commons
import qs.Ui

// One progress component shared by Connect and Apply (README 11b.1). A
// full-width track clipped to its bounds; the fill is determinate when a
// percent is known and an indeterminate segment sliding inside the track
// otherwise. Theme colours, one corner radius, gated by `motion`.
Item {
  id: root

  property real value: -1 // 0..1 determinate; < 0 indeterminate
  property bool active: true
  property bool motion: true
  property color foreground: Color.foreground

  implicitHeight: Style.space(6)

  Rectangle {
    id: track
    width: parent.width
    height: parent.height
    radius: Style.cornerRadius
    color: Util.alpha(root.foreground, 0.12)
    clip: true

    Rectangle {
      id: determinate
      x: 0
      height: parent.height
      radius: Style.cornerRadius
      color: Color.accent
      visible: root.active && root.value >= 0
      width: Math.max(2, Math.min(1, root.value) * track.width)
    }

    Rectangle {
      id: segment
      height: parent.height
      radius: Style.cornerRadius
      color: Color.accent
      visible: root.active && root.value < 0
      width: Math.round(track.width * 0.3)

      SequentialAnimation on x {
        running: root.active && root.motion && root.value < 0
        loops: Animation.Infinite
        NumberAnimation { from: -segment.width; to: track.width; duration: 1100; easing.type: Easing.InOutSine }
      }
    }
  }
}
