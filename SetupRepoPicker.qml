pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Connect repo picker (README 12c finding 51): radio cards for the recommended
// repos, the rest behind "Show all repos", and the URL field as a collapsed
// fallback. Pure rendering; selection and URL edits leave through signals.
Column {
  id: root

  property var candidates: null
  property string selectedUrl: ""
  property string url: ""
  property color foreground: Color.foreground
  property bool urlOpen: false
  property bool showAll: false

  signal repoPicked(string url)
  signal urlEdited(string text)

  readonly property var groups: Model.setupCandidateRows(root.candidates)
  readonly property var filteredOthers: Model.setupFilterRows(root.groups.others, filterField.text)

  width: parent ? parent.width : 0
  spacing: Style.spacing.md

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: "Stow Sync will download your repos and link your configs. Nothing is changed until you confirm in Review."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Column {
    width: parent.width
    visible: root.groups.definitive.length > 0
    spacing: Style.spacing.xs

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Your setup repo"
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Repeater {
      model: root.groups.definitive

      SetupRepoCard {
        required property var modelData
        width: parent.width
        name: String(modelData.label || "")
        sentence: String(modelData.sentence || "")
        badges: modelData.badges || []
        selected: String(modelData.value || "") === root.selectedUrl
        foreground: root.foreground
        onPicked: root.repoPicked(String(modelData.value || ""))
      }
    }
  }

  Column {
    width: parent.width
    visible: root.groups.likely.length > 0
    spacing: Style.spacing.xs

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Looks like a dotfiles repo"
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Repeater {
      model: root.groups.likely

      SetupRepoCard {
        required property var modelData
        width: parent.width
        name: String(modelData.label || "")
        sentence: String(modelData.sentence || "")
        badges: modelData.badges || []
        selected: String(modelData.value || "") === root.selectedUrl
        foreground: root.foreground
        onPicked: root.repoPicked(String(modelData.value || ""))
      }
    }
  }

  Column {
    width: parent.width
    visible: root.groups.others.length > 0
    spacing: Style.spacing.xs

    Button {
      text: (root.showAll ? "Hide other repos" : "Show all repos") + " (" + root.groups.others.length + ")"
      iconText: root.showAll ? "\uf077" : "\uf078"
      fontSize: Style.font.caption
      horizontalPadding: Style.space(6)
      verticalPadding: Style.space(3)
      onClicked: root.showAll = !root.showAll
    }

    TextField {
      id: filterField
      width: parent.width
      visible: root.showAll
      placeholderText: "Filter repos"
      foreground: root.foreground
    }

    Flow {
      width: parent.width
      visible: root.showAll
      spacing: Style.spacing.xs

      Repeater {
        model: root.filteredOthers

        Button {
          required property var modelData
          text: String(modelData.label || "")
          fontSize: Style.font.caption
          selected: String(modelData.value || "") === root.selectedUrl
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          onClicked: root.repoPicked(String(modelData.value || ""))
        }
      }
    }
  }

  Button {
    text: root.urlOpen ? "Hide the URL field" : "Use another repo URL"
    iconText: root.urlOpen ? "\uf077" : "\uf078"
    fontSize: Style.font.caption
    horizontalPadding: Style.space(6)
    verticalPadding: Style.space(3)
    onClicked: root.urlOpen = !root.urlOpen
  }

  TextField {
    width: parent.width
    visible: root.urlOpen
    text: root.url
    placeholderText: "https://github.com/<you>/dotfiles.git"
    foreground: root.foreground
    onTextEdited: root.urlEdited(text)
  }
}
