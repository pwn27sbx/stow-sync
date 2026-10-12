pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// "Setup backups" view (README 10b.7/finding 27): every backup from
// setup-backups with its date and counts, plus Undo (a confirm card) or an
// "undone" marker. Reachable any time from the header while the wizard is off.
Column {
  id: root

  property var rows: []
  property var undoResult: null
  property string undoError: ""
  property bool busy: false
  property color foreground: Color.foreground

  signal undoRequested(string id)
  signal doneRequested()

  readonly property string undoSummary: Model.setupUndoSummary(root.undoResult)

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: root.rows.length > 0 ? "Every setup you ran on this machine. Undo puts the original files back."
                                 : "No setup backups yet."
    color: Util.alpha(root.foreground, 0.72)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  // Undo result / error (finding 80): the result card stays while the list is
  // open, so Undo never looks like it did nothing.
  Text {
    width: parent.width
    visible: root.undoSummary !== ""
    textFormat: Text.PlainText
    text: root.undoSummary
    color: Color.accent
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    font.bold: true
    wrapMode: Text.WordWrap
  }

  Text {
    width: parent.width
    visible: root.undoError !== ""
    textFormat: Text.PlainText
    text: root.undoError
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Repeater {
    model: root.rows

    RowLayout {
      required property var modelData
      width: parent.width
      spacing: Style.spacing.md

      ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(modelData.label || "")
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: Util.alpha(root.foreground, 0.72)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Text {
        Layout.alignment: Qt.AlignVCenter
        visible: modelData.undone === true
        textFormat: Text.PlainText
        text: "undone"
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      // An empty backup did nothing, so it has nothing to undo (finding 91).
      Text {
        Layout.alignment: Qt.AlignVCenter
        visible: modelData.undone !== true && modelData.empty === true
        textFormat: Text.PlainText
        text: "nothing to undo"
        color: Util.alpha(root.foreground, 0.72)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        Layout.alignment: Qt.AlignVCenter
        visible: modelData.undone !== true && modelData.empty !== true
        text: "Undo"
        foreground: Color.urgent
        bordered: true
        fontSize: Style.font.caption
        enabled: !root.busy
        onClicked: root.undoRequested(String(modelData.id || ""))
      }
    }
  }
}
