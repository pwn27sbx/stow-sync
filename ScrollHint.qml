import QtQuick
import qs.Commons

// Bottom fade + chevron cue for a Flickable that has more content below
// (README Unit 15b/finding 85, refined by Unit 15f/finding 92): the fade covers
// the content's bottom band and the chevron sits in the 12 px gap above the
// footer, never over a sliced line. Hides itself when the content fits or is
// scrolled to the bottom. Theme colours only.
Rectangle {
  id: root

  property var flick: null
  property color foreground: Color.foreground

  readonly property bool more: root.flick
    ? (root.flick.contentHeight > root.flick.height + 1 && root.flick.contentY < root.flick.contentHeight - root.flick.height - 1)
    : false

  // 24 px over the content bottom + the 12 px footer gap below it.
  height: Style.space(24) + Style.space(12)
  color: "transparent"
  visible: root.more

  Rectangle {
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    height: Style.space(24)
    gradient: Gradient {
      GradientStop { position: 0.0; color: Util.alpha(Color.popups.background, 0.0) }
      GradientStop { position: 1.0; color: Color.popups.background }
    }
  }

  // The chevron lives in the footer gap, not over the content.
  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    text: "\uf078"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
