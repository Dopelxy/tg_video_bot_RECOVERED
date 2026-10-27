import QtQuick
import QtQuick.Layouts

Rectangle {
    id: card
    property string heading
    property string value
    property string detail
    property color indicator: Theme.muted
    implicitHeight: 110; radius: Theme.cardRadius
    color: Theme.card; border.color: Theme.cardBorder
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 7
        RowLayout {
            spacing: 7
            Rectangle { width: 5; height: 5; radius: 3; color: card.indicator }
            Text { text: card.heading; color: Theme.secondary; font.family: Theme.fontFamily; font.pixelSize: 10; font.letterSpacing: 0.7 }
        }
        Text {
            objectName: "stateValue"
            text: card.value; Layout.fillWidth: true
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold
            wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            text: card.detail; Layout.fillWidth: true
            color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 10
            wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; textFormat: Text.PlainText
        }
    }
}
