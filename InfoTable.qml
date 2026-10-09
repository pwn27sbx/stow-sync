pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One collapsible info-table card per repo (config-sync's info table). The
// header is the repo name and its state; the body is the label/value table
// from Model.repoInfoRows, with an inline Copy on the Remote row.
GroupCard {
  id: root

  property var repo: null
  property string version: ""
  property string now: ""

  signal copyRequested(string value)

  readonly property var infoRows: Model.repoInfoRows(root.repo, root.version, root.now)
  readonly property var repoObject: root.repo || ({})

  title: Model.repoDisplayName(root.repoObject.path)
  subtitle: Model.stateTitle(root.repoObject.state) + "  \u00b7  " + Model.repoSubtitle(root.repoObject)
  count: String(Model.num(root.repoObject.stowed_packages, 0))
  unit: "packages"
  icon: ""

  Repeater {
    model: root.infoRows

    RowLayout {
      required property var modelData
      width: parent ? parent.width : 0
      spacing: Style.spacing.sm

      Text {
        Layout.preferredWidth: Style.space(96)
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: modelData.label
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: modelData.value
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideMiddle
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: modelData.copy === true
        text: "Copy"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        onClicked: root.copyRequested(String(modelData.value))
      }
    }
  }
}
