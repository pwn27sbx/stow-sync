pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Body of the setup wizard, one branch per step (Review lives in SetupReview).
// Pure rendering: every value comes from SetupWizard.qml, every interaction
// leaves through a signal.
Column {
  id: root

  property int step: 0
  property var connectRows: []
  property var plan: null
  property bool planLoading: false
  property var stepRows: []
  property var report: null
  property var undoResult: null
  property var postChecked: ({})
  property bool busy: false
  property color foreground: Color.foreground

  signal postToggled(string id, bool value)
  signal undoRequested()

  width: parent ? parent.width : 0
  spacing: Style.spacing.lg

  function toneColor(tone) {
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
    return Util.alpha(root.foreground, 0.72)
  }

  // ---- Step 0: Connect --------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 0
    spacing: Style.spacing.sm

    Text {
      width: parent.width
      visible: root.connectRows.length === 0
      textFormat: Text.PlainText
      text: "Cloning is safe and repeatable. Stow Sync clones the dotfiles repo, reads its recipe and clones every other repo it lists."
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Repeater {
      model: root.connectRows

      RowLayout {
        required property var modelData
        width: parent.width
        spacing: Style.spacing.md

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
          Layout.maximumWidth: Style.space(320)
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: root.toneColor(String(modelData.tone || "muted"))
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignRight
        }
      }
    }
  }

  // ---- Step 1: Review ---------------------------------------------------
  SetupReview {
    width: parent.width
    visible: root.step === 1
    plan: root.plan
    planLoading: root.planLoading
    postChecked: root.postChecked
    foreground: root.foreground
    onPostToggled: function(id, value) { root.postToggled(id, value) }
  }

  // ---- Step 2: Apply ----------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 2
    spacing: Style.spacing.md

    RowLayout {
      width: parent.width
      visible: root.stepRows.length === 0
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: "Setting up this machine\u2026"
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Item {
        Layout.preferredWidth: Style.space(44)
        Layout.preferredHeight: Style.space(10)

        Rectangle {
          width: Style.space(8)
          height: width
          radius: width / 2
          y: (parent.height - height) / 2
          color: Color.accent
          visible: root.busy

          SequentialAnimation on x {
            running: root.busy
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 36; duration: 600; easing.type: Easing.InOutSine }
            NumberAnimation { from: 36; to: 0; duration: 600; easing.type: Easing.InOutSine }
          }
        }
      }
    }

    Repeater {
      model: root.stepRows

      RowLayout {
        required property var modelData
        width: parent.width
        spacing: Style.spacing.md

        Text {
          Layout.alignment: Qt.AlignVCenter
          textFormat: Text.PlainText
          text: modelData.status === "done" ? "\uf00c" : "\uf00d"
          color: modelData.status === "done" ? Color.accent : Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

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
          Layout.maximumWidth: Style.space(200)
          visible: String(modelData.detail || "") !== ""
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: modelData.status === "done" ? Util.alpha(root.foreground, 0.72) : Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignRight
        }
      }
    }
  }

  // ---- Step 3: Report ---------------------------------------------------
  Column {
    width: parent.width
    visible: root.step === 3
    spacing: Style.spacing.md

    Repeater {
      model: root.report ? root.report.lines : []

      RowLayout {
        required property var modelData
        width: parent.width
        spacing: Style.spacing.md

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
          Layout.maximumWidth: Style.space(220)
          visible: String(modelData.detail || "") !== ""
          textFormat: Text.PlainText
          text: String(modelData.detail || "")
          color: root.toneColor(String(modelData.tone || "muted"))
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignRight
        }
      }
    }

    Text {
      width: parent.width
      visible: root.report && root.report.backup !== ""
      textFormat: Text.PlainText
      text: "Backup id " + (root.report ? String(root.report.backup) : "")
      color: Util.alpha(root.foreground, 0.72)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      width: parent.width
      visible: root.undoResult !== null
      textFormat: Text.PlainText
      text: root.undoResult !== null ? "Undo restored " + root.undoResult.restored.length + " file(s)." : ""
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Button {
      visible: root.report !== null && root.undoResult === null
      text: "Undo this setup"
      fontSize: Style.font.caption
      enabled: !root.busy
      onClicked: root.undoRequested()
    }
  }
}
