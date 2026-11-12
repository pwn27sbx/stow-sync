import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One row in the Overview "Needs fixing" group (S2): the package name, its
// state in plain words, the affected paths (first 3, then "+N more") and the
// actions for that one package. No button here is the recommended one — the
// plugin cannot know whether linking a package is right for this machine, so
// every button shares the same quiet outline. A package with links already in
// place gets the per-path skip next to the whole-package skip, because dropping
// the package would drop every link it already has. The panel computes every
// string (Model.packageFix); this component only renders them and reports the
// clicks.
Item {
  id: root

  property var row: null
  property bool busy: false
  property color foreground: Color.foreground

  signal planRequested()
  signal skipPathsRequested()
  signal skipPackageRequested()

  readonly property var fix: root.row || ({})

  implicitHeight: column.implicitHeight

  BorderSurface {
    width: parent.width
    implicitHeight: column.implicitHeight + Style.spacing.sm * 2
    color: "transparent"
    borderSpec: Border.none()
    radius: Style.cornerRadius

    Column {
      id: column
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.spacing.controlPaddingX
      anchors.rightMargin: Style.spacing.controlPaddingX
      spacing: Style.spacing.xxs

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: String(root.fix.title || "")
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: String(root.fix.subtitle || "")
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        visible: String(root.fix.pathsText || "") !== ""
        textFormat: Text.PlainText
        text: String(root.fix.pathsText || "")
        color: Util.alpha(root.foreground, 0.62)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
      }

      // The actions for this package, in one wrapping row. All of them are
      // quiet outlines: none is highlighted, so none reads as a recommendation.
      Flow {
        width: parent.width
        spacing: Style.spacing.sm

        Button {
          visible: String(root.fix.actionText || "") !== ""
          text: String(root.fix.actionText || "")
          bordered: true
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          enabled: !root.busy
          onClicked: root.planRequested()
        }

        Button {
          visible: String(root.fix.skipPathsLabel || "") !== ""
          text: String(root.fix.skipPathsLabel || "")
          bordered: true
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          enabled: !root.busy
          onClicked: root.skipPathsRequested()
        }

        Button {
          text: String(root.fix.skipLabel || "Skip on this machine")
          bordered: true
          fontSize: Style.font.caption
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xxs
          enabled: !root.busy
          onClicked: root.skipPackageRequested()
        }
      }
    }
  }
}
