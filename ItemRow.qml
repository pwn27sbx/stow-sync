import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One change row (checkbox + file path) or one stow-health row (Fix button).
// A change row may carry a group header ("dotfiles  ›  fish") stamped by the
// model above it. Enter opens a diff (change) or the restow confirm (health).
Item {
  id: root

  property var row: null
  property int rowIndex: 0
  property bool focused: false
  property bool checked: true
  property bool showCheckbox: false
  property bool showAction: false
  property string actionText: "Fix"
  property string header: ""
  property color foreground: Color.foreground

  signal hovered(int index)
  signal activated()
  signal toggled(bool value)
  signal actionClicked()

  readonly property bool isHealth: root.row !== null && root.row.type === "health"
  readonly property bool isGroup: root.row !== null && root.row.type === "group"
  readonly property string primary: root.row === null ? ""
    : (root.isGroup ? String(root.row.label) : (root.isHealth ? String(root.row.packageLabel) : String(root.row.path)))
  readonly property string secondary: root.isGroup ? (root.row.expanded ? "Click to hide" : "Click to show")
    : (root.isHealth ? root.healthDetail() : root.changeDetail())

  function tokenColor(token) {
    if (token === "urgent") return Color.urgent
    if (token === "accent") return Color.accent
    if (token === "muted") return Color.muted
    return Color.foreground
  }

  function healthDetail() {
    if (root.row === null) return ""
    var parts = []
    if (root.row.conflicts > 0) parts.push(root.row.conflicts + (root.row.conflicts > 1 ? " conflicts" : " conflict"))
    if (root.row.pending > 0) parts.push(root.row.pending + " pending")
    if (root.row.dangling > 0) parts.push(root.row.dangling + " dangling")
    if (parts.length === 0) parts.push("stowed")
    return parts.join("  ·  ")
  }

  function changeDetail() {
    if (root.row === null) return ""
    return String(root.row.packageLabel) + "  ·  " + String(root.row.kind)
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

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: root.hovered(root.rowIndex)
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

        Text {
          Layout.alignment: Qt.AlignVCenter
          visible: root.isGroup
          text: root.isGroup && root.row.expanded ? "▾" : "▸"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Rectangle {
          Layout.alignment: Qt.AlignVCenter
          visible: root.row !== null
          Layout.preferredWidth: Style.space(8)
          Layout.preferredHeight: Style.space(8)
          radius: Style.space(4)
          color: root.tokenColor(root.row === null ? "muted" : root.row.stateColor)
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
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
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
          onClicked: root.actionClicked()
        }
      }
    }
  }
}
