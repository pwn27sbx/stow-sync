import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Header row for one repo: name, branch/ahead/behind, state chip and the
// commit/push/pull actions. Actions are enabled only when the backend would
// accept them (Model.repoRow precomputes canCommit/canPush/canPull).
BorderSurface {
  id: root

  property var row: null
  property int rowIndex: 0
  property bool focused: false

  signal hovered(int index)
  signal commitRequested()
  signal pushRequested()
  signal pullRequested()

  function tokenColor(token) {
    if (token === "urgent") return Color.urgent
    if (token === "accent") return Color.accent
    if (token === "muted") return Color.muted
    return Color.foreground
  }

  implicitHeight: Math.max(Style.spacing.controlHeight, content.implicitHeight + Style.spacing.sm)
  color: root.focused ? Util.alpha(Color.accent, 0.16) : "transparent"
  borderSpec: Border.none()
  radius: Style.cornerRadius

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    onEntered: root.hovered(root.rowIndex)
    onClicked: root.commitRequested()
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

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.row === null ? "" : String(root.row.name)
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.row === null ? "" : String(root.row.subtitle)
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    BorderSurface {
      Layout.alignment: Qt.AlignVCenter
      implicitWidth: chipText.implicitWidth + Style.space(10)
      implicitHeight: chipText.implicitHeight + Style.space(4)
      radius: height / 2
      color: Util.alpha(root.tokenColor(root.row === null ? "muted" : root.row.stateColor), 0.2)
      borderSpec: Border.flat(root.tokenColor(root.row === null ? "muted" : root.row.stateColor), 1)

      Text {
        id: chipText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: root.row === null ? "" : String(root.row.title)
        color: root.tokenColor(root.row === null ? "muted" : root.row.stateColor)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      Layout.alignment: Qt.AlignVCenter
      visible: root.row !== null && root.row.ahead > 0
      text: root.row === null ? "" : "↑" + root.row.ahead
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      Layout.alignment: Qt.AlignVCenter
      visible: root.row !== null && root.row.behind > 0
      text: root.row === null ? "" : "↓" + root.row.behind
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Commit…"
      enabled: root.row !== null && root.row.canCommit
      onClicked: root.commitRequested()
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Push"
      enabled: root.row !== null && root.row.canPush
      onClicked: root.pushRequested()
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Pull"
      enabled: root.row !== null && root.row.canPull
      onClicked: root.pullRequested()
    }
  }
}
