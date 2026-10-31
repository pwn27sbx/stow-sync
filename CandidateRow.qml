import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One new-config candidate inside the Overview "New config files" and "Hidden"
// groups. The package is chosen in the Adopt confirm card (an editable field
// prefilled with the suggestion), so this row shows the path, what the verdict
// recommends, the backend's reason and the actions the model allows: the
// recommended one is accent-filled, the other stays quiet, a row already
// ignored shows an "Ignored" chip instead of a lone opposite button, and a
// `never` row offers neither.
Item {
  id: root

  property var row: null
  property bool focused: false
  property bool credential: false
  property string packageName: ""
  property color foreground: Color.foreground

  signal hovered()
  signal adoptRequested()
  signal ignoreRequested()

  readonly property var candidate: root.row || ({})
  // The single Adopt/Ignore rule, from the model (README "What a candidate row
  // tells you"): one accent pick at most, or a state chip, or nothing.
  readonly property var actions: Model.candidateRowActions(root.candidate)
  readonly property bool adoptVisible: root.actions.adopt !== "none" && !root.credential
  readonly property bool adoptPrimary: root.actions.adopt === "primary"
  readonly property bool ignoreVisible: root.actions.ignore !== "none"
  readonly property bool ignorePrimary: root.actions.ignore === "primary"
  // Only the accent pick makes the whole row a target; a secondary action is
  // reached through its own button, so a stray row click never adopts a doubt.
  readonly property bool rowActivates: root.adoptPrimary

  implicitHeight: card.implicitHeight

  BorderSurface {
    id: card
    width: parent.width
    implicitHeight: Math.max(Style.spacing.controlHeight, content.implicitHeight + Style.spacing.sm)
    color: root.focused ? Util.alpha(Color.accent, 0.16) : "transparent"
    borderSpec: Border.none()
    radius: Style.cornerRadius

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      enabled: root.rowActivates
      cursorShape: root.rowActivates ? Qt.PointingHandCursor : Qt.ArrowCursor
      onEntered: root.hovered()
      onClicked: root.adoptRequested()
    }

    RowLayout {
      id: content
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.spacing.controlPaddingX
      anchors.rightMargin: Style.spacing.controlPaddingX
      spacing: Style.spacing.sm

      Rectangle {
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredWidth: Style.space(8)
        Layout.preferredHeight: Style.space(8)
        radius: width / 2
        color: root.actions.tone === "never" ? Color.urgent
          : (root.adoptPrimary ? Color.accent : Util.alpha(root.foreground, 0.5))
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(root.candidate.path || "")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideMiddle
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.credential
            ? (String(root.candidate.group || "watched") + "  \u00b7  contains credentials")
            : (String(root.candidate.group || "watched") + "  \u00b7  package: " + root.packageName)
          color: Util.alpha(root.foreground, 0.8)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        // The pick in plain words, above the buttons: "Recommended" when the
        // verdict already decided, "Suggested" when it is the safe pick for a
        // doubt, "Never stow this" when there is nothing to adopt. The reason
        // below stays the why.
        Text {
          Layout.fillWidth: true
          visible: String(root.actions.label || "") !== ""
          textFormat: Text.PlainText
          text: String(root.actions.label || "")
            + (String(root.actions.hint || "") !== "" ? "  \u00b7  " + String(root.actions.hint) : "")
          color: root.actions.tone === "never" ? Color.urgent
            : (root.actions.tone === "recommended" ? Color.accent : Util.alpha(root.foreground, 0.9))
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
          elide: Text.ElideRight
        }

        // The backend's one-line reason: what this file is and why it got its
        // verdict, so the owner never has to ask.
        Text {
          Layout.fillWidth: true
          visible: String(root.candidate.reason || "") !== ""
          textFormat: Text.PlainText
          text: String(root.candidate.reason || "")
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      // The state of a row that is already ignored: the verdict is recomputed
      // each scan, so there is no Ignore action to press, only this.
      Rectangle {
        Layout.alignment: Qt.AlignVCenter
        visible: String(root.actions.chip || "") !== ""
        implicitWidth: chipLabel.implicitWidth + Style.spacing.sm * 2
        implicitHeight: chipLabel.implicitHeight + Style.spacing.xxs * 2
        radius: height / 2
        color: Util.alpha(Color.accent, 0.18)

        Text {
          id: chipLabel
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: "\uf00c  " + String(root.actions.chip || "")
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: root.adoptVisible
        text: root.actions.chip !== "" ? "Adopt anyway" : "Adopt"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        // The recommended button is filled with the accent, the other stays
        // quiet: a border and muted text (README "What a candidate row tells you").
        background: root.adoptPrimary ? Color.accent : "transparent"
        foreground: root.adoptPrimary ? Color.background : Util.alpha(root.foreground, 0.72)
        bordered: !root.adoptPrimary
        onClicked: root.adoptRequested()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: root.ignoreVisible
        text: "Ignore"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        background: root.ignorePrimary ? Color.accent : "transparent"
        foreground: root.ignorePrimary ? Color.background : Util.alpha(root.foreground, 0.72)
        bordered: !root.ignorePrimary
        onClicked: root.ignoreRequested()
      }
    }
  }
}
