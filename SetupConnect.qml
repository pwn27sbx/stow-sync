pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Connect step body (README 11a.3 / 11b.2/11b.4 / 11c.2/11c.3): the candidate
// repo picker, the "loading your repos" state with a retry, the live clone
// progress bar, the per-repo result checklist and the GitHub auth fix.
Column {
  id: root

  property var candidates: null
  property string selectedUrl: ""
  property string url: ""
  property bool repoLoading: false
  property string repoError: ""
  property var connectEntries: []
  property bool connectRunning: false
  property var clone: null
  property string loginDetail: ""
  property var authFix: null
  property bool motion: true
  property color foreground: Color.foreground

  signal repoPicked(string url)
  signal urlEdited(string text)
  signal repoRetryRequested()
  signal checkAgainRequested()

  readonly property bool showPicker: root.candidates !== null && !root.repoLoading && root.repoError === "" && !root.connectRunning && root.connectEntries.length === 0

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  Text {
    width: parent.width
    visible: root.repoLoading
    textFormat: Text.PlainText
    text: "Loading your GitHub repos\u2026"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  Column {
    width: parent.width
    visible: root.repoError !== "" && root.candidates === null && !root.connectRunning
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.repoError
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Button {
      text: "Retry"
      iconText: "\uf021"
      fontSize: Style.font.caption
      onClicked: root.repoRetryRequested()
    }
  }

  // Download view (README 12c finding 53): one card per repo with a real
  // progress bar, size and state; the overall line on top.
  Column {
    width: parent.width
    visible: root.connectEntries.length > 0
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: Model.setupDownloadSummary(root.connectEntries)
      color: root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
    }

    Repeater {
      model: Model.setupDownloadCards(root.connectEntries, root.clone)

      Rectangle {
        required property var modelData
        width: parent.width
        implicitHeight: cardColumn.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: Util.alpha(root.foreground, 0.03)

        Column {
          id: cardColumn
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(12)
          anchors.rightMargin: Style.space(12)
          spacing: Style.spacing.xs

          RowLayout {
            width: parent.width
            spacing: Style.spacing.md

            Text {
              Layout.alignment: Qt.AlignVCenter
              textFormat: Text.PlainText
              text: (modelData.state === "cloned" || modelData.state === "ready") ? "\uf00c"
                : (modelData.state === "error" ? "\uf00d" : (modelData.state === "cloning" ? "\uf110" : "\uf10c"))
              color: modelData.tone === "urgent" ? Color.urgent : (modelData.tone === "accent" ? Color.accent : Util.alpha(root.foreground, 0.72))
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            Text {
              Layout.fillWidth: true
              textFormat: Text.PlainText
              text: String(modelData.label || "")
              color: root.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            Text {
              Layout.alignment: Qt.AlignVCenter
              textFormat: Text.PlainText
              text: String(modelData.size || "")
              color: Util.alpha(root.foreground, 0.72)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          SetupProgress {
            width: parent.width
            visible: modelData.state === "cloning"
            value: modelData.percent >= 0 ? modelData.percent / 100 : -1
            active: modelData.state === "cloning"
            motion: root.motion
            foreground: root.foreground
          }

          Text {
            width: parent.width
            visible: String(modelData.detail || "") !== ""
            textFormat: Text.PlainText
            text: String(modelData.detail || "")
            color: root.toneColor(String(modelData.tone || "muted"))
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }
      }
    }
  }

  SetupRepoPicker {
    width: parent.width
    visible: root.showPicker
    candidates: root.candidates
    selectedUrl: root.selectedUrl
    url: root.url
    foreground: root.foreground
    onRepoPicked: function(url) { root.repoPicked(url) }
    onUrlEdited: function(text) { root.urlEdited(text) }
  }

  Column {
    width: parent.width
    visible: root.authFix !== null
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "GitHub login needed to download a private repo"
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.loginDetail !== "" ? root.loginDetail : String(root.authFix ? root.authFix.detail : "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    TextEdit {
      width: parent.width
      Layout.preferredHeight: implicitHeight
      text: String(root.authFix ? root.authFix.command : "")
      color: Color.accent
      font.family: "monospace"
      font.pixelSize: Style.font.caption
      readOnly: true
      selectByMouse: true
      wrapMode: TextEdit.NoWrap
      clip: true
    }

    Button {
      text: "Check again"
      iconText: "\uf021"
      fontSize: Style.font.caption
      onClicked: root.checkAgainRequested()
    }
  }
}
