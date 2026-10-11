import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar slot for Stow Sync. The icon is one Nerd Font Material Design glyph:
// md-swap_horizontal_bold at rest, swapped for md-autorenew while a request is
// in flight. Overlays: a 7 px state dot top-right (accent when there are changes/new
// configs, urgent when something needs attention) and a tiny up/down arrow glyph
// bottom-right when there are commits to upload/fetch. There is no numeric badge;
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
  readonly property string arrowGlyph: Model.barArrowGlyph(root.iconState)
  readonly property string tooltipText: "Stow Sync — " + Model.heroState(statusData, "", { machineSetup: root.setupAvailable }).title

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

  // `openGate` is true only once the host has actually delivered this widget's
  // settings. The bar host sets `bar` first and `settings` right after, so
  // onBarChanged must never open the gate (README 11a fix). Only injectPanel
  // sets settingsReady.
  function injectPanel(openGate) {
    var target = panelItem
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("settingsReady" in target && openGate === true) target.settingsReady = true
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    // Let the panel run its first refresh; it waits for the gate so it never
    // runs the helper with the default (real) config.
    if (typeof target.ensureStarted === "function") target.ensureStarted()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: root.injectPanel(false)
  onSettingsChanged: root.injectPanel(true)

  // Safety net: if settings were delivered before the panel loaded (so
  // onSettingsChanged fired with no panel yet), open the gate once after load.
  Timer {
    id: gateFallback
    interval: 800
    repeat: false
    running: true
    onTriggered: root.injectPanel(true)
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel(false)
      Qt.callLater(function() { root.injectPanel(false) })
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

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    active: root.opened
    text: Model.barIconGlyph(root.busy)
    tooltipText: root.tooltipText
    onPressed: function(which) {
      if (which === Qt.RightButton) root.refreshWithFetch()
      else root.togglePanel()
    }
  }

  // State dot top-right (urgent wins over accent). A 1 px ring in the bar
  // background keeps it readable over any icon.
  Rectangle {
    visible: root.iconState.dot !== "none"
    width: 7; height: 7; radius: 4
    color: root.tokenColor(root.iconState.dot)
    border.width: 1
    border.color: root.bar ? root.bar.background : Color.background
    anchors.right: parent.right; anchors.top: parent.top
    anchors.rightMargin: 1; anchors.topMargin: 3
  }

  // Ahead/behind as a tiny arrow glyph overlay, bottom-right.
  Text {
    visible: root.arrowGlyph !== ""
    text: root.arrowGlyph
    color: button.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    anchors.right: parent.right; anchors.bottom: parent.bottom
    anchors.rightMargin: 1; anchors.bottomMargin: 1
  }
}
