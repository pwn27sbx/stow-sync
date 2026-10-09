pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One package card on the Packages tab: chevron, package icon, title, muted
// target/state description and a file count. Expanded it lists each changed
// file with its status chip and offers Restow for that package.
GroupCard {
  id: root

  property var card: null
  property string now: ""

  signal restowRequested()

  readonly property var cardObject: root.card || ({})

  icon: String(root.cardObject.icon || "")
  title: String(root.cardObject.title || "")
  subtitle: String(root.cardObject.description || "")
  count: String(Model.num(root.cardObject.count, 0))
  unit: String(root.cardObject.unit || "files")

  function chipFor(state) {
    var s = String(state || "")
    if (s === "added") return "A"
    if (s === "deleted") return "D"
    if (s === "untracked") return "?"
    return "M"
  }

  Repeater {
    model: root.cardObject.files || []

    RowLayout {
      required property var modelData
      width: parent ? parent.width : 0
      spacing: Style.spacing.sm

      BorderSurface {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(16)
        Layout.preferredHeight: Style.space(16)
        radius: Style.cornerRadius
        color: Util.alpha(Color.accent, 0.16)
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.chipFor(modelData.state)
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      Text {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: String(modelData.path)
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideMiddle
      }
    }
  }

  Button {
    text: "Restow"
    iconText: "\uf021"
    fontSize: Style.font.caption
    horizontalPadding: Style.spacing.sm
    verticalPadding: Style.spacing.xxs
    onClicked: root.restowRequested()
  }
}
