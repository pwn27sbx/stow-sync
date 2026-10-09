import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// The three-tab bar. Number keys and left/right arrows are handled by the
// panel; this component only renders the buttons and reports clicks.
Item {
  id: root

  property var tabs: []
  property int current: 0
  property color foreground: Color.foreground

  signal selected(int index)

  implicitHeight: row.implicitHeight

  RowLayout {
    id: row
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.space(4)

    Repeater {
      model: root.tabs

      Button {
        required property var modelData
        required property int index
        Layout.fillWidth: true
        text: String(modelData)
        fontSize: Style.font.caption
        foreground: root.foreground
        selected: root.current === index
        bordered: true
        horizontalPadding: Style.space(2)
        verticalPadding: Style.space(5)
        onClicked: root.selected(index)
      }
    }
  }
}
