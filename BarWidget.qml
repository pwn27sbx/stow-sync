import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar slot for Stow Sync: a git-branch glyph, a count badge colored by the
// worst signal, and the popup. The glyph U+E725 is the Octicon "git-branch";
// it was verified present in JetBrainsMono Nerd Font's cmap, the family the
// bar font resolves to.
BarWidget {
  id: root
  moduleName: "pwnsxb.stow-sync"

  readonly property var panelItem: panelLoader.item
  readonly property bool opened: panelItem ? panelItem.opened === true : false

  // Forwarded so this widget can stand in for the panel as the bar's popout
  // identity; the KeyboardPanel reads popoutSwitchClosing back off its owner.
  readonly property bool popoutSwitchClosing: panelItem ? panelItem.popoutSwitchClosing === true : false

  readonly property var statusData: panelItem && "data" in panelItem ? panelItem.data : null
  readonly property string badgeLabel: Model.badgeText(statusData)
  readonly property color badgeColor: root.tokenColor(Model.badgeColor(statusData))
  readonly property string summaryState: statusData && statusData.summary ? statusData.summary.state : "clean"

  function tokenColor(token) {
    if (token === "urgent") return Color.urgent
    if (token === "accent") return Color.accent
    if (token === "muted") return Color.muted
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

  function injectPanel() {
    var target = panelItem
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
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
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    active: root.opened
    text: "\ue725"
    tooltipText: "Stow Sync — " + Model.stateTitle(root.summaryState)
    onPressed: function(button) {
      if (button === Qt.RightButton) root.refreshWithFetch()
      else root.togglePanel()
    }
  }

  Rectangle {
    id: badge
    visible: root.badgeLabel !== ""
    z: 2
    anchors.right: parent.right
    anchors.top: parent.top
    width: Math.max(Style.space(12), badgeText.implicitWidth + Style.space(6))
    height: Style.space(12)
    radius: height / 2
    color: root.badgeColor
    border.width: 1
    border.color: root.bar ? root.bar.background : Color.background

    Text {
      id: badgeText
      anchors.centerIn: parent
      text: root.badgeLabel
      color: Color.background
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
    }
  }
}
