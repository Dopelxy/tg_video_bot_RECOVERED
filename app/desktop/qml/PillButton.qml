import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool destructive: false
    implicitWidth: 152; implicitHeight: 44
    hoverEnabled: true; focusPolicy: Qt.StrongFocus
    Accessible.name: text
    contentItem: Text {
        text: control.text; textFormat: Text.PlainText
        font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
        color: !control.enabled ? Theme.disabledText : control.primary ? "#102D27"
               : control.destructive ? Theme.error : Theme.text
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    background: Rectangle {
        id: surface
        antialiasing: true
        property color topFill: !control.enabled ? Theme.disabledFill
            : control.primary ? (control.down ? "#59BBA9" : control.hovered ? "#83D7C7" : Theme.success)
            : control.down ? "#34383E" : control.hovered ? "#3A3D44" : "#2B2F37"
        property color bottomFill: !control.enabled ? Theme.disabledFill
            : control.primary ? (control.down ? "#54B19F" : "#60BEAC")
            : control.down ? "#252A31" : control.hovered ? "#30353E" : "#222731"
        radius: height / 2
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accent : !control.enabled ? "#343B46"
                      : control.primary ? "#A1E5D6" : control.hovered ? "#8BC7B38A" : "#48F2F0EB"
        gradient: Gradient {
            GradientStop { position: 0; color: surface.topFill }
            GradientStop { position: 1; color: surface.bottomFill }
        }
        Behavior on topFill { ColorAnimation { duration: Theme.motion } }
        Behavior on bottomFill { ColorAnimation { duration: Theme.motion } }
        Behavior on border.color { ColorAnimation { duration: Theme.motion } }
        Rectangle { anchors.fill: parent; anchors.margins: -4; radius: height / 2; visible: control.activeFocus; color: "transparent"; border.color: Theme.accent; border.width: 1 }
    }
}
