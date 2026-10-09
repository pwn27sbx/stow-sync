import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Stow Sync popup. Unit 0 is scaffold only: an empty keyboard panel that shows
// the plugin name. Rows, actions and the backend runner land in later units.
Panel {
  id: root
  moduleName: "pwnsxb.stow-sync"
  ipcTarget: "pwnsxb.stow-sync"
  manageIpc: false

  property var anchorItem: null

  // The bar tracks the widget mounted in its slot (BarWidget.qml), not this
  // nested panel, so the popout coordinator keeps referring to `hostWidget`.
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.space(8)

        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: "Stow Sync"
          color: Color.foreground
          font.family: Style.font.family
          font.bold: true
          font.pixelSize: Style.font.title
        }

        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: "Scaffold — backend and panel land in later units."
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }
}
