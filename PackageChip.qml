import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One package chip in the Packages grid: a rounded chip with the package icon,
// its name and a small file count. Healthy packages get a plain foreground
// fill; a package with changes gets the accent outline; an unhealthy package
// gets the urgent outline.
BorderSurface {
  id: root

  property var card: null
  property var state: ({})
  property bool expanded: false
  property bool motion: true
  property color foreground: Color.foreground

  signal toggled()

  readonly property var chip: root.card || ({})
  readonly property color outlineColor: String(root.state.outlineTone || "") === "urgent" ? Color.urgent : Color.accent

  implicitWidth: row.implicitWidth + Style.spacing.xxl * 2
  implicitHeight: row.implicitHeight + Style.spacing.lg * 2
  radius: Style.cornerRadius
  color: Util.alpha(root.foreground, root.state.fillAlpha === undefined ? 0.06 : root.state.fillAlpha)
  borderSpec: root.state.outline === true ? Border.flat(root.outlineColor, Style.normalBorderWidth) : Border.none()

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.toggled()
  }

  RowLayout {
    id: row
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.spacing.xxl
    anchors.rightMargin: Style.spacing.xxl
    spacing: Style.spacing.sm

    Text {
      Layout.alignment: Qt.AlignVCenter
      textFormat: Text.PlainText
      text: String(root.chip.icon || "")
      color: root.outlineColor
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignVCenter
      textFormat: Text.PlainText
      text: String(root.chip.name || "")
      color: root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
      textFormat: Text.PlainText
      text: String(root.chip.count === undefined ? 0 : root.chip.count)
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}
