import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One row inside a GroupCard: optional checkbox, optional status chip, a
// primary line, a muted secondary line and an optional action button. The
// panel computes the display strings; this component only renders them.
Item {
  id: root

  property string primary: ""
  property string secondary: ""
  property string chip: ""
  property string chipTone: "accent"
  property string header: ""
  property bool focused: false
  property bool checked: true
  property bool showCheckbox: false
  property bool showAction: false
  property string actionText: "Fix"
  property bool dimmed: false
  property color foreground: Color.foreground

  signal hovered()
  signal toggled(bool value)
  signal activated()
  signal actionClicked()

  function chipColor() {
    if (root.chipTone === "urgent") return Color.urgent
    if (root.chipTone === "muted") return Color.muted
    return Color.accent
  }

  implicitHeight: column.implicitHeight

  Column {
    id: column
    width: parent.width
    spacing: Style.spacing.xxs

    Text {
      width: parent.width
      visible: root.header !== ""
      textFormat: Text.PlainText
      text: root.header
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
      elide: Text.ElideRight
    }

    BorderSurface {
      id: card
      width: parent.width
      implicitHeight: Math.max(Style.spacing.controlHeight, content.implicitHeight + Style.spacing.sm)
      color: root.focused ? Util.alpha(Color.accent, 0.16) : "transparent"
      borderSpec: Border.none()
      radius: Style.cornerRadius
      opacity: root.dimmed ? 0.55 : 1.0

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: root.hovered()
        onClicked: root.activated()
      }

      RowLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.controlPaddingX
        anchors.rightMargin: Style.spacing.controlPaddingX
        spacing: Style.spacing.sm

        Rectangle {
          Layout.alignment: Qt.AlignVCenter
          visible: root.showCheckbox
          Layout.preferredWidth: Style.space(14)
          Layout.preferredHeight: Style.space(14)
          radius: Style.cornerRadius
          color: root.checked ? Color.accent : "transparent"
          border.width: 1
          border.color: root.checked ? Color.accent : Util.alpha(root.foreground, 0.5)

          MouseArea {
            anchors.fill: parent
            onClicked: root.toggled(!root.checked)
          }
        }

        Rectangle {
          Layout.alignment: Qt.AlignVCenter
          visible: root.chip !== ""
          Layout.preferredWidth: Style.space(16)
          Layout.preferredHeight: Style.space(16)
          radius: Style.cornerRadius
          color: Util.alpha(root.chipColor(), 0.16)
          border.width: 1
          border.color: Util.alpha(root.chipColor(), 0.6)

          Text {
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: root.chip
            color: root.chipColor()
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
          }
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: 0

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.primary
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideMiddle
          }

          Text {
            Layout.fillWidth: true
            visible: root.secondary !== ""
            textFormat: Text.PlainText
            text: root.secondary
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          visible: root.showAction
          text: root.actionText
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          onClicked: root.actionClicked()
        }
      }
    }
  }
}
