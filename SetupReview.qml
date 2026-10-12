pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Review step body of the setup wizard (README 10b.5 / 11a.1). Each plan group
// is a collapsible summary row with a full-row click target, a hover/focus fill
// and a clear chevron; Missing tools and Still to do start expanded. Notes wrap
// and are never elided. Post steps whose tool is missing render disabled.
Column {
  id: root

  property var plan: null
  property bool planLoading: false
  property var postChecked: ({})
  property var expanded: ({})
  property string focusedKey: ""
  property string hoveredKey: ""
  property bool busy: false
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)
  signal groupToggled(string key)

  readonly property var groups: Model.setupPlanGroups(root.plan)

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  function isExpanded(group) {
    return Model.setupGroupExpanded(root.expanded, group)
  }

  Text {
    width: parent.width
    visible: root.planLoading
    textFormat: Text.PlainText
    text: "Building the plan\u2026"
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  Text {
    width: parent.width
    visible: !root.planLoading && root.plan !== null
    textFormat: Text.PlainText
    text: Model.setupReviewSummary(root.plan, Model.setupSelectedPostCount(root.plan, root.postChecked))
    color: root.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Repeater {
    model: root.groups

    Column {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.xs
      visible: modelData.items.length > 0

      SetupGroupHeader {
        title: String(modelData.title || "")
        count: modelData.count !== undefined ? Number(modelData.count) : -1
        unit: String(modelData.unit || "")
        tone: String(modelData.tone || "muted")
        expanded: root.isExpanded(modelData)
        focused: root.focusedKey === String(modelData.key) || root.hoveredKey === String(modelData.key)
        foreground: root.foreground
        onToggled: root.groupToggled(String(modelData.key))
        onHoverChanged: function(hovered) {
          if (hovered) root.hoveredKey = String(modelData.key)
          else if (root.hoveredKey === String(modelData.key)) root.hoveredKey = ""
        }
      }

      Column {
        width: parent.width
        spacing: Style.spacing.xs
        visible: root.isExpanded(modelData)

        Repeater {
          model: modelData.items

          Column {
            required property var modelData
            width: parent.width
            spacing: 2

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
                wrapMode: String(modelData.detail || "") === "" ? Text.WordWrap : Text.NoWrap
                elide: String(modelData.detail || "") === "" ? Text.ElideNone : Text.ElideRight
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

            Column {
              width: parent.width
              spacing: 2
              visible: modelData.default === undefined && (modelData.sub || []).length > 0

              Repeater {
                model: modelData.sub || []

                Text {
                  required property var modelData
                  width: parent.width
                  textFormat: Text.PlainText
                  text: String(modelData)
                  color: Util.alpha(root.foreground, 0.72)
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }
            }

            // One row style for every Afterwards step (finding 70): label with
            // its On/Off wording, then the switch, or the reason in its place.
            RowLayout {
              id: postRow
              width: parent.width
              visible: modelData.default !== undefined
              spacing: Style.spacing.md

              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(modelData.label || "") + "   \u00b7   " + Model.setupToggleLabel(root.postChecked[String(modelData.id || "")] === true)
                color: modelData.available === false ? Util.alpha(root.foreground, 0.72) : root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }

              ToggleSwitch {
                Layout.alignment: Qt.AlignVCenter
                visible: modelData.available !== false
                checked: root.postChecked[String(modelData.id || "")] === true
                enabled: !root.busy
                onToggled: root.postToggled(String(modelData.id || ""), !checked)
              }

              Text {
                Layout.alignment: Qt.AlignVCenter
                visible: modelData.available === false
                textFormat: Text.PlainText
                text: String(modelData.detail || "unavailable")
                color: Util.alpha(root.foreground, 0.72)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }
    }
  }

  Item {
    width: 1
    height: Style.spacing.sm
  }
}
