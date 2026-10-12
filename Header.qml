import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Fixed top of the panel. No boxed look: a small filled circle tinted by state
// holds the branch glyph, the title and version sit on one baseline, and three
// icon-only 32x32 actions (refresh, edit, close) live on the right. The
// dismissible feedback strip stays underneath until the next success.
Item {
  id: root

  property string title: "Stow Sync"
  property string version: ""
  property string stateTone: "muted"
  property bool busy: false
  property bool refreshEnabled: true
  property string message: ""
  property bool isError: false
  property bool showSetup: false
  property bool showSetupBackups: false
  property color foreground: Color.foreground

  signal refreshClicked()
  signal editClicked()
  signal closeClicked()
  signal dismissed()
  signal helpToggled()
  signal setupClicked()
  signal undoSetupClicked()

  function toneColor() {
    if (root.stateTone === "urgent") return Color.urgent
    if (root.stateTone === "accent") return Color.accent
    return root.foreground
  }

  implicitHeight: column.implicitHeight

  ColumnLayout {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.spacing.lg

    RowLayout {
      id: row
      Layout.fillWidth: true
      spacing: Style.spacing.xxl

      Rectangle {
        Layout.alignment: Qt.AlignVCenter
        implicitWidth: Style.space(28)
        implicitHeight: Style.space(28)
        radius: Style.cornerRadius
        color: Util.alpha(root.toneColor(), 0.18)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          // Octicon git-branch; verified present in the bar font.
          text: "\ue725"
          color: root.toneColor()
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      Text {
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: root.title
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.title
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        Layout.alignment: Qt.AlignBaseline
        textFormat: Text.PlainText
        text: root.version !== "" ? "v" + root.version : ""
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Item { Layout.fillWidth: true }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(32)
        Layout.preferredHeight: Style.space(32)
        horizontalPadding: 0
        verticalPadding: 0
        visible: root.showSetup
        iconText: "\uf109"
        tooltipText: "Set up this machine"
        fontSize: Style.font.caption
        enabled: !root.busy
        onClicked: root.setupClicked()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredHeight: Style.space(32)
        verticalPadding: 0
        horizontalPadding: Style.spacing.md
        visible: root.showSetupBackups
        // Labelled action, not an icon-only glyph (finding 88). Material Design
        // md-undo U+F054C, verified present in JetBrainsMono Nerd Font.
        iconText: "\u{F054C}"
        text: "Undo setup"
        tooltipText: "Undo setup"
        fontSize: Style.font.caption
        enabled: !root.busy
        onClicked: root.undoSetupClicked()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(32)
        Layout.preferredHeight: Style.space(32)
        horizontalPadding: 0
        verticalPadding: 0
        iconText: "\uf021"
        tooltipText: "Refresh (r)"
        fontSize: Style.font.caption
        enabled: root.refreshEnabled && !root.busy
        onClicked: root.refreshClicked()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(32)
        Layout.preferredHeight: Style.space(32)
        horizontalPadding: 0
        verticalPadding: 0
        iconText: "\uf013"
        tooltipText: "Open the Stow Sync config file"
        fontSize: Style.font.caption
        enabled: !root.busy
        onClicked: root.editClicked()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(32)
        Layout.preferredHeight: Style.space(32)
        horizontalPadding: 0
        verticalPadding: 0
        iconText: "\uf11c"
        tooltipText: "Keys (?)"
        fontSize: Style.font.caption
        onClicked: root.helpToggled()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(32)
        Layout.preferredHeight: Style.space(32)
        horizontalPadding: 0
        verticalPadding: 0
        iconText: "\uf00d"
        tooltipText: "Close (Esc)"
        fontSize: Style.font.caption
        onClicked: root.closeClicked()
      }
    }

    BorderSurface {
      Layout.fillWidth: true
      visible: root.message !== ""
      implicitHeight: messageRow.implicitHeight + Style.spacing.lg
      color: Util.alpha(root.isError ? Color.urgent : Color.accent, 0.10)
      borderSpec: Border.controlSpec(root.isError ? "selected" : "normal", root.isError ? Color.urgent : Color.accent, Color.accent)
      radius: Style.cornerRadius
      padding: Style.spacing.lg

      RowLayout {
        id: messageRow
        width: parent.width
        spacing: Style.spacing.lg
        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.message
          color: root.isError ? Color.urgent : Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }
        Button {
          Layout.alignment: Qt.AlignVCenter
          visible: root.isError
          iconText: "\uf00d"
          tooltipText: "Dismiss"
          fontSize: Style.font.caption
          onClicked: root.dismissed()
        }
      }
    }
  }
}
