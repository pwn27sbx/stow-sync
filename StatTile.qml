import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One equal-width Overview stat tile: icon, big number and a small muted
// label. The panel keeps the last values visible while loading (it dims the
// whole row instead of blanking the numbers).
BorderSurface {
  id: root

  property string icon: ""
  property string value: ""
  property string label: ""
  property string tone: "muted"
  property color foreground: Color.foreground

  function toneColor() {
    if (root.tone === "urgent") return Color.urgent
    if (root.tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.5)
  }

  implicitHeight: column.implicitHeight + Style.spacing.sm * 2
  color: Util.alpha(Color.foreground, 0.04)
  borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
  radius: Style.cornerRadius

  Column {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.spacing.xxs

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: root.icon
      color: root.toneColor()
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: root.value
      color: root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
      font.bold: true
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: root.label
      color: Util.alpha(root.foreground, 0.8)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}
