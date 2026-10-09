pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Modal overlay host. One instance serves the confirm step for every mutation,
// the commit dialog (with its message field), the diff viewer and the package
// picker. The panel sets `mode` and the matching payload properties; this file
// derives the copy and swaps in the right inline control.
Item {
  id: root

  property bool opened: false
  property string mode: "confirm"
  property string confirmKind: ""
  property var confirmPayload: ({})
  property string confirmError: ""
  property string commitRepo: ""
  property int commitPathCount: 0
  property string commitMessage: ""
  property var commitSecrets: []
  property bool commitAllowSecrets: false
  property string commitError: ""
  property string diffTitle: ""
  property string diffBody: ""
  property bool diffTruncated: false
  property string pickerPath: ""
  property string pickerValue: ""
  property var pickerOptions: []
  property bool busy: false
  property color foreground: Color.foreground

  signal confirmed()
  signal canceled()
  signal commitMessageEdited(string text)
  signal pickerValueEdited(string value)
  signal commitAccepted()

  readonly property var spec: Model.confirmSpec(root.confirmKind, root.confirmPayload)
  readonly property string title: root.mode === "commit" ? ("Commit to " + root.commitRepo)
    : root.mode === "diff" ? root.diffTitle
    : root.mode === "picker" ? "Choose package"
    : root.spec.title
  readonly property string message: root.mode === "commit" ? (root.commitPathCount + " paths selected")
    : root.mode === "picker" ? root.pickerPath
    : root.mode === "diff" ? ""
    : root.spec.message
  readonly property var lines: root.mode === "commit" ? Model.secretLines(root.commitSecrets)
    : (root.mode === "diff" || root.mode === "picker") ? []
    : root.spec.lines
  readonly property string bodyText: root.mode === "diff" ? (root.diffBody !== "" ? root.diffBody : "(no changes)") : ""
  readonly property string confirmText: root.mode === "commit" ? (root.commitAllowSecrets ? "Commit anyway" : "Commit")
    : root.mode === "diff" ? "Close"
    : root.mode === "picker" ? "Use"
    : root.spec.confirmText
  readonly property bool destructive: root.mode === "commit" ? root.commitSecrets.length > 0
    : (root.mode === "confirm" ? root.spec.destructive : false)
  readonly property string errorText: root.mode === "commit" ? root.commitError
    : (root.mode === "confirm" ? root.confirmError : "")
  readonly property bool bodyMode: root.bodyText !== ""

  // Exposed so the panel can suspend its key catcher while an inline editor or
  // the picker popup owns the keyboard.
  readonly property bool contentActiveFocus: contentLoader.item ? contentLoader.item.activeFocus === true : false
  readonly property bool contentPopupOpen: contentLoader.item && contentLoader.item.popupOpen === true ? true : false

  visible: opened

  onCommitMessageChanged: if (contentLoader.item && "text" in contentLoader.item) contentLoader.item.text = root.commitMessage

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
      height: root.bodyMode
        ? Math.min(parent.height - Style.space(16), Style.space(460))
        : Math.min(parent.height - Style.space(16), chrome.implicitHeight + Style.space(28))
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
            width: parent.width
            visible: root.title !== ""
            textFormat: Text.PlainText
            text: root.title
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            wrapMode: Text.WordWrap
          }

          Text {
            width: parent.width
            visible: root.message !== ""
            textFormat: Text.PlainText
            text: root.message
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Repeater {
            model: root.lines

            Text {
              required property string modelData
              width: chrome.width
              textFormat: Text.PlainText
              text: "• " + modelData
              color: root.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }
          }

          Item {
            id: slot
            width: parent.width
            implicitHeight: childrenRect.height

            Loader {
              id: contentLoader
              width: parent.width
              sourceComponent: root.mode === "commit" ? commitComponent
                : (root.mode === "picker" ? pickerComponent : null)
            }
          }

          Text {
            width: parent.width
            visible: root.errorText !== ""
            textFormat: Text.PlainText
            text: root.errorText
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
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
            width: bodyArea.width
            textFormat: Text.PlainText
            text: root.bodyText
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.NoWrap
          }
        }

        Text {
          anchors.left: parent.left
          anchors.bottom: buttonRow.top
          anchors.bottomMargin: Style.spacing.sm
          visible: root.bodyMode && root.diffTruncated
          text: "Diff truncated"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
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
            onClicked: root.confirmed()
          }
        }
      }
    }
  }

  Component {
    id: commitComponent

    TextField {
      placeholderText: "Commit message"
      onTextEdited: root.commitMessageEdited(text)
      Keys.onEscapePressed: root.canceled()
      onAccepted: root.commitAccepted()
    }
  }

  Component {
    id: pickerComponent

    SearchableDropdown {
      width: parent ? parent.width : Style.space(260)
      showLabel: false
      value: root.pickerValue
      options: root.pickerOptions
      onChanged: function(value) { root.pickerValueEdited(value) }
    }
  }
}
