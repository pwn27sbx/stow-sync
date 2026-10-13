pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model
// Tab body: `tab` picks Overview (0), Changes (1) or Packages (2). Expansion
// state lives here (survives tab switches); selection/hidden state is owned by
// Panel. Root and tab bodies are plain Columns: a Column derives implicitHeight
// from its children and positions them by height alone.
Column {
  id: root
  property var statusData: null; property int tab: 0; property string version: ""; property string now: ""
  property bool busy: false; property bool motion: true; property var checkedPaths: ({}); property var hiddenPaths: []
  property bool showHidden: false; property bool showExisting: false; property bool setupNeeded: false; property bool notSetUp: false; property string focusedKey: ""; property var packages: []; property var setupBackups: []
  property color foreground: Color.foreground
  signal reviewRequested(); signal publishRequested(); signal updateRequested()
  signal restowRequested(string repo, string packageName); signal adoptRequested(var candidate); signal ignoreRequested(var candidate)
  signal copyRequested(string value); signal selectAllRequested(); signal selectRepoRequested(); signal clearSelectionRequested()
  signal showHiddenToggled(); signal showExistingToggled(); signal setupRequested(); signal changeToggled(string key, bool value); signal changeHovered(string key)
  signal diffRequested(string repo, string path); signal undoSetupRequested()
  property string packageKey: ""
  // One accordion key for the Overview (finding 84): a repo lane uses
  // "repo:<path>", a group card uses its key; opening one closes the other.
  property string expandedKey: ""
  readonly property var repos: (root.statusData && root.statusData.repos) || []
  readonly property var groups: Model.overviewGroups(root.statusData)
  readonly property var changeView: Model.changesView(root.statusData, { hiddenPaths: root.hiddenPaths, showHidden: root.showHidden, showExisting: root.showExisting })
  readonly property int changes: Model.changeTotals(root.statusData).count
  readonly property int behind: Model.flowTotals(root.statusData, "behind").count
  readonly property int fresh: Model.newCandidateCount(root.statusData)
  readonly property int hiddenCount: root.hiddenPaths.length
  readonly property var firstUnhealthy: Model.firstUnhealthy(root.statusData)
  readonly property var overview: Model.overviewState(root.statusData, { notSetUp: root.notSetUp, setupNeeded: root.setupNeeded }) // finding 76
  readonly property bool anySelected: Model.anyChecked(root.changeView.rows, root.checkedPaths)
  function groupExpanded(key) { return root.expandedKey === String(key) }
  function expandGroup(key) { root.expandedKey = String(key) }
  function toggleGroup(key) { root.expandedKey = Model.accordionKey(root.expandedKey, String(key)) }
  function repoExpanded(path, index) { return root.expandedKey === "" ? index === 0 : root.expandedKey === ("repo:" + String(path)) }
  function toggleRepo(path) { root.expandedKey = Model.accordionKey(root.expandedKey, "repo:" + String(path)) }
  function togglePackageChip(key) { root.packageKey = root.packageKey === key ? "" : key }
  function isChecked(key) { return root.checkedPaths[key] !== false }
  width: parent ? parent.width : 0
  height: childrenRect.height
  spacing: Style.spacing.xxl
  // ---- Overview ---------------------------------------------------------
  Column {
    id: overviewBody
    width: root.width
    visible: root.tab === 0
    spacing: Style.spacing.xxl
    Bridge {
      width: parent.width
      bridge: Model.bridgeState(root.statusData, { notSetUp: root.notSetUp })
      sentence: Model.explain(root.statusData, { notSetUp: root.notSetUp })
      busy: root.busy
      motion: root.motion
      foreground: root.foreground
    }
    SetupBanner {
      width: parent.width; visible: root.overview.showSetupCard; foreground: root.foreground; onSetupRequested: root.setupRequested()
    }
    Text { width: parent.width; visible: root.overview.showUpdateHint; text: root.overview.updateHint; color: Util.alpha(root.foreground, 0.72); font.family: Style.font.family; font.pixelSize: Style.font.caption }
    BorderSurface {
      width: parent.width
      visible: root.fresh > 0 && root.overview.showManagement
      implicitHeight: bannerRow.implicitHeight + Style.spacing.lg * 2
      color: Util.alpha(Color.accent, 0.10)
      borderSpec: Border.none()
      radius: Style.cornerRadius
      RowLayout {
        id: bannerRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.xxl
        anchors.rightMargin: Style.spacing.xxl
        spacing: Style.spacing.lg
        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: Model.plural(root.fresh, " new config file is not in Stow", " new config files are not in Stow")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
        }
        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: "Review"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.toggleGroup("newConfigs") }
    }
    Row {
      width: parent.width
      visible: root.overview.showManagement && (root.changes > 0 || root.fresh > 0 || root.behind > 0 || root.firstUnhealthy !== null)
      spacing: Style.spacing.lg
      Button { visible: root.changes > 0 || root.fresh > 0 || root.behind > 0; text: "Review Changes"; iconText: "\uf044"; fontSize: Style.font.caption; onClicked: root.reviewRequested() }
      Button { visible: root.behind > 0; text: "Update"; iconText: "\uf0ed"; fontSize: Style.font.caption; onClicked: root.updateRequested() }
      Button { visible: root.changes > 0; text: "Publish"; iconText: "\uf0ee"; fontSize: Style.font.caption; enabled: !root.busy; onClicked: root.publishRequested() }
      Button {
        visible: root.firstUnhealthy !== null; text: "Fix packages"; iconText: "\uf0ad"; fontSize: Style.font.caption; enabled: !root.busy
        onClicked: if (root.firstUnhealthy) root.restowRequested(root.firstUnhealthy.repo, root.firstUnhealthy.package)
      }
    }
    Repeater {
      model: root.repos
      RepoLane {
        required property var modelData
        required property int index
        width: parent.width
        // Hide the empty lanes on a machine that is not set up yet (finding 49).
        visible: !root.notSetUp
        lane: Model.repoLaneSummary(modelData, root.now, { neutral: root.notSetUp })
        repo: modelData
        version: root.version
        now: root.now
        expanded: root.repoExpanded(String(modelData.path || ""), index)
        motion: root.motion
        foreground: root.foreground
        onToggled: root.toggleRepo(String(modelData.path || ""))
        onCopyRequested: function(value) { root.copyRequested(value) }
      }
    }
    Repeater {
      model: root.groups
      GroupCard {
        required property var modelData
        width: parent.width
        visible: root.overview.showManagement && (modelData.key !== "newConfigs" || root.groupExpanded("newConfigs"))
        title: modelData.title
        subtitle: modelData.subtitle
        count: String(modelData.count)
        unit: modelData.unit
        expanded: root.groupExpanded(modelData.key)
        motion: root.motion
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
              primary: modelData.type === "health" ? String(modelData.title) : (modelData.type === "incoming" ? (String(modelData.hash) + "  " + String(modelData.subject)) : String(modelData.path))
              secondary: modelData.type === "health" ? String(modelData.subtitle) : (modelData.type === "incoming" ? Model.repoDisplayName(modelData.repo) : String(modelData.package))
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
              credential: modelData.credential === true
              packageName: Model.candidateSuggestion({ suggested_package: modelData.package, credential: modelData.credential })
              foreground: root.foreground
              onAdoptRequested: root.adoptRequested(modelData)
              onIgnoreRequested: root.ignoreRequested(modelData)
            }
          }
        }
      }
    }
    SetupLine { width: parent.width; backups: root.setupBackups; busy: root.busy; notSetUp: root.notSetUp; foreground: root.foreground; onUndoRequested: root.undoSetupRequested() }
  }
  // ---- Changes ----------------------------------------------------------
  Column {
    id: changesBody
    // Reserve the scrollbar gutter so no row, toggle or count sits under it
    // (finding 97), like the Overview body.
    width: root.width - Style.space(12)
    visible: root.tab === 1
    spacing: Style.spacing.xxl
    Text {
      width: parent.width; textFormat: Text.PlainText; text: Model.explain(root.statusData, { notSetUp: root.notSetUp })
      color: Util.alpha(root.foreground, 0.72); font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
    }
    Row {
      width: parent.width
      spacing: Style.spacing.lg
      Button { text: "Select all"; bordered: true; fontSize: Style.font.caption; onClicked: root.selectAllRequested() }
      Button { text: "Select repo \u25b8"; bordered: true; fontSize: Style.font.caption; onClicked: root.selectRepoRequested() }
      Button { text: "Clear"; bordered: true; fontSize: Style.font.caption; onClicked: root.clearSelectionRequested() }
      Button { text: "Hidden (" + root.hiddenCount + ")"; iconText: "\uf070"; fontSize: Style.font.caption; bordered: true; onClicked: root.showHiddenToggled() }
    }
    Button {
      text: "Publish selected"; iconText: "\uf0ee"; background: Color.accent; foreground: Color.background; horizontalPadding: Style.space(16); fontSize: Style.font.caption
      enabled: root.anySelected && !root.busy
      onClicked: root.publishRequested()
    }
    BorderSurface {
      width: parent.width
      implicitHeight: toggleRow.implicitHeight + Style.spacing.xxl * 2
      color: Util.alpha(Color.foreground, 0.04)
      borderSpec: Border.none()
      radius: Style.cornerRadius
      padding: Style.spacing.xxl
      RowLayout {
        id: toggleRow
        width: parent.width
        spacing: Style.spacing.lg
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.xxs
          Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: "Show existing untracked files"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }
          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "Files that already existed when Stow Sync was installed. They are not counted in the badge."
            color: Util.alpha(root.foreground, 0.72)
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
        subtitle: modelData.subtitle
        count: String(modelData.count)
        unit: modelData.unit
        expanded: root.groupExpanded("repo:" + modelData.key)
        motion: root.motion
        onToggled: root.toggleGroup("repo:" + modelData.key)
        Repeater {
          model: modelData.packages
          Column {
            required property var modelData
            width: parent ? parent.width : 0
            spacing: Style.spacing.xxs
            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: modelData.label + "  \u00b7  " + Model.pluralCount(modelData.count, "file")
              color: Util.alpha(root.foreground, 0.72)
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
                chip: String(modelData.chip)
                splitPath: true
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
    spacing: Style.spacing.xxl
    PackageGrid {
      width: parent.width
      packages: root.packages
      expandedKey: root.packageKey
      busy: root.busy
      motion: root.motion
      foreground: root.foreground
      onExpandRequested: function(key) { root.togglePackageChip(key) }
      onRestowRequested: function(repo, packageName) { root.restowRequested(repo, packageName) }
    }
  }
}
