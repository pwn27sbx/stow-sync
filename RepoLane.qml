pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// A borderless repo lane: a 3 px left state stripe, a collapsed row (name,
// branch chip, short hash, relative time and a compact count) and an expanded
// body of two columns of key:value chips. Remote carries a copy icon button.
// Height animates while expanding/collapsing.
Item {
  id: root

  property var lane: ({})
  property var repo: null
  property string version: ""
  property string now: ""
  property bool expanded: false
  property bool motion: true
  property color foreground: Color.foreground

  signal toggled()
  signal copyRequested(string value)

  readonly property var repoObject: root.repo || ({})
  readonly property var infoRows: Model.repoInfoRows(root.repoObject, root.version, root.now)
  readonly property var leftRows: root.infoRows.slice(0, Math.ceil(root.infoRows.length / 2))
  readonly property var rightRows: root.infoRows.slice(Math.ceil(root.infoRows.length / 2))
  readonly property color stripeColor: root.lane.stripeTone === "urgent"
    ? Color.urgent
    : Util.alpha(Color.accent, root.lane.stripeAlpha === undefined ? 0.5 : root.lane.stripeAlpha)

  function displayValue(row) {
    return String(row.label) === "Remote" ? Model.shortRemote(String(row.value)) : String(row.value)
  }

  implicitHeight: card.implicitHeight

  Component {
    id: chipComponent

    BorderSurface {
      id: chip
      required property var modelData
      Layout.fillWidth: true
      implicitHeight: chipRow.implicitHeight + Style.spacing.sm * 2
      radius: Style.space(6)
      color: Util.alpha(Color.foreground, 0.04)
      borderSpec: Border.none()

      RowLayout {
        id: chipRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.sm
        anchors.rightMargin: Style.spacing.sm
        spacing: Style.spacing.sm

        Text {
          Layout.preferredWidth: Style.space(72)
          textFormat: Text.PlainText
          text: String(modelData.label)
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.displayValue(modelData)
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideMiddle
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          visible: modelData.copy === true
          iconText: "\uf0c5"
          tooltipText: "Copy"
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.xs
          verticalPadding: Style.spacing.xxs
          onClicked: root.copyRequested(String(modelData.value))
        }
      }
    }
  }

  BorderSurface {
    id: card
    width: parent.width
    implicitHeight: inner.implicitHeight + Style.spacing.xxl * 2
    radius: Style.space(10)
    color: Util.alpha(Color.foreground, 0.04)
    borderSpec: Border.none()

    Rectangle {
      id: stripe
      width: Style.space(3)
      height: parent.height
      anchors.left: parent.left
      radius: width / 2
      color: root.stripeColor
    }

    MouseArea {
      x: stripe.width + Style.spacing.xxl
      y: Style.spacing.xxl
      width: Math.max(0, card.width - x - Style.spacing.xxl)
      height: header.implicitHeight
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.toggled()
    }

    Column {
      id: inner
      anchors.left: stripe.right
      anchors.right: parent.right
      anchors.leftMargin: Style.spacing.xxl
      anchors.rightMargin: Style.spacing.xxl
      anchors.top: parent.top
      anchors.topMargin: Style.spacing.xxl
      spacing: Style.spacing.lg

      RowLayout {
        id: header
        width: parent.width
        spacing: Style.spacing.lg

        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: String(root.lane.name || "")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
          elide: Text.ElideRight
        }

        BorderSurface {
          Layout.alignment: Qt.AlignVCenter
          visible: String(root.lane.branchChip || "") !== ""
          implicitWidth: branchText.implicitWidth + Style.spacing.md * 2
          implicitHeight: branchText.implicitHeight + Style.spacing.xxs * 2
          radius: 999
          color: Util.alpha(Color.foreground, 0.06)
          borderSpec: Border.none()

          RowLayout {
            anchors.centerIn: parent
            spacing: Style.spacing.xxs
            Text { textFormat: Text.PlainText; text: "\ue725"; color: Util.alpha(root.foreground, 0.72); font.family: Style.font.family; font.pixelSize: Style.font.caption }
            Text { id: branchText; textFormat: Text.PlainText; text: String(root.lane.branchChip || ""); color: Util.alpha(root.foreground, 0.72); font.family: Style.font.family; font.pixelSize: Style.font.caption }
          }
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          visible: String(root.lane.shortHash || "") !== ""
          textFormat: Text.PlainText
          text: String(root.lane.shortHash || "")
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          visible: String(root.lane.timeText || "") !== ""
          textFormat: Text.PlainText
          text: String(root.lane.timeText || "")
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Item { Layout.fillWidth: true }

        Text {
          Layout.alignment: Qt.AlignVCenter
          Layout.maximumWidth: Style.space(96)
          textFormat: Text.PlainText
          text: String(root.lane.countText || "")
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          horizontalAlignment: Text.AlignRight
        }

        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: root.expanded ? "\u25be" : "\u25b8"
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      Item {
        id: bodyWrap
        width: parent.width
        clip: true
        implicitHeight: root.expanded ? body.implicitHeight : 0

        Behavior on implicitHeight {
          enabled: root.motion
          NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        RowLayout {
          id: body
          width: parent.width
          spacing: Style.spacing.lg

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.sm
            Repeater { model: root.leftRows; delegate: chipComponent }
          }

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.sm
            Repeater { model: root.rightRows; delegate: chipComponent }
          }
        }
      }
    }
  }
}
