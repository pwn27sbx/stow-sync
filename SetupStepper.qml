pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Five-step orientation strip for the setup wizard (README 12c finding 51):
// done (check), current (filled dot) and next (hollow dot) per step, joined by
// connector lines (●──◉──○). Pure rendering; the current index comes from SetupFlow.
Row {
  id: root

  property var steps: []
  property int current: 0
  property color foreground: Color.foreground

  width: parent ? parent.width : 0
  spacing: 0

  Repeater {
    model: root.steps

    Item {
      id: segment

      required property int index
      required property var modelData

      width: root.steps.length > 0 ? root.width / root.steps.length : 0
      height: column.implicitHeight

      readonly property string state: Model.setupWizardStepState(index, root.current)
      readonly property color tone: state === "next" ? Util.alpha(root.foreground, 0.5)
        : (state === "current" ? Color.accent : root.foreground)
      readonly property real lineY: icon.implicitHeight / 2
      readonly property real dotGap: Math.max(3, icon.implicitWidth / 2 + 2)

      Rectangle {
        id: connectorLeft
        visible: segment.index > 0
        x: 0
        width: Math.max(0, segment.width / 2 - segment.dotGap)
        y: segment.lineY
        height: 1
        color: Util.alpha(root.foreground, 0.25)
      }

      Rectangle {
        id: connectorRight
        visible: segment.index < root.steps.length - 1
        x: segment.width / 2 + segment.dotGap
        width: Math.max(0, segment.width / 2 - segment.dotGap)
        y: segment.lineY
        height: 1
        color: Util.alpha(root.foreground, 0.25)
      }

      Column {
        id: column
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(8) // dots -> labels (finding 63)

        Text {
          id: icon
          anchors.horizontalCenter: parent.horizontalCenter
          textFormat: Text.PlainText
          text: segment.state === "done" ? "\uf00c" : (segment.state === "current" ? "\uf111" : "\uf10c")
          color: segment.tone
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          width: Math.min(implicitWidth, segment.width - Style.space(4))
          textFormat: Text.PlainText
          text: String(segment.modelData || "")
          color: segment.tone
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          elide: Text.ElideRight
        }
      }
    }
  }
}
