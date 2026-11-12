import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One row in the Overview "Needs fixing" group (S2): the package name, its
// state in plain words, the affected paths (first 3, then "+N more") and the
// two per-package choices — the one recommended action and "Skip on this
// machine". The panel computes every string (Model.packageFix); this component
// only renders them and reports the two clicks.
Item {
  id: root

  property var row: null
  property bool busy: false
  property color foreground: Color.foreground

  signal planRequested()
  signal skipRequested()

  readonly property var fix: root.row || ({})

  implicitHeight: column.implicitHeight

  Column {
    id: column
    width: parent.width
    spacing: Style.spacing.xxs

    BorderSurface {
      width: parent.width
      implicitHeight: Math.max(Style.spacing.controlHeight, content.implicitHeight + Style.spacing.sm)
      color: "transparent"
      borderSpec: Border.none()
      radius: Style.cornerRadius

      RowLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.controlPaddingX
        anchors.rightMargin: Style.spacing.controlPaddingX
        spacing: Style.spacing.sm

        ColumnLayout {
          Layout.fillWidth: true
          spacing: 0

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(root.fix.title || "")
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(root.fix.subtitle || "")
            color: Util.alpha(root.foreground, 0.72)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
            visible: String(root.fix.pathsText || "") !== ""
            textFormat: Text.PlainText
            text: String(root.fix.pathsText || "")
            color: Util.alpha(root.foreground, 0.62)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideMiddle
          }
        }

        // The one recommended action, accent-filled (the panel's colour rule).
        Button {
          Layout.alignment: Qt.AlignVCenter
          visible: String(root.fix.actionText || "") !== ""
          text: String(root.fix.actionText || "")
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          enabled: !root.busy
          background: Color.accent
          foreground: Color.background
          onClicked: root.planRequested()
        }

        Button {
          Layout.alignment: Qt.AlignVCenter
          text: "Skip on this machine"
          bordered: true
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          enabled: !root.busy
          onClicked: root.skipRequested()
        }
      }
    }
  }
}
