import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Quiet Overview line for the latest un-undone setup (README Unit 15d):
// "Set up 12 Oct · 17 packages linked" on the left and a small "Undo setup"
// button on the right. Hidden while the machine is not set up or busy; the
// button keeps the 15b behaviour (one setup → the confirm card, several → the
// list). Theme colours only; the danger tone shows on hover/focus only.
RowLayout {
  id: root

  property var backups: []
  property bool busy: false
  property bool notSetUp: false
  property color foreground: Color.foreground

  signal undoRequested()

  readonly property var info: Model.setupLine(root.backups, { notSetUp: root.notSetUp, busy: root.busy })

  width: parent ? parent.width : 0
  visible: root.info !== null
  spacing: Style.spacing.md

  Text {
    Layout.fillWidth: true
    textFormat: Text.PlainText
    text: root.info !== null ? String(root.info.label) : ""
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    elide: Text.ElideRight
  }

  Button {
    id: undoButton
    Layout.alignment: Qt.AlignVCenter
    property bool hot: false
    text: "Undo setup"
    iconText: "\u{F054C}"
    tooltipText: "Undo setup"
    fontSize: Style.font.caption
    horizontalPadding: Style.spacing.sm
    verticalPadding: 0
    focusable: true
    // Danger tone only while hovered or focused (README Unit 15d).
    foreground: (hot || activeFocus) ? Color.urgent : root.foreground
    enabled: !root.busy
    onHovered: function(hovered) { hot = hovered }
    onClicked: root.undoRequested()
  }
}
