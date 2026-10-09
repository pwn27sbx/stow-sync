import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One compact Overview card per repo: name, branch, one plain-words status
// line and the single small action that fits (Publish when there is anything
// to commit, Update when the repo is behind). Enter on the card runs the same
// action.
BorderSurface {
  id: root

  property var row: null
  property int rowIndex: 0
  property bool focused: false
  property color foreground: Color.foreground

  signal hovered(int index)
  signal publishRequested()
  signal updateRequested()
  signal activated()

  readonly property bool isRepo: root.row !== null && root.row.type === "repo"
  readonly property bool canPublish: root.isRepo && (root.row.changesCount > 0 || root.row.untrackedCount > 0)
  readonly property bool canUpdate: root.isRepo && root.row.behind > 0
  readonly property string statusText: root.isRepo ? String(root.row.statusText) : ""

  implicitHeight: Math.max(Style.spacing.controlHeight, content.implicitHeight + Style.spacing.sm)
  color: root.focused ? Util.alpha(Color.accent, 0.16) : "transparent"
  borderSpec: Border.none()
  radius: Style.cornerRadius

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: root.hovered(root.rowIndex)
    onClicked: {
      if (root.canPublish) root.publishRequested()
      else if (root.canUpdate) root.updateRequested()
      else root.activated()
    }
  }

  RowLayout {
    id: content
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.spacing.controlPaddingX
    anchors.rightMargin: Style.spacing.controlPaddingX
    spacing: Style.spacing.sm

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 0

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.sm

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.isRepo ? String(root.row.basename || root.row.name) : ""
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
          elide: Text.ElideRight
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          visible: root.isRepo && String(root.row.branch) !== ""
          textFormat: Text.PlainText
          text: root.isRepo ? String(root.row.branch) : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.statusText
        color: root.isRepo && root.row.state === "clean" && !root.canPublish ? Color.muted : root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      visible: root.canPublish
      text: "Publish"
      onClicked: root.publishRequested()
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      visible: root.canUpdate
      text: "Update"
      onClicked: root.updateRequested()
    }
  }
}
