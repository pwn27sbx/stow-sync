import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Full-width entry point shown only while `machineSetup` is on and a configured
// repo is missing on disk (README 10b.1/finding 1). The whole card is clickable,
// it carries a one-line explanation and a filled primary button; the "this
// machine is not set up yet" sentence lives once, in the hero above.
Item {
  id: root

  property color foreground: Color.foreground
  signal setupRequested()

  implicitHeight: card.implicitHeight

  BorderSurface {
    id: card
    width: parent.width
    implicitHeight: column.implicitHeight + Style.space(12) * 2
    color: Util.alpha(Color.accent, 0.10)
    borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
    radius: Style.cornerRadius

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: root.setupRequested()
    }

    ColumnLayout {
      id: column
      anchors.fill: parent
      anchors.margins: Style.space(12)
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "Download your repos and link your configs on this machine."
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Button {
        id: cta
        Layout.alignment: Qt.AlignLeft
        text: "Set up this machine"
        iconText: "\uf109"
        background: Color.accent
        foreground: Color.background
        horizontalPadding: Style.space(16)
        verticalPadding: Style.space(8)
        fontSize: Style.font.caption
        onClicked: root.setupRequested()
      }
    }
  }
}
