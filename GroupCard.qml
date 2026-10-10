import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Collapsible group/category card: chevron, optional icon, bold title, muted
// subtitle, count on the right and an optional action button. The default
// property is the expanded body, so callers drop a Repeater of rows inside.
Item {
  id: root

  property string title: ""
  property string subtitle: ""
  property string icon: ""
  property string count: ""
  property string unit: ""
  property bool expanded: false
  property int bodyPadding: 0
  property bool hasAction: false
  property string actionText: "Fix"
  property bool focused: false
  property bool motion: true
  property color foreground: Color.foreground

  signal toggled()
  signal actionClicked()

  default property alias content: body.data

  implicitHeight: card.implicitHeight

  BorderSurface {
    id: card
    width: parent.width
    implicitHeight: inner.implicitHeight + Style.spacing.sm * 2
    color: Util.alpha(Color.foreground, 0.04)
    borderSpec: Border.none()
    radius: Style.space(10)
    padding: Style.spacing.sm

    Rectangle {
      id: stripe
      width: Style.space(3)
      height: parent.height
      anchors.left: parent.left
      radius: width / 2
      color: Color.accent
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.toggled()
    }

    Column {
      id: inner
      x: Style.space(3)
      width: parent.width - Style.space(3)
      spacing: Style.spacing.sm

      RowLayout {
        width: parent.width
        spacing: Style.spacing.sm

        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: root.expanded ? "\u25be" : "\u25b8"
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          visible: root.icon !== ""
          textFormat: Text.PlainText
          text: root.icon
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: 0

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.title
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
            visible: root.subtitle !== ""
            textFormat: Text.PlainText
            text: root.subtitle
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          Layout.maximumWidth: Style.space(140)
          Layout.rightMargin: Style.space(8)
          textFormat: Text.PlainText
          text: root.count !== "" ? (root.count + (root.unit !== "" ? " " + root.unit : "")) : ""
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          horizontalAlignment: Text.AlignRight
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          Layout.rightMargin: Style.space(8)
          visible: root.hasAction
          text: root.actionText
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          onClicked: root.actionClicked()
        }
      }

      Item {
        id: bodyWrap
        width: parent.width
        clip: true
        implicitHeight: root.expanded ? body.implicitHeight + root.bodyPadding * 2 : 0

        Behavior on implicitHeight {
          enabled: root.motion
          NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        Column {
          id: body
          x: root.bodyPadding
          y: root.bodyPadding
          width: parent.width - root.bodyPadding * 2
          spacing: Style.spacing.xs
        }
      }
    }
  }
}
