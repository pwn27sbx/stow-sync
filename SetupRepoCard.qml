pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One radio card for the Connect picker (README 12c finding 51): a radio mark,
// the repo name in bold, one plain sentence and small badges. The selected card
// gets an accent border and fill.
Rectangle {
  id: root

  property string name: ""
  property string sentence: ""
  property var badges: []
  property bool selected: false
  property color foreground: Color.foreground

  signal picked()

  width: parent ? parent.width : 0
  implicitHeight: cardRow.implicitHeight + Style.space(16)
  radius: Style.cornerRadius
  color: root.selected ? Util.alpha(Color.accent, 0.10) : Util.alpha(root.foreground, 0.03)
  border.width: root.selected ? Style.normalBorderWidth : 0
  border.color: Color.accent

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.picked()
  }

  RowLayout {
    id: cardRow
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(12)
    spacing: Style.space(12)

    Text {
      Layout.alignment: Qt.AlignVCenter
      textFormat: Text.PlainText
      text: root.selected ? "\uf111" : "\uf10c"
      color: root.selected ? Color.accent : Util.alpha(root.foreground, 0.5)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 2

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.name
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        Layout.fillWidth: true
        visible: root.sentence !== ""
        textFormat: Text.PlainText
        text: root.sentence
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    RowLayout {
      Layout.alignment: Qt.AlignVCenter
      spacing: Style.space(4)

      Repeater {
        model: root.badges

        Rectangle {
          required property var modelData
          radius: Style.cornerRadius
          color: "transparent"
          border.width: Style.normalBorderWidth
          border.color: modelData === "recipe" ? Color.accent : Util.alpha(root.foreground, 0.4)
          implicitWidth: badgeText.implicitWidth + Style.space(12)
          implicitHeight: badgeText.implicitHeight + Style.space(4)

          Text {
            id: badgeText
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: String(modelData)
            color: modelData === "recipe" ? Color.accent : Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
