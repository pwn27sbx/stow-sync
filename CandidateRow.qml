import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One candidate row, optionally prefixed by its group header ("New configs",
// "Existing untracked"). The package picker is a Button that asks the panel to
// open the shared picker; Adopt and Ignore emit their own signals.
Item {
  id: root

  property var row: null
  property int rowIndex: 0
  property bool focused: false
  property string header: ""
  property bool showBulk: false
  property string packageName: ""

  signal hovered(int index)
  signal adoptRequested()
  signal ignoreRequested()
  signal pickRequested()
  signal bulkIgnoreRequested()

  implicitHeight: column.implicitHeight

  Column {
    id: column
    width: parent.width
    spacing: Style.spacing.xs

    RowLayout {
      width: parent.width
      visible: root.header !== ""
      spacing: Style.spacing.sm

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.header
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: root.showBulk
        text: "Ignore all shown"
        onClicked: root.bulkIgnoreRequested()
      }
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
        onEntered: root.hovered(root.rowIndex)
        onClicked: root.adoptRequested()
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
          color: root.row === null ? Color.muted : (root.row.known ? Color.muted : Color.accent)
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: 0

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.row === null ? "" : String(root.row.path)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.row === null ? "" : (String(root.row.itemType) + "  ·  " + String(root.row.sizeText))
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          text: root.packageName !== "" ? root.packageName : "package…"
          tooltipText: "Suggested package — click to change"
          onClicked: root.pickRequested()
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          text: "Adopt"
          onClicked: root.adoptRequested()
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          text: "Ignore"
          onClicked: root.ignoreRequested()
        }
      }
    }
  }
}
