import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Header row for one repo: name, branch/ahead/behind, state chip and the
// commit/push/pull actions. This component is instantiated for every list
// delegate, so every binding first checks `isRepo`; otherwise a change/candidate
// row would feed undefined into the bool `enabled`/`visible` properties and
// flood the journal with "Unable to assign [undefined] to bool".
BorderSurface {
  id: root

  property var row: null
  property int rowIndex: 0
  property bool focused: false

  signal hovered(int index)
  signal commitRequested()
  signal pushRequested()
  signal pullRequested()

  readonly property bool isRepo: root.row !== null && root.row.type === "repo"
  // Commit is offered when there is anything to commit (tracked or untracked).
  readonly property bool canCommit: root.isRepo && (root.row.changesCount > 0 || root.row.untrackedCount > 0)
  readonly property bool canPush: root.isRepo && root.row.ahead > 0
  readonly property bool canPull: root.isRepo && root.row.behind > 0

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
        text: root.isRepo ? String(root.row.name) : ""
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.isRepo ? String(root.row.subtitle) : ""
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
      color: Util.alpha(root.tokenColor(root.isRepo ? root.row.stateColor : "muted"), 0.2)
      borderSpec: Border.flat(root.tokenColor(root.isRepo ? root.row.stateColor : "muted"), 1)

      Text {
        id: chipText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: root.isRepo ? String(root.row.title) : ""
        color: root.tokenColor(root.isRepo ? root.row.stateColor : "muted")
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      Layout.alignment: Qt.AlignVCenter
      visible: root.canPush
      text: root.isRepo ? "↑" + root.row.ahead : ""
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      Layout.alignment: Qt.AlignVCenter
      visible: root.canPull
      text: root.isRepo ? "↓" + root.row.behind : ""
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Commit…"
      enabled: root.canCommit
      focusable: root.canCommit
      opacity: root.canCommit ? 1.0 : 0.4
      onClicked: root.commitRequested()
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: root.isRepo ? "Push (" + root.row.ahead + ")" : "Push"
      enabled: root.canPush
      focusable: root.canPush
      opacity: root.canPush ? 1.0 : 0.4
      onClicked: root.pushRequested()
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: root.isRepo ? "Pull (" + root.row.behind + ")" : "Pull"
      enabled: root.canPull
      focusable: root.canPull
      opacity: root.canPull ? 1.0 : 0.4
      onClicked: root.pullRequested()
    }
  }
}
