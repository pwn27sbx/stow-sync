pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model
// Tab body: `tab` picks Overview (0), Changes (1) or Packages (2); expansion
// state lives here so it survives tab switches, while selection/hidden state
// is owned by Panel (the publish plan needs it).
// Layout note: the root and each tab body are plain Columns (positioners),
// not ColumnLayouts: a Column derives implicitHeight from its children and
// positions them by height alone (what the Flickable contentHeight needs).
Column {
  id: root
  property var statusData: null
  property int tab: 0
  property string version: ""
  property string now: ""
  property bool busy: false
  property var checkedPaths: ({})
  property var hiddenPaths: []
  property bool showHidden: false
  property bool showExisting: false
  property string focusedKey: ""
  property var packages: []
  property color foreground: Color.foreground
  signal reviewRequested()
  signal publishRequested()
  signal updateRequested()
  signal restowRequested(string repo, string packageName)
  signal adoptRequested(var candidate)
  signal ignoreRequested(var candidate)
  signal copyRequested(string value)
  signal selectAllRequested()
  signal selectRepoRequested()
  signal clearSelectionRequested()
  signal showHiddenToggled()
  signal showExistingToggled()
  signal changeToggled(string key, bool value)
  signal changeHovered(string key)
  signal diffRequested(string repo, string path)
  property var expandedGroups: ({})
  property var expandedRepos: ({})
  property var expandedPackages: ({})
  readonly property var repos: (root.statusData && root.statusData.repos) || []
  readonly property var tiles: Model.statTiles(root.statusData)
  readonly property var groups: Model.overviewGroups(root.statusData)
  readonly property var changeView: Model.changesView(root.statusData, { hiddenPaths: root.hiddenPaths, showHidden: root.showHidden, showExisting: root.showExisting })
  readonly property int changes: Model.changeTotals(root.statusData).count
  readonly property int behind: Model.flowTotals(root.statusData, "behind").count
  readonly property int fresh: Model.newCandidateCount(root.statusData)
  readonly property int hiddenCount: root.hiddenPaths.length
  readonly property var firstUnhealthy: Model.firstUnhealthy(root.statusData)
  function setKey(map, key, value) { var next = {}; for (var k in map) next[k] = map[k]; next[key] = value; return next }
  function groupExpanded(key) { return root.expandedGroups[key] === true }
  function expandGroup(key) { root.expandedGroups = root.setKey(root.expandedGroups, key, true) }
  function toggleGroup(key) { root.expandedGroups = root.setKey(root.expandedGroups, key, !root.groupExpanded(key)) }
  function repoExpanded(path, index) { return root.expandedRepos[path] !== undefined ? root.expandedRepos[path] === true : index === 0 }
  function toggleRepo(path) { root.expandedRepos = root.setKey(root.expandedRepos, path, !root.repoExpanded(path, -1)) }
  function packageExpanded(key) { return root.expandedPackages[key] === true }
  function togglePackage(key) { root.expandedPackages = root.setKey(root.expandedPackages, key, !root.packageExpanded(key)) }
  function isChecked(key) { return root.checkedPaths[key] !== false }
  width: parent ? parent.width : 0
  height: childrenRect.height
  spacing: Style.spacing.md
  // ---- Overview ---------------------------------------------------------
  Column {
    id: overviewBody
    width: root.width
    visible: root.tab === 0
    spacing: Style.spacing.md
    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: Model.explain(root.statusData)
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
    Row {
      id: tileRow
      width: parent.width
      spacing: Style.spacing.sm
      opacity: root.busy ? 0.6 : 1.0
      readonly property int tileCount: Math.max(1, root.tiles.length)
      readonly property real tileWidth: (width - spacing * (tileCount - 1)) / tileCount
      Repeater {
        model: root.tiles
        StatTile {
          required property var modelData
          width: tileRow.tileWidth
          icon: modelData.icon
          value: modelData.value
          label: modelData.label
          tone: modelData.tone
          foreground: root.foreground
        }
      }
    }
    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Button { visible: root.changes > 0 || root.fresh > 0 || root.behind > 0; text: "Review Changes"; iconText: "\uf044"; fontSize: Style.font.caption; onClicked: root.reviewRequested() }
      Button { visible: root.behind > 0; text: "Update"; iconText: "\uf0ed"; fontSize: Style.font.caption; onClicked: root.updateRequested() }
      Button { visible: root.changes > 0; text: "Publish"; iconText: "\uf0ee"; fontSize: Style.font.caption; enabled: !root.busy; onClicked: root.publishRequested() }
      Button {
        visible: root.firstUnhealthy !== null; text: "Fix packages"; iconText: "\uf0ad"; fontSize: Style.font.caption; enabled: !root.busy
        onClicked: if (root.firstUnhealthy) root.restowRequested(root.firstUnhealthy.repo, root.firstUnhealthy.package) }
    }
    Repeater {
      model: root.repos
      InfoTable {
        required property var modelData
        required property int index
        width: parent.width
        repo: modelData
        version: root.version
        now: root.now
        expanded: root.repoExpanded(String(modelData.path || ""), index)
        foreground: root.foreground
        onToggled: root.toggleRepo(String(modelData.path || ""))
        onCopyRequested: function(value) { root.copyRequested(value) }
      }
    }
    Text {
      width: parent.width
      visible: root.groups.length > 0
      textFormat: Text.PlainText
      text: "Groups below are collapsed. Press one to expand it."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
    Repeater {
      model: root.groups
      GroupCard {
        required property var modelData
        width: parent.width
        title: modelData.title
        subtitle: modelData.subtitle
        count: String(modelData.count)
        unit: modelData.unit
        expanded: root.groupExpanded(modelData.key)
        foreground: root.foreground
        onToggled: root.toggleGroup(modelData.key)
        Repeater {
          model: modelData.items
          Item {
            required property var modelData
            width: parent ? parent.width : 0
            implicitHeight: Math.max(itemLine.implicitHeight, candLine.implicitHeight)
            ItemRow {
              id: itemLine
              width: parent.width
              visible: modelData.type !== "candidate"
              primary: modelData.type === "incoming" ? (String(modelData.hash) + "  " + String(modelData.subject)) : String(modelData.path)
              secondary: modelData.type === "health" ? Model.healthLabel(modelData.health) : (modelData.type === "incoming" ? Model.repoDisplayName(modelData.repo) : String(modelData.package))
              chip: modelData.type === "change" ? String(modelData.chip) : ""
              showAction: modelData.type === "health"
              actionText: "Fix"
              foreground: root.foreground
              onActionClicked: root.restowRequested(String(modelData.repo), String(modelData.package))
            }
            CandidateRow {
              id: candLine
              width: parent.width
              visible: modelData.type === "candidate"
              row: modelData
              packageName: Model.packageFor({ key: modelData.path, suggestedPackage: modelData.package, path: modelData.path }, {})
              foreground: root.foreground
              onAdoptRequested: root.adoptRequested(modelData)
              onIgnoreRequested: root.ignoreRequested(modelData)
            }
          }
        }
      }
    }
  }
  // ---- Changes ----------------------------------------------------------
  Column {
    id: changesBody
    width: root.width
    visible: root.tab === 1
    spacing: Style.spacing.md
    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: Model.explain(root.statusData)
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Button { text: "Select all"; fontSize: Style.font.caption; onClicked: root.selectAllRequested() }
      Button { text: "Select repo \u25b8"; fontSize: Style.font.caption; onClicked: root.selectRepoRequested() }
      Button { text: "Clear"; fontSize: Style.font.caption; onClicked: root.clearSelectionRequested() }
      Button { text: "Hidden (" + root.hiddenCount + ")"; iconText: "\uf070"; fontSize: Style.font.caption; bordered: true; onClicked: root.showHiddenToggled() }
    }
    Button { text: "Publish selected"; iconText: "\uf0ee"; fontSize: Style.font.caption; enabled: !root.busy; onClicked: root.publishRequested() }
    BorderSurface {
      width: parent.width
      implicitHeight: toggleRow.implicitHeight + Style.spacing.sm * 2
      color: Util.alpha(Color.foreground, 0.04)
      borderSpec: Border.controlSpec("normal", Color.foreground, Color.accent)
      radius: Style.cornerRadius
      padding: Style.spacing.sm
      RowLayout {
        id: toggleRow
        width: parent.width
        spacing: Style.spacing.sm
        ColumnLayout {
          Layout.fillWidth: true
          spacing: 0
          Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: "Show existing untracked files"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }
          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "Files that already existed when Stow Sync was installed. They are not counted in the badge."
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
        ToggleSwitch { Layout.alignment: Qt.AlignVCenter; checked: root.showExisting; onToggled: root.showExistingToggled() }
      }
    }
    Repeater {
      model: root.changeView.groups
      GroupCard {
        required property var modelData
        width: parent.width
        title: modelData.title
        subtitle: modelData.count + " files \u00b7 press to expand"
        count: String(modelData.count)
        unit: "files"
        expanded: root.packageExpanded("repo:" + modelData.key)
        onToggled: root.togglePackage("repo:" + modelData.key)
        Repeater {
          model: modelData.packages
          Column {
            required property var modelData
            width: parent ? parent.width : 0
            spacing: Style.spacing.xxs
            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: modelData.label + "  \u00b7  " + modelData.count + " files"
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
            }
            Repeater {
              model: modelData.items
              ItemRow {
                required property var modelData
                width: parent ? parent.width : 0
                primary: String(modelData.path)
                secondary: String(modelData.package)
                chip: String(modelData.chip)
                showCheckbox: true
                checked: root.isChecked(modelData.key)
                focused: root.focusedKey === modelData.key
                dimmed: modelData.hidden === true
                onHovered: root.changeHovered(String(modelData.key))
                onToggled: function(value) { root.changeToggled(String(modelData.key), value) }
                onActivated: root.diffRequested(String(modelData.repo), String(modelData.path))
              }
            }
          }
        }
      }
    }
  }
  // ---- Packages ---------------------------------------------------------
  Column {
    id: packagesBody
    width: root.width
    visible: root.tab === 2
    spacing: Style.spacing.md
    Repeater {
      model: root.packages
      PackageCard {
        required property var modelData
        width: parent.width
        card: modelData
        expanded: root.packageExpanded(String(modelData.repo) + ":" + String(modelData.name))
        onToggled: root.togglePackage(String(modelData.repo) + ":" + String(modelData.name))
        onRestowRequested: root.restowRequested(String(modelData.repo), String(modelData.name))
      }
    }
  }
}
