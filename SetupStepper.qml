pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Five-step orientation strip for the setup wizard (README 12c finding 51):
// done (check), current (filled dot) and next (hollow dot) per step. Pure
// rendering; the current index comes from SetupFlow.
RowLayout {
  id: root

  property var steps: []
  property int current: 0
  property color foreground: Color.foreground

  spacing: Style.spacing.xs

  Repeater {
    model: root.steps

    ColumnLayout {
      required property int index
      required property var modelData
      Layout.fillWidth: true
      spacing: 2

      readonly property string state: Model.setupWizardStepState(index, root.current)
      readonly property color tone: state === "next" ? Util.alpha(root.foreground, 0.5)
        : (state === "current" ? Color.accent : root.foreground)

      Text {
        Layout.alignment: Qt.AlignHCenter
        textFormat: Text.PlainText
        text: parent.state === "done" ? "\uf00c" : (parent.state === "current" ? "\uf111" : "\uf10c")
        color: parent.tone
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: String(modelData || "")
        color: parent.tone
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
      }
    }
  }
}
