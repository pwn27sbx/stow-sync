pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Repo picker for the Connect step (README 11c.2). Definitive repos (with a
// Stow Sync recipe) come first and are preselected; likely repos follow; every
// other repo is behind "Show all repos" with a filter field. Pure rendering:
// the chosen URL leaves through `repoPicked`.
Column {
  id: root

  property var candidates: null
  property string selectedUrl: ""
  property color foreground: Color.foreground

  signal repoPicked(string url)

  readonly property var groups: Model.setupCandidateRows(root.candidates)
  readonly property var filteredOthers: Model.setupFilterRows(root.groups.others, filterField.text)
  property bool showAll: false

  width: parent ? parent.width : 0
  spacing: Style.spacing.sm

  function chipText(row) {
    var detail = String(row.detail || "")
    return String(row.label || "") + (row.likely ? " \u2605" : "") + (detail !== "" ? "  \u00b7  " + detail : "")
  }

  Column {
    width: parent.width
    visible: root.groups.definitive.length > 0
    spacing: Style.spacing.xs

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Ready to set up"
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Flow {
      width: parent.width
      spacing: Style.spacing.xs

      Repeater {
        model: root.groups.definitive

        Button {
          required property var modelData
          text: root.chipText(modelData)
          fontSize: Style.font.caption
          selected: String(modelData.value || "") === root.selectedUrl
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          onClicked: root.repoPicked(String(modelData.value || ""))
        }
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

    Flow {
      width: parent.width
      spacing: Style.spacing.xs

      Repeater {
        model: root.groups.likely

        Button {
          required property var modelData
          text: root.chipText(modelData)
          fontSize: Style.font.caption
          selected: String(modelData.value || "") === root.selectedUrl
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          onClicked: root.repoPicked(String(modelData.value || ""))
        }
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
          text: root.chipText(modelData)
          fontSize: Style.font.caption
          selected: String(modelData.value || "") === root.selectedUrl
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          onClicked: root.repoPicked(String(modelData.value || ""))
        }
      }
    }
  }
}
