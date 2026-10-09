import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Fixed top of the panel (config-sync's header, folding in the Unit 4c hero):
// a state-tinted branch glyph, the title and version on one baseline, the
// plain-words state line with a spinner while busy, the refresh / Edit /
// close actions, and the dismissible feedback strip underneath. Errors stay
// until the next successful refresh; successes clear themselves.
Item {
  id: root

  property string title: "Stow Sync"
  property string version: ""
  property string stateText: ""
  property string stateTone: "muted"
  property bool busy: false
  property bool refreshEnabled: true
  property string message: ""
  property bool isError: false
  property color foreground: Color.foreground

  signal refreshClicked()
  signal editClicked()
  signal closeClicked()
  signal dismissed()

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
    spacing: Style.spacing.sm

    RowLayout {
      id: row
      Layout.fillWidth: true
      spacing: Style.spacing.md

      Text {
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        // Octicon git-branch; verified present in the bar font (see BarWidget).
        text: "\ue725"
        color: root.toneColor()
        font.family: Style.font.family
        font.pixelSize: Style.font.display
      }

      ColumnLayout {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        spacing: Style.spacing.xxs

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm

          Text {
            Layout.alignment: Qt.AlignBaseline
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
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
          Item { Layout.fillWidth: true }
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm

          Text {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            textFormat: Text.PlainText
            text: root.stateText
            color: root.toneColor()
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            Layout.alignment: Qt.AlignVCenter
            visible: root.busy
            textFormat: Text.PlainText
            // Font Awesome spinner, rotated while a request is in flight.
            text: "\uf110"
            color: root.toneColor()
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            RotationAnimation on rotation {
              from: 0
              to: 360
              duration: 900
              loops: Animation.Infinite
              running: root.busy
            }
          }
        }
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        iconText: "\uf021"
        tooltipText: "Refresh (r)"
        fontSize: Style.font.caption
        enabled: root.refreshEnabled && !root.busy
        onClicked: root.refreshClicked()
      }
      Button {
        Layout.alignment: Qt.AlignVCenter
        text: "Edit"
        tooltipText: "Open the Stow Sync config file"
        fontSize: Style.font.caption
        enabled: !root.busy
        onClicked: root.editClicked()
      }
      Button {
        Layout.alignment: Qt.AlignVCenter
        iconText: "\uf00d"
        tooltipText: "Close (Esc)"
        fontSize: Style.font.caption
        onClicked: root.closeClicked()
      }
    }

    BorderSurface {
      Layout.fillWidth: true
      visible: root.message !== ""
      implicitHeight: messageRow.implicitHeight + Style.spacing.sm
      color: Util.alpha(root.isError ? Color.urgent : Color.accent, 0.10)
      borderSpec: Border.controlSpec(root.isError ? "selected" : "normal", root.isError ? Color.urgent : Color.accent, Color.accent)
      radius: Style.cornerRadius
      padding: Style.spacing.sm

      RowLayout {
        id: messageRow
        width: parent.width
        spacing: Style.spacing.sm
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
