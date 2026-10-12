pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Report step body of the setup wizard (README 10b.6 / 11d). Grouped results as
// collapsible rows (Packages and Moved collapsed, Services/Steps/notes expanded),
// the backup folder path (elided in the middle, copyable), every post step with
// its state and last output line, the notes again and the Undo result card. The
// Undo button and Done are pinned in the wizard footer.
Column {
  id: root

  property var report: null
  property var undoResult: null
  property string undoError: ""
  property bool busy: false
  property color foreground: Color.foreground
  property var expanded: ({})
  property string hoveredKey: ""

  readonly property var sections: (root.report && root.report.sections) || []
  readonly property var undo: Model.setupUndoResult(root.undoResult)

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  function copyText(text) {
    if (String(text) !== "") Util.execArgv(["wl-copy", String(text)])
  }

  function isExpanded(group) {
    return Model.setupGroupExpanded(root.expanded, group)
  }

  function rightText(item) {
    if (item && item.state !== undefined) return String(item.state)
    return String((item && item.detail) || "")
  }

  function toggle(group) {
    root.expanded = Model.setupToggleGroup(root.expanded, group)
  }

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: root.undoResult !== null
      ? "This setup was undone. Everything below is what it did before you undid it."
      : "Setup finished. Everything below is what Stow Sync did on this machine."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  // Report-path Undo failure (finding 80): always visible, never cleared by a
  // status refresh.
  Text {
    width: parent.width
    visible: root.undoError !== ""
    textFormat: Text.PlainText
    text: root.undoError
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  // Undo result card (README 11b.3/finding 73): the undo result comes first,
  // right under the summary sentence; the sections below are the greyed history.
  Column {
    width: parent.width
    visible: root.undoResult !== null
    spacing: Style.spacing.xs

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.undo.ok ? "Setup undone" : "Undo finished with problems"
      color: root.undo.ok ? Color.accent : Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
    }

    Repeater {
      model: root.undo.lines

      RowLayout {
        required property var modelData
        width: parent.width
        spacing: Style.spacing.md

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
          Layout.maximumWidth: Style.space(200)
          visible: String(modelData.detail || "") !== ""
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: String(modelData.tone) === "urgent" ? Color.urgent : Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignRight
        }
      }
    }
  }

  RowLayout {
    width: parent.width
    visible: root.report !== null && String(root.report.backupDir || "") !== ""
    spacing: Style.spacing.sm

    Text {
      Layout.fillWidth: true
      textFormat: Text.PlainText
      // Elide in the middle so the timestamp at the end is never lost (finding 41).
      text: String(root.report ? root.report.backupDir : "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: "monospace"
      font.pixelSize: Style.font.caption
      elide: Text.ElideMiddle
      wrapMode: Text.NoWrap
    }

    Button {
      Layout.alignment: Qt.AlignVCenter
      text: "Copy"
      iconText: "\uf0c5"
      fontSize: Style.font.caption
      onClicked: root.copyText(String(root.report ? root.report.backupDir : ""))
    }
  }

  Repeater {
    model: root.sections

    Column {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.xs

      SetupGroupHeader {
        title: String(modelData.title || "") + (modelData.undone ? "  \u00b7  undone" : "")
        count: modelData.count !== undefined ? Number(modelData.count) : modelData.items.length
        unit: String(modelData.unit || "")
        tone: modelData.undone ? "muted" : String(modelData.tone || "muted")
        expanded: root.isExpanded(modelData)
        focused: root.hoveredKey === String(modelData.key)
        foreground: root.foreground
        onToggled: root.toggle(modelData)
        onHoverChanged: function(hovered) {
          if (hovered) root.hoveredKey = String(modelData.key)
          else if (root.hoveredKey === String(modelData.key)) root.hoveredKey = ""
        }
      }

      Column {
        width: parent.width
        spacing: Style.spacing.xs
        visible: root.isExpanded(modelData)
        opacity: modelData.undone ? 0.6 : 1

        Repeater {
          model: modelData.items

          Column {
            required property var modelData
            width: parent.width
            spacing: 2

            RowLayout {
              width: parent.width
              spacing: Style.spacing.md

              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(modelData.label || "")
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: root.rightText(modelData) === "" ? Text.WordWrap : Text.NoWrap
                elide: root.rightText(modelData) === "" ? Text.ElideNone : Text.ElideRight
              }

              Text {
                Layout.maximumWidth: Style.space(180)
                visible: root.rightText(modelData) !== ""
                textFormat: Text.PlainText
                text: root.rightText(modelData)
                color: root.toneColor(String(modelData.tone || "muted"))
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignRight
              }
            }

            Text {
              width: parent.width
              visible: String(modelData.sub || "") !== ""
              textFormat: Text.PlainText
              text: String(modelData.sub || "")
              color: Util.alpha(root.foreground, 0.72)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
              horizontalAlignment: Text.AlignLeft
            }
          }
        }
      }
    }
  }

  Text {
    width: parent.width
    visible: root.report !== null && root.report.backup !== ""
    textFormat: Text.PlainText
    text: "Backup " + String(root.report ? root.report.backup : "") + (root.undoResult !== null ? "  \u00b7  undone" : "")
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
