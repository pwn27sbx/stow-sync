import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar slot for Stow Sync. The icon is a drawn bridge: two filled nodes (this PC
// and GitHub) joined by a line. Overlays: a state dot top-right (accent when
// there are changes/new configs, urgent when something needs attention), a tiny
// up/down chevron when there are commits to upload/fetch, and a dot travelling
// along the line only while a request is in flight. There is no numeric badge;
// the number lives in the tooltip and the panel.
BarWidget {
  id: root
  moduleName: "pwnsxb.stow-sync"

  readonly property var panelItem: panelLoader.item
  readonly property bool opened: panelItem ? panelItem.opened === true : false

  // Forwarded so this widget can stand in for the panel as the bar's popout
  // identity; the KeyboardPanel reads popoutSwitchClosing back off its owner.
  readonly property bool popoutSwitchClosing: panelItem ? panelItem.popoutSwitchClosing === true : false

  readonly property var statusData: panelItem && "statusData" in panelItem ? panelItem.statusData : null
  readonly property bool busy: panelItem && panelItem.busy === true
  readonly property bool setupAvailable: Model.setupVisible(root.settings, root.statusData)
  readonly property var iconState: Model.barIconState(statusData)
  readonly property string tooltipText: "Stow Sync — " + Model.heroState(statusData).title

  function tokenColor(token) {
    if (token === "urgent") return Color.urgent
    if (token === "accent") return Color.accent
    return Color.foreground
  }

  function open() {
    if (panelItem) panelItem.open()
  }

  function close() {
    if (panelItem) panelItem.close()
  }

  function togglePanel() {
    if (panelItem) panelItem.toggle()
  }

  function closeForPopoutSwitch() {
    if (panelItem) panelItem.closeForPopoutSwitch()
  }

  function refreshWithFetch() {
    if (panelItem && typeof panelItem.refreshWithFetch === "function") panelItem.refreshWithFetch()
  }

  // Open the panel and the "Set up this machine" wizard. No-op unless the
  // machineSetup setting is on, so the feature stays invisible when disabled.
  function openSetupWizard() {
    if (!root.setupAvailable) return
    root.open()
    if (panelItem && typeof panelItem.openSetup === "function") panelItem.openSetup()
  }

  function injectPanel() {
    var target = panelItem
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    // Settings are set now; let the panel run its first refresh (it waits for
    // this so it never runs the helper with the wrong config).
    if (typeof target.ensureStarted === "function") target.ensureStarted()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "pwnsxb.stow-sync"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function refresh(): void { root.refreshWithFetch() }
    function setup(): void { root.openSetupWizard() }
  }

  // The drawn bridge glyph. Everything is sized off the icon canvas so it stays
  // crisp in the bar slot.
  Component {
    id: bridgeGlyph

    Item {
      id: glyph
      anchors.fill: parent

      readonly property real slot: Math.min(width, height)
      readonly property real nodeD: Math.max(2, Math.round(slot * 0.32))
      readonly property real lineH: Math.max(1, Math.round(slot * 0.10))
      readonly property real midY: Math.round(height / 2)
      readonly property real leftCx: Math.round(width * 0.22)
      readonly property real rightCx: Math.round(width * 0.78)
      readonly property real chevronSize: Math.max(6, Math.round(slot * 0.44))
      readonly property color dotColor: root.tokenColor(root.iconState.dot)

      // Connecting line.
      Rectangle {
        x: parent.leftCx
        y: parent.midY - Math.round(height / 2)
        width: Math.max(1, parent.rightCx - parent.leftCx)
        height: parent.lineH
        color: button.foreground
      }

      // Left node: this PC.
      Rectangle {
        x: parent.leftCx - width / 2
        y: parent.midY - height / 2
        width: parent.nodeD
        height: parent.nodeD
        radius: width / 2
        color: button.foreground
      }

      // Right node: GitHub.
      Rectangle {
        x: parent.rightCx - width / 2
        y: parent.midY - height / 2
        width: parent.nodeD
        height: parent.nodeD
        radius: width / 2
        color: button.foreground
      }

      // Up chevron above the line: commits to upload.
      Text {
        visible: root.iconState.up
        x: Math.round((width - implicitWidth) / 2)
        y: Math.round(parent.midY - parent.lineH / 2 - height - Math.round(parent.slot * 0.08))
        text: "\u2191"
        color: button.foreground
        font.family: Style.font.family
        font.bold: true
        font.pixelSize: parent.chevronSize
      }

      // Down chevron below the line: commits to fetch.
      Text {
        visible: root.iconState.down
        x: Math.round((width - implicitWidth) / 2)
        y: Math.round(parent.midY + parent.lineH / 2 + Math.round(parent.slot * 0.08))
        text: "\u2193"
        color: button.foreground
        font.family: Style.font.family
        font.bold: true
        font.pixelSize: parent.chevronSize
      }

      // State dot top-right (urgent wins over accent). A 1 px ring in the bar
      // background keeps it readable over any icon.
      Rectangle {
        visible: root.iconState.dot !== "none"
        width: Math.max(4, Math.round(slot * 0.24))
        height: width
        radius: width / 2
        anchors.right: parent.right
        anchors.top: parent.top
        color: parent.dotColor
        border.width: 1
        border.color: root.bar ? root.bar.background : Color.background
      }

      // Travelling dot: only while a request is in flight.
      Rectangle {
        id: travelDot
        visible: root.busy
        width: Math.max(4, Math.round(parent.slot * 0.22))
        height: width
        radius: width / 2
        y: parent.midY - height / 2
        color: Color.accent

        SequentialAnimation on x {
          running: root.busy
          loops: Animation.Infinite
          NumberAnimation {
            from: glyph.leftCx
            to: Math.max(glyph.leftCx, glyph.rightCx - travelDot.width)
            duration: 600
            easing.type: Easing.InOutSine
          }
          NumberAnimation {
            from: Math.max(glyph.leftCx, glyph.rightCx - travelDot.width)
            to: glyph.leftCx
            duration: 600
            easing.type: Easing.InOutSine
          }
        }
      }
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    active: root.opened
    iconComponent: bridgeGlyph
    tooltipText: root.tooltipText
    onPressed: function(which) {
      if (which === Qt.RightButton) root.refreshWithFetch()
      else root.togglePanel()
    }
  }
}
