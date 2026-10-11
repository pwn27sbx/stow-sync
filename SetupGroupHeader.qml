pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Shared collapsible summary row for the setup wizard (Review and Report,
// README 11a.1 / 11d.4): a chevron, a bold title, a right-aligned count, a
// full-row click target and a hover/focus fill. Pure rendering: the toggle
// leaves through `toggled`.
Rectangle {
  id: root

  property string title: ""
  property int count: -1
  property string unit: ""
  property string tone: "muted"
  property bool expanded: false
  property bool focused: false
  property color foreground: Color.foreground

  signal toggled()
  signal hoverChanged(bool hovered)

  function toneColor(token) {
    if (token === "urgent") return Color.urgent
    if (token === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  width: parent ? parent.width : 0
  implicitHeight: headerRow.implicitHeight + Style.spacing.sm
  radius: Style.cornerRadius
  color: root.focused ? Util.alpha(root.foreground, 0.06) : "transparent"

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    hoverEnabled: true
    onEntered: root.hoverChanged(true)
    onExited: root.hoverChanged(false)
    onClicked: root.toggled()
  }

  RowLayout {
    id: headerRow
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.spacing.sm
    anchors.rightMargin: Style.spacing.sm
    spacing: Style.spacing.sm

    Text {
      Layout.alignment: Qt.AlignVCenter
      textFormat: Text.PlainText
      // Font Awesome chevrons; caption size rendered as a dot (finding 37).
      text: root.expanded ? "\uf078" : "\uf054"
      color: root.toneColor(root.tone)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Text {
      Layout.fillWidth: true
      textFormat: Text.PlainText
      text: root.title
      color: root.toneColor(root.tone)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      Layout.alignment: Qt.AlignVCenter
      visible: root.count >= 0
      textFormat: Text.PlainText
      text: String(root.count) + (root.unit !== "" ? " " + root.unit : "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}
