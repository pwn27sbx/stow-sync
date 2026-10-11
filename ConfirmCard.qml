pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Modal overlay host. One instance serves the confirm step of every mutation
// (confirm), the Publish card (editable message, file list, target, secrets),
// the Adopt card (editable package field with suggestions) and the diff view.
Item {
  id: root

  property bool opened: false
  property string mode: "confirm"
  property string confirmKind: ""
  property var confirmPayload: ({})
  property string confirmError: ""
  property string publishMessage: ""
  property var publishLines: []
  property var publishTargets: []
  property var publishSecrets: []
  property bool publishAllowSecrets: false
  property string publishError: ""
  property string adoptRepo: ""
  property string adoptPath: ""
  property string adoptPackage: ""
  property var adoptSuggestions: []
  property string adoptError: ""
  property string diffTitle: ""
  property string diffBody: ""
  property bool diffTruncated: false
  property bool busy: false
  property color foreground: Color.foreground

  signal confirmed()
  signal canceled()
  signal publishMessageEdited(string text)
  signal publishAccepted()
  signal adoptPackageEdited(string text)
  signal adoptSuggestionClicked(string text)
  signal adoptAccepted()

  readonly property var spec: Model.confirmSpec(root.confirmKind, root.confirmPayload)
  readonly property string title: root.mode === "publish" ? "Publish changes" : root.mode === "adopt" ? ("Adopt into " + root.adoptRepo) : root.mode === "diff" ? root.diffTitle : root.spec.title
  readonly property string message: root.mode === "publish" ? "Commit the selected files, then upload to GitHub." : root.mode === "adopt" ? root.adoptPath : root.mode === "diff" ? "" : root.spec.message
  readonly property var lines: root.mode === "confirm" ? root.spec.lines : []
  readonly property var secretLines: Model.secretLines(root.publishSecrets)
  readonly property string confirmText: root.mode === "publish" ? (root.publishAllowSecrets ? "Publish anyway" : "Publish") : root.mode === "diff" ? "Close" : root.mode === "adopt" ? "Adopt" : root.spec.confirmText
  readonly property bool destructive: root.mode === "publish" ? root.publishSecrets.length > 0 : (root.mode === "confirm" ? root.spec.destructive : false)
  readonly property string errorText: root.mode === "publish" ? root.publishError : root.mode === "adopt" ? root.adoptError : (root.mode === "confirm" ? root.confirmError : "")
  readonly property bool bodyMode: root.mode === "diff"
  readonly property bool contentActiveFocus: contentLoader.item ? contentLoader.item.activeFocus === true : false
  readonly property bool contentPopupOpen: false

  // Publish target lines and secret lines share one Repeater.
  readonly property var extraLines: {
    var out = []
    if (root.mode === "publish") {
      for (var i = 0; i < root.publishTargets.length; i++) out.push({ text: "→ " + root.publishTargets[i], urgent: false })
      for (var j = 0; j < root.secretLines.length; j++) out.push({ text: "⚠ " + root.secretLines[j], urgent: true })
    }
    return out
  }

  visible: opened

  function acceptPrimary() {
    if (root.mode === "publish") root.publishAccepted()
    else if (root.mode === "adopt") root.adoptAccepted()
    else root.confirmed()
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.72)

    MouseArea {
      anchors.fill: parent
      onClicked: if (!root.busy) root.canceled()
    }

    BorderSurface {
      id: card
      width: Math.min(parent.width - Style.space(24), Style.space(460))
      // Reserve room for the button row as well as the text, so a wrapped
      // sentence never runs under the buttons (README 11d.5 / finding 46).
      height: root.bodyMode
        ? Math.min(parent.height - Style.space(16), Style.space(460))
        : Math.min(parent.height - Style.space(16), chrome.implicitHeight + buttonRow.implicitHeight + Style.space(28))
      anchors.centerIn: parent
      color: Color.popups.background
      borderSpec: Border.flat(root.destructive ? Color.urgent : Color.accent, Style.normalBorderWidth)
      padding: Style.space(16)
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: inner
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset

        Column {
          id: chrome
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: Style.spacing.sm

          Text {
            width: parent.width; visible: root.title !== ""; textFormat: Text.PlainText
            text: root.title; color: root.foreground; font.family: Style.font.family
            font.pixelSize: Style.font.title; font.bold: true; wrapMode: Text.WordWrap
          }

          Text {
            width: parent.width; visible: root.message !== ""; textFormat: Text.PlainText
            text: root.message; color: Util.alpha(root.foreground, 0.8); font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
          }

          Repeater {
            model: root.lines
            Text {
              required property string modelData
              width: chrome.width; textFormat: Text.PlainText; text: "• " + modelData
              color: root.foreground; font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
            }
          }

          Repeater {
            model: root.extraLines
            Text {
              required property var modelData
              width: chrome.width; textFormat: Text.PlainText; text: modelData.text
              color: modelData.urgent ? Color.urgent : Util.alpha(root.foreground, 0.8); font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
            }
          }

          Item {
            width: parent.width
            implicitHeight: contentLoader.item ? contentLoader.item.implicitHeight : 0

            Loader {
              id: contentLoader
              width: parent.width
              sourceComponent: root.mode === "publish" ? messageComponent : (root.mode === "adopt" ? packageComponent : null)
            }
          }

          Text {
            width: parent.width; visible: root.errorText !== ""; textFormat: Text.PlainText
            text: root.errorText; color: Color.urgent; font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap
          }
        }

        Flickable {
          id: bodyArea
          visible: root.bodyMode
          anchors.top: chrome.bottom
          anchors.topMargin: Style.spacing.sm
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.bodyMode ? Math.max(Style.space(60), inner.height - chrome.height - buttonRow.height - Style.space(20)) : 0
          clip: true
          contentWidth: width
          contentHeight: bodyText.implicitHeight

          Text {
            id: bodyText
            width: bodyArea.width; textFormat: Text.PlainText
            text: root.diffBody !== "" ? root.diffBody : "(no changes)"
            color: root.foreground; font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall; wrapMode: Text.NoWrap
          }
        }

        Text {
          anchors.left: parent.left; anchors.bottom: buttonRow.top; anchors.bottomMargin: Style.spacing.sm
          visible: root.bodyMode && root.diffTruncated; text: "Diff truncated"
          color: Util.alpha(root.foreground, 0.8); font.family: Style.font.family; font.pixelSize: Style.font.caption
        }

        Row {
          id: buttonRow
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          spacing: Style.spacing.sm

          Button {
            text: root.mode === "diff" ? "Back" : "Cancel"
            enabled: !root.busy
            onClicked: root.canceled()
          }

          Button {
            text: root.busy ? "Working…" : root.confirmText
            foreground: root.destructive ? Color.urgent : Color.foreground
            enabled: !root.busy
            focusable: true
            focus: root.opened
            onClicked: root.acceptPrimary()
          }
        }
      }
    }
  }

  Component {
    id: messageComponent

    TextField {
      text: root.publishMessage
      placeholderText: "Commit message"
      onTextEdited: root.publishMessageEdited(text)
      onAccepted: root.publishAccepted()
    }
  }

  Component {
    id: packageComponent

    Column {
      width: parent ? parent.width : Style.space(260)
      spacing: Style.spacing.xs

      TextField {
        width: parent.width
        text: root.adoptPackage
        placeholderText: "Package name"
        onTextEdited: root.adoptPackageEdited(text)
        onAccepted: root.adoptAccepted()
      }

      Text {
        width: parent.width; visible: root.adoptSuggestions.length > 0; textFormat: Text.PlainText
        text: "Existing packages"; color: Util.alpha(root.foreground, 0.8); font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Flow {
        width: parent.width
        spacing: Style.spacing.xs

        Repeater {
          model: root.adoptSuggestions
          Button {
            required property string modelData
            text: modelData
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(3)
            onClicked: root.adoptSuggestionClicked(modelData)
          }
        }
      }
    }
  }
}
