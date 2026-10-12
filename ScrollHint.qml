import QtQuick
import qs.Commons

// Bottom fade + chevron cue for a Flickable that has more content below
// (README Unit 15b/finding 85): a long list never ends in a sliced line with no
// sign that it scrolls. Hides itself when the content fits or is scrolled to the
// bottom. Theme colours only; the fade uses the popup background.
Rectangle {
  id: root

  property var flick: null
  property color foreground: Color.foreground

  readonly property bool more: root.flick
    ? (root.flick.contentHeight > root.flick.height + 1 && root.flick.contentY < root.flick.contentHeight - root.flick.height - 1)
    : false

  height: Style.space(24)
  visible: root.more

  gradient: Gradient {
    GradientStop { position: 0.0; color: Util.alpha(Color.popups.background, 0.0) }
    GradientStop { position: 1.0; color: Color.popups.background }
  }

  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(2)
    text: "\uf078"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
