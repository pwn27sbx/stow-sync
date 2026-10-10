pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Opt-in "Set up this machine" wizard (README section 8b). Modal overlay with
// four steps: Connect, Review, Apply, Report. It owns its own state and asks
// Panel to run backend commands through `requested`; Panel feeds every result
// back with handleResult/handleFailure. Only instantiated when machineSetup is
// true, so a user who never enables it sees nothing setup-related.
Item {
  id: root

  property bool opened: false
  property var settings: ({})
  property var statusData: null
  property bool busy: false
  property bool motion: true
  property color foreground: Color.foreground

  signal requested(string tag, var args)
  signal closed()

  property int step: 0
  property string url: ""
  property var connectResult: null
  property var plan: null
  property string planToken: ""
  property bool planLoading: false
  property var applyResult: null
  property var undoResult: null
  property var postChecked: ({})
  property string errorText: ""
  property bool applying: false

  readonly property bool running: root.applying
  readonly property bool contentActiveFocus: urlField.activeFocus
  readonly property var stepRows: Model.setupStepState(root.applyResult)
  readonly property var report: Model.setupReport(root.applyResult)
  readonly property var stepNames: ["Connect", "Review", "Apply", "Report"]

  visible: opened
  onOpenedChanged: if (opened) root.start()

  function start() {
    root.step = 0
    root.url = Model.setupPrefillUrl(root.statusData)
    root.connectResult = null
    root.plan = null
    root.planToken = ""
    root.planLoading = false
    root.applyResult = null
    root.undoResult = null
    root.postChecked = ({})
    root.errorText = ""
    root.applying = false
    // Hidden setupFixture (README 8b live check): render a recorded plan
    // straight into Review, read-only, without touching Connect or Apply.
    var fixture = root.settings ? String(root.settings.setupFixture || "") : ""
    if (fixture !== "") { root.step = 1; root.loadPlan() }
  }

  function selectedPostIds() {
    var ids = []
    var post = (root.plan && root.plan.post) || []
    for (var i = 0; i < post.length; i++) {
      var id = String(post[i].id || "")
      var checked = root.postChecked[id] !== undefined ? root.postChecked[id] === true : post[i].default === true
      if (checked) ids.push(id)
    }
    return ids
  }

  function primaryLabel() {
    if (root.step === 0) return root.connectResult ? "Review" : "Connect"
    if (root.step === 1) return root.planToken === "fixture" ? "Close" : Model.setupPrimaryLabel(root.plan)
    if (root.step === 2) return root.applying ? "Setting up\u2026" : (root.applyResult ? "Continue" : "Set up")
    return "Finish"
  }

  function primary() {
    if (root.running) return
    if (root.step === 0) {
      if (!root.connectResult) {
        if (String(root.url).trim() === "") { root.errorText = "Enter the dotfiles repository URL."; return }
        root.errorText = ""
        root.requested("setup-connect", ["setup-connect", "--url", root.url])
      } else {
        root.step = 1
        root.loadPlan()
      }
      return
    }
    if (root.step === 1) {
      if (root.planToken === "fixture") { root.closed(); return }
      if (root.planLoading) return
      root.step = 2
      root.applying = true
      root.errorText = ""
      root.requested("setup-apply", ["setup-apply", "--token", root.planToken, "--post", root.selectedPostIds().join(",")])
      return
    }
    if (root.step === 2) {
      if (root.applyResult) root.step = 3
      return
    }
    root.closed()
  }

  function loadPlan() {
    root.planLoading = true
    root.errorText = ""
    var args = ["setup-plan"]
    var fixture = root.settings ? String(root.settings.setupFixture || "") : ""
    if (fixture !== "") args = args.concat(["--fixture", fixture])
    root.requested("setup-plan", args)
  }

  function back() {
    if (root.running) { root.errorText = "Setup is running"; return }
    if (root.step === 1 || root.step === 2) { root.step = 0; return }
    root.closed()
  }

  function undo() {
    if (root.running || !root.applyResult) return
    root.errorText = ""
    root.requested("setup-undo", ["setup-undo", "--backup", String(root.applyResult.backup || "")])
  }

  function handleResult(tag, payload) {
    if (tag === "setup-connect") {
      if (!payload || payload.ok === false) { root.errorText = String(payload && payload.error || "Connect failed."); return }
      root.connectResult = payload
      return
    }
    if (tag === "setup-plan") {
      root.planLoading = false
      if (!payload || payload.ok === false) { root.errorText = String(payload && payload.error || "Could not build the plan."); return }
      root.plan = payload.plan
      root.planToken = String(payload.token || "")
      var selection = {}
      var post = (payload.plan && payload.plan.post) || []
      for (var i = 0; i < post.length; i++) selection[String(post[i].id || "")] = post[i].default === true
      root.postChecked = selection
      return
    }
    if (tag === "setup-apply") {
      root.applying = false
      if (!payload || payload.ok === false) { root.errorText = String(payload && payload.error || "Setup failed."); return }
      root.applyResult = payload
      return
    }
    if (tag === "setup-undo") {
      if (!payload || payload.ok === false) { root.errorText = String(payload && payload.error || "Undo failed."); return }
      root.undoResult = payload
      return
    }
  }

  function handleFailure(tag, message) {
    root.applying = false
    root.planLoading = false
    root.errorText = String(message || "The helper failed.")
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.72)

    MouseArea {
      anchors.fill: parent
      onClicked: if (!root.running) root.closed()
    }

    BorderSurface {
      id: card
      width: Math.min(parent.width - Style.space(24), Style.space(560))
      height: Math.min(parent.height - Style.space(16), Style.space(460))
      anchors.centerIn: parent
      color: Color.popups.background
      borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
      padding: Style.space(16)
      radius: Style.space(10)

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: inner
        anchors.fill: parent
        anchors.margins: card.contentTopInset

        Column {
          id: chrome
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: Style.spacing.sm

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: "Set up this machine"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: "Step " + (root.step + 1) + " of 4 \u00b7 " + root.stepNames[root.step]
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          TextField {
            id: urlField
            width: parent.width
            visible: root.step === 0
            text: root.url
            placeholderText: "https://github.com/<you>/dotfiles.git"
            foreground: root.foreground
            onTextEdited: root.url = text
            onAccepted: root.primary()
          }

          Text {
            width: parent.width
            visible: root.errorText !== ""
            textFormat: Text.PlainText
            text: root.errorText
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }
        }

        Flickable {
          id: bodyArea
          anchors.top: chrome.bottom
          anchors.topMargin: Style.spacing.sm
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(Style.space(60), inner.height - chrome.height - buttonRow.height - Style.space(20))
          clip: true
          contentWidth: width
          contentHeight: body.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          SetupStep {
            id: body
            width: bodyArea.width
            step: root.step
            connectRows: Model.setupConnectRows(root.connectResult)
            plan: root.plan
            planLoading: root.planLoading
            stepRows: root.stepRows
            report: root.report
            undoResult: root.undoResult
            postChecked: root.postChecked
            busy: root.busy
            foreground: root.foreground
            onPostToggled: function(id, value) { var next = {}; for (var k in root.postChecked) next[k] = root.postChecked[k]; next[id] = value; root.postChecked = next }
            onUndoRequested: root.undo()
          }
        }

        Row {
          id: buttonRow
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          spacing: Style.spacing.sm

          Button {
            text: root.step === 0 ? "Cancel" : (root.step === 3 ? "Close" : "Back")
            enabled: !root.running
            onClicked: root.back()
          }

          Button {
            text: root.primaryLabel()
            enabled: !root.running && !root.planLoading
            onClicked: root.primary()
          }
        }
      }
    }
  }
}
