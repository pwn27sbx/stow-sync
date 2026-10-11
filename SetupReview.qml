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

  Repeater {
    model: root.groups

    Column {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.xs
      visible: modelData.items.length > 0

      Rectangle {
        id: header
        width: parent.width
        implicitHeight: headerRow.implicitHeight + Style.spacing.sm
        radius: Style.cornerRadius
        color: (root.focusedKey === modelData.key || root.hoveredKey === modelData.key)
          ? Util.alpha(root.foreground, 0.06) : "transparent"

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          hoverEnabled: true
          onEntered: root.hoveredKey = String(modelData.key)
          onExited: if (root.hoveredKey === String(modelData.key)) root.hoveredKey = ""
          onClicked: root.groupToggled(String(modelData.key))
        }

        RowLayout {
          id: headerRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.spacing.sm
          anchors.rightMargin: Style.spacing.sm
          spacing: Style.spacing.sm

          Text {
            Layout.alignment: Qt.AlignVCenter
            textFormat: Text.PlainText
            // Font Awesome chevrons; caption size rendered as a dot (finding 37).
            text: root.isExpanded(modelData) ? "\uf078" : "\uf054"
            color: root.toneColor(String(modelData.tone || "muted"))
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(modelData.title || "")
            color: root.toneColor(String(modelData.tone || "muted"))
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            Layout.alignment: Qt.AlignVCenter
            textFormat: Text.PlainText
            text: String(modelData.count) + (String(modelData.unit || "") !== "" ? " " + String(modelData.unit) : "")
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.spacing.xs
        visible: root.isExpanded(modelData)

        Repeater {
          model: modelData.items

          Item {
            required property var modelData
            width: parent.width
            implicitHeight: modelData.default !== undefined ? (modelData.available === false ? disabledRow.implicitHeight : postToggle.implicitHeight) : plainRow.implicitHeight

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

            Toggle {
              id: postToggle
              width: parent.width
              visible: modelData.default !== undefined && modelData.available !== false
              label: String(modelData.label || "")
              foreground: root.foreground
              enabled: !root.busy
              checked: root.postChecked[String(modelData.id || "")] === true
              onClicked: root.postToggled(String(modelData.id || ""), !checked)
            }

            RowLayout {
              id: disabledRow
              width: parent.width
              visible: modelData.default !== undefined && modelData.available === false
              spacing: Style.spacing.md

              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(modelData.label || "")
                color: Util.alpha(root.foreground, 0.72)
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }

              Text {
                Layout.alignment: Qt.AlignVCenter
                textFormat: Text.PlainText
                text: String(modelData.detail || "unavailable")
                color: Color.urgent
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
