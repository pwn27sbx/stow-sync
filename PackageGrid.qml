pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Packages tab: every package is a chip wrapping in a Flow, coloured by health.
// Clicking a chip expands that package's file list below the grid (one at a
// time). Expanded rows fade away when a different chip is chosen.
Item {
  id: root

  property var packages: []
  property string expandedKey: ""
  property bool busy: false
  property bool motion: true
  property color foreground: Color.foreground

  signal expandRequested(string key)
  signal restowRequested(string repo, string packageName)

  function keyOf(card) {
    return String((card && card.repo) || "") + ":" + String((card && card.name) || "")
  }

  function chipFor(state) {
    var s = String(state || "")
    if (s === "added") return "A"
    if (s === "deleted") return "D"
    if (s === "untracked") return "?"
    return "M"
  }

  function chipToneColor(letter) {
    if (letter === "D") return Color.urgent
    if (letter === "A") return Qt.lighter(Color.accent, 1.35)
    if (letter === "?") return Util.alpha(root.foreground, 0.6)
    return Color.accent
  }

  readonly property var expandedCard: {
    for (var i = 0; i < root.packages.length; i++) {
      if (keyOf(root.packages[i]) === root.expandedKey) return root.packages[i]
    }
    return null
  }

  implicitHeight: column.implicitHeight

  Column {
    id: column
    width: parent.width
    spacing: Style.spacing.lg

    Flow {
      width: parent.width
      spacing: Style.spacing.sm

      Repeater {
        model: root.packages

        PackageChip {
          required property var modelData
          card: modelData
          state: Model.packageChipState(modelData)
          expanded: root.keyOf(modelData) === root.expandedKey
          motion: root.motion
          foreground: root.foreground
          onToggled: root.expandRequested(root.keyOf(modelData))
        }
      }
    }

    Item {
      id: detailWrap
      width: parent.width
      clip: true
      implicitHeight: root.expandedCard !== null ? detail.implicitHeight : 0

      Behavior on implicitHeight {
        enabled: root.motion
        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
      }

      BorderSurface {
        id: detail
        width: parent.width
        visible: root.expandedCard !== null
        implicitHeight: detailInner.implicitHeight + Style.spacing.xxl * 2
        radius: Style.space(10)
        color: Util.alpha(Color.foreground, 0.04)
        borderSpec: Border.none()

        Column {
          id: detailInner
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.spacing.xxl
          anchors.rightMargin: Style.spacing.xxl
          spacing: Style.spacing.sm

          RowLayout {
            width: parent.width
            spacing: Style.spacing.sm

            Text {
              Layout.fillWidth: true
              textFormat: Text.PlainText
              text: String((root.expandedCard && root.expandedCard.name) || "") + "  \u00b7  " +
                Model.pluralCount((root.expandedCard && root.expandedCard.count) || 0, "file")
              color: root.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              elide: Text.ElideRight
            }

            Button {
              Layout.alignment: Qt.AlignVCenter
              text: "Restow"
              iconText: "\uf021"
              fontSize: Style.font.caption
              horizontalPadding: Style.spacing.sm
              verticalPadding: Style.spacing.xxs
              enabled: !root.busy
              onClicked: if (root.expandedCard) root.restowRequested(String(root.expandedCard.repo), String(root.expandedCard.name))
            }
          }

          Text {
            width: parent.width
            visible: root.expandedCard !== null && (root.expandedCard.count || 0) === 0
            textFormat: Text.PlainText
            text: Model.healthLabel(String((root.expandedCard && root.expandedCard.health) || "ok")) === "ok"
              ? "No changed files."
              : "Needs fixing: " + Model.healthLabel(String(root.expandedCard.health))
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Repeater {
            model: root.expandedCard ? root.expandedCard.files : []

            RowLayout {
              required property var modelData
              width: parent.width
              spacing: Style.spacing.sm

              Rectangle {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Style.space(16)
                Layout.preferredHeight: Style.space(16)
                radius: Style.space(6)
                color: Util.alpha(root.chipToneColor(root.chipFor(modelData.state)), 0.16)
                Text {
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: root.chipFor(modelData.state)
                  color: root.chipToneColor(root.chipFor(modelData.state))
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
              }

              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(modelData.path)
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideMiddle
              }
            }
          }
        }
      }
    }
  }
}
