import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Full-width entry point shown only while `machineSetup` is on and a configured
// repo is missing on disk (README 10b.1/finding 1). The whole card is clickable
// and a filled primary button names the action.
Item {
  id: root

  property color foreground: Color.foreground
  signal setupRequested()

  implicitHeight: card.implicitHeight

  BorderSurface {
    id: card
    width: parent.width
    implicitHeight: column.implicitHeight + Style.spacing.lg * 2
    color: Util.alpha(Color.accent, 0.10)
    borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
    radius: Style.cornerRadius
    padding: Style.spacing.lg

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: root.setupRequested()
    }

    ColumnLayout {
      id: column
      width: parent.width
      spacing: Style.spacing.sm

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "This machine is not set up yet"
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "Download your repos and link your configs on this machine."
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Button {
        id: cta
        Layout.alignment: Qt.AlignLeft
        text: "Set up this machine"
        iconText: "\uf109"
        fontSize: Style.font.caption
        onClicked: root.setupRequested()
      }
    }
  }
}
