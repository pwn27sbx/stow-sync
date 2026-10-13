import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One new-config candidate inside the Overview "New config files" group. The
// package is chosen in the Adopt confirm card (an editable field prefilled
// with the suggestion), so this row only shows the path, size, suggestion and
// the Adopt / Ignore actions.
Item {
  id: root

  property var row: null
  property bool focused: false
  property bool credential: false
  property string packageName: ""
  property color foreground: Color.foreground

  signal hovered()
  signal adoptRequested()
  signal ignoreRequested()

  readonly property var candidate: root.row || ({})

  implicitHeight: card.implicitHeight

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
      cursorShape: root.credential ? Qt.ArrowCursor : Qt.PointingHandCursor
      onEntered: root.hovered()
      onClicked: if (!root.credential) root.adoptRequested()
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
        Layout.preferredWidth: Style.space(8)
        Layout.preferredHeight: Style.space(8)
        radius: width / 2
        color: root.credential ? Util.alpha(root.foreground, 0.5) : Color.accent
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(root.candidate.path || "")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideMiddle
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.credential
            ? (String(root.candidate.group || "watched") + "  \u00b7  contains credentials")
            : (String(root.candidate.group || "watched") + "  \u00b7  package: " + root.packageName)
          color: Util.alpha(root.foreground, 0.8)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: !root.credential
        text: "Adopt"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        onClicked: root.adoptRequested()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        text: "Ignore"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        onClicked: root.ignoreRequested()
      }
    }
  }
}
