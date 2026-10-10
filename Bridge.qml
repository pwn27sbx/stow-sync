import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Hero: the sync bridge. Two node pills joined by a line; the line is accent
// when in sync and urgent when something needs attention. An up chip carries
// the commits to upload, a down chip the commits to fetch, and the "This PC"
// node shows a count badge for local changes. While a request is in flight a
// small dot travels along the line (the only looping animation, and only
// while busy). Under the bridge: one plain sentence from Model.explain.
Item {
  id: root

  property var bridge: ({})
  property string sentence: ""
  property bool busy: false
  property bool motion: true
  property color foreground: Color.foreground

  // Count tween (Model.tweenValue mirrors the tween tested in node).
  property int badgeFrom: 0
  property int badgeTo: 0
  property real badgeT: 1
  readonly property int displayBadge: Model.tweenValue(root.badgeFrom, root.badgeTo, root.badgeT)
  readonly property string badgeText: root.displayBadge > 99 ? "99+" : (root.displayBadge > 0 ? String(root.displayBadge) : "")
  readonly property color lineColor: root.bridge.lineTone === "urgent" ? Color.urgent : Color.accent

  onBridgeChanged: {
    var target = Number(root.bridge && root.bridge.badge) || 0
    if (!root.motion) { root.badgeFrom = target; root.badgeTo = target; root.badgeT = 1; return }
    root.badgeFrom = root.displayBadge
    root.badgeTo = target
    root.badgeT = 0
    badgeTween.restart()
  }

  implicitHeight: column.implicitHeight

  Timer {
    id: badgeTween
    interval: 16
    repeat: true
    onTriggered: {
      root.badgeT += 16 / 180
      if (root.badgeT >= 1) { root.badgeT = 1; badgeTween.stop() }
    }
  }

  Column {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.spacing.lg

    Item {
      id: diagram
      width: parent.width
      height: Style.space(36)

      NodePill {
        id: leftNode
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        label: String(root.bridge.leftLabel || "This PC")
        badgeText: root.badgeText
        tone: root.lineColor
        foreground: root.foreground
      }

      NodePill {
        id: rightNode
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        label: String(root.bridge.rightLabel || "GitHub")
        icon: "\ue725"
        tone: root.lineColor
        foreground: root.foreground
      }

      Item {
        id: lineArea
        anchors.left: leftNode.right
        anchors.right: rightNode.left
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.lg
        anchors.rightMargin: Style.spacing.lg
        height: Style.space(20)

        Rectangle {
          id: line
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width
          height: Style.space(2)
          radius: Style.cornerRadius
          color: root.lineColor
        }

        Row {
          anchors.centerIn: parent
          spacing: Style.spacing.sm

          BorderSurface {
            visible: root.bridge.hasUp === true
            implicitWidth: upLabel.implicitWidth + Style.spacing.lg * 2
            implicitHeight: upLabel.implicitHeight + Style.spacing.xs * 2
            radius: Style.cornerRadius
            color: Util.alpha(Color.background, 0.92)
            borderSpec: Border.flat(root.lineColor, Style.normalBorderWidth)

            Text {
              id: upLabel
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: String(root.bridge.upText || "")
              color: root.lineColor
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }

          BorderSurface {
            visible: root.bridge.hasDown === true
            implicitWidth: downLabel.implicitWidth + Style.spacing.lg * 2
            implicitHeight: downLabel.implicitHeight + Style.spacing.xs * 2
            radius: Style.cornerRadius
            color: Util.alpha(Color.background, 0.92)
            borderSpec: Border.flat(root.lineColor, Style.normalBorderWidth)

            Text {
              id: downLabel
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: String(root.bridge.downText || "")
              color: root.lineColor
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }
        }

        Rectangle {
          id: travelDot
          visible: root.busy && root.motion
          y: (parent.height - height) / 2
          width: Style.space(6)
          height: Style.space(6)
          radius: width / 2
          color: root.lineColor

          SequentialAnimation on x {
            running: root.busy && root.motion
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: Math.max(0, lineArea.width - travelDot.width); duration: 600; easing.type: Easing.InOutSine }
            NumberAnimation { from: Math.max(0, lineArea.width - travelDot.width); to: 0; duration: 600; easing.type: Easing.InOutSine }
          }
        }
      }
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.sentence
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
  }
}
