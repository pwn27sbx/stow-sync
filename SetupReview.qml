pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Review step body of the setup wizard: the plan grouped like the Changes tab,
// with the optional post steps rendered as switches (their recipe default).
Column {
  id: root

  property var plan: null
  property bool planLoading: false
  property var postChecked: ({})
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)

  readonly property var groups: Model.setupPlanGroups(root.plan)

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  Text {
    width: parent.width
    visible: root.planLoading
    textFormat: Text.PlainText
    text: "Working\u2026"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  Repeater {
    model: root.groups

    Column {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.xs

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: String(modelData.title || "")
        color: root.toneColor(String(modelData.tone || "muted"))
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }

      Text {
        width: parent.width
        visible: String(modelData.subtitle || "") !== ""
        textFormat: Text.PlainText
        text: String(modelData.subtitle || "")
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Repeater {
        model: modelData.items

        Item {
          required property var modelData
          width: parent.width
          implicitHeight: modelData.default !== undefined ? postToggle.implicitHeight : plainRow.implicitHeight

          RowLayout {
            id: plainRow
            width: parent.width
            visible: modelData.default === undefined
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
              Layout.maximumWidth: Style.space(160)
              visible: String(modelData.detail || "") !== ""
              textFormat: Text.PlainText
              text: String(modelData.detail || "")
              color: root.toneColor(String(modelData.tone || "muted"))
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignRight
              elide: Text.ElideRight
            }
          }

          Toggle {
            id: postToggle
            width: parent.width
            visible: modelData.default !== undefined
            label: String(modelData.label || "")
            foreground: root.foreground
            checked: root.postChecked[String(modelData.id || "")] === true
            onClicked: root.postToggled(String(modelData.id || ""), !checked)
          }
        }
      }
    }
  }
}
