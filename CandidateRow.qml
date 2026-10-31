import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One new-config candidate inside the Overview "New config files" and "Hidden"
// groups. The package is chosen in the Adopt confirm card (an editable field
// prefilled with the suggestion), so this row shows the path, what the verdict
// recommends, the backend's reason and the Adopt / Ignore actions.
Item {
  id: root

  property var row: null
  property bool focused: false
  property bool credential: false
  // A hidden row (`never`/`ignore`) offers no Ignore button: the verdict is
  // computed each scan, not written to the config's ignore list.
  property bool showIgnore: true
  property bool showAdopt: true
  property string packageName: ""
  property color foreground: Color.foreground

  signal hovered()
  signal adoptRequested()
  signal ignoreRequested()

  readonly property var candidate: root.row || ({})
  readonly property bool adoptable: root.showAdopt && !root.credential
  // What this row recommends, in words, and which button that is (README
  // "New config candidates"): a firm verdict is "Recommended", a review is a
  // "Suggested" safe pick, and a secret offers nothing to press.
  readonly property var recommendation: Model.candidateRecommendation(root.candidate)
  readonly property bool adoptEmphasis: root.recommendation.action === "adopt"
  readonly property bool ignoreEmphasis: root.recommendation.action === "ignore"
  // Only a firm upload makes the whole row an Adopt target. A review row asks
  // for a button press, so a stray click on the row must not adopt it.
  readonly property bool rowActivates: root.adoptable && root.adoptEmphasis

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
        color: root.recommendation.tone === "never" ? Color.urgent
          : (root.adoptEmphasis ? Color.accent : Util.alpha(root.foreground, 0.5))
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
          visible: String(root.recommendation.label || "") !== ""
          textFormat: Text.PlainText
          text: String(root.recommendation.label || "")
            + (String(root.recommendation.hint || "") !== "" ? "  \u00b7  " + String(root.recommendation.hint) : "")
          color: root.recommendation.tone === "never" ? Color.urgent
            : (root.recommendation.tone === "recommended" ? Color.accent : Util.alpha(root.foreground, 0.9))
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

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: !root.credential && root.showAdopt
        text: "Adopt"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        // The recommended button is filled with the accent, the other stays
        // neutral (the plugin's primary-action style, as on "Publish selected").
        background: root.adoptEmphasis ? Color.accent : Style.normalFillFor(root.foreground, Color.accent)
        foreground: root.adoptEmphasis ? Color.background : root.foreground
        onClicked: root.adoptRequested()
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: root.showIgnore
        text: "Ignore"
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xxs
        background: root.ignoreEmphasis ? Color.accent : Style.normalFillFor(root.foreground, Color.accent)
        foreground: root.ignoreEmphasis ? Color.background : root.foreground
        onClicked: root.ignoreRequested()
      }
    }
  }
}
