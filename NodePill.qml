import QtQuick
import qs.Commons
import qs.Ui

// One node of the sync bridge: a pill with an optional icon, a label and an
// optional count badge. The badge box is sized from the digit ink and centred
// on the label cap height, so its padding above and below the digit is equal;
// the digit ink is centred in the box. The icon is aligned to the label by
// baseline. All positions come from FontMetrics/TextMetrics, not eyeballing.
Item {
  id: root

  property string label: ""
  property string badgeText: ""
  property string icon: ""
  property color tone: Color.accent
  property color foreground: Color.foreground

  readonly property int badgeGap: Math.round(Style.space(3))
  // Sub-pixel rasterisation compensation (fractional text baseline vs the
  // pixel grid); tuned so the rendered box/digit gaps are equal.
  readonly property real badgeNudge: 1
  readonly property real badgeDigitNudge: 0.5

  FontMetrics { id: labelFm; font: labelText.font }
  FontMetrics { id: iconFm; font: iconText.font }
  FontMetrics { id: digitFm; font: badgeDigit.font }
  TextMetrics { id: labelTm; font: labelText.font; text: labelText.text }
  // Cap-only metrics ("H"): the label ink includes the "h" ascender, but the
  // box must centre on the cap height, which matches the digit height.
  TextMetrics { id: capTm; font: labelText.font; text: "H" }
  TextMetrics { id: digitTm; font: badgeDigit.font; text: root.badgeText }

  // Label baseline and cap box in content coordinates (label.y == 0). The
  // tight bounding rect is baseline-relative (y negative above the baseline).
  readonly property real labelBaseline: labelFm.ascent
  readonly property real labelCapTop: root.labelBaseline + capTm.tightBoundingRect.y
  readonly property real labelCapBottom: root.labelBaseline + capTm.tightBoundingRect.y + capTm.tightBoundingRect.height
  readonly property real labelCapCenter: root.labelCapTop + capTm.tightBoundingRect.height / 2

  // Even height keeps the top and bottom padding equal after pixel rounding
  // (the rendered cap/ink height is even too).
  readonly property real badgeH: 2 * Math.floor((capTm.tightBoundingRect.height + root.badgeGap * 2) / 2)
  readonly property real badgeW: Math.max(Style.space(14), digitTm.tightBoundingRect.width + Style.space(6))
  readonly property real badgeTop: root.labelCapCenter - root.badgeH / 2 + root.badgeNudge
  // Digit baseline aligned with the label baseline; with equal cap heights the
  // digit ink is then centred in the box automatically.
  readonly property real badgeDigitY: root.labelBaseline - digitFm.ascent + root.badgeDigitNudge

  implicitWidth: content.implicitWidth + Style.spacing.lg * 2
  implicitHeight: pill.implicitHeight

  BorderSurface {
    id: pill
    width: parent.width
    implicitHeight: content.implicitHeight + Style.spacing.lg * 2
    radius: Style.cornerRadius
    color: Util.alpha(Color.foreground, 0.06)
    borderSpec: Border.none()

    Item {
      id: content
      anchors.centerIn: parent
      implicitWidth: root.badgeText !== ""
        ? badgeSlot.x + badgeSlot.width
        : labelText.x + labelText.implicitWidth
      implicitHeight: Math.max(labelText.implicitHeight,
        root.badgeText !== "" ? badgeSlot.y + badgeSlot.height : 0,
        root.icon !== "" ? iconText.y + iconText.implicitHeight : 0)

      Text {
        id: iconText
        x: 0
        y: root.labelBaseline - iconFm.ascent
        visible: root.icon !== ""
        textFormat: Text.PlainText
        text: root.icon
        color: root.tone
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Text {
        id: labelText
        x: root.icon !== "" ? iconText.implicitWidth + Style.spacing.sm : 0
        y: 0
        textFormat: Text.PlainText
        text: root.label
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }

      Item {
        id: badgeSlot
        x: labelText.x + labelText.implicitWidth + (root.badgeText !== "" ? Style.space(6) : 0)
        y: root.badgeTop
        width: root.badgeText !== "" ? root.badgeW : 0
        height: root.badgeText !== "" ? root.badgeH : 0
        visible: root.badgeText !== ""

        Rectangle {
          id: badgeBox
          anchors.fill: parent
          radius: Style.cornerRadius
          color: Color.accent
        }

        Text {
          id: badgeDigit
          anchors.horizontalCenter: parent.horizontalCenter
          y: root.badgeDigitY - root.badgeTop
          textFormat: Text.PlainText
          text: root.badgeText
          color: Color.background
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
      }
    }
  }
}
