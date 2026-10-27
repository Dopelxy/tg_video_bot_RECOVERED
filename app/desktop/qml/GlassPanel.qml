import QtQuick
import QtQuick.Effects

Item {
    id: panel
    property Item backdropSource
    property bool effectsEnabled: false
    property real radius: Theme.radius
    property real scrollOffset: 0
    readonly property rect captureRect: {
        const geometry = x + y + width + height + scrollOffset
                         + (backdropSource ? backdropSource.width + backdropSource.height : 0)
        const origin = backdropSource ? mapToItem(backdropSource, 0, 0) : Qt.point(0, 0)
        return Qt.rect(origin.x, origin.y, width, height)
    }
    onCaptureRectChanged: if (blurLoader.item) blurLoader.item.refresh()
    Rectangle {
        x: -4; y: 4; width: panel.width + 8; height: panel.height + 8
        radius: panel.radius + 4; color: "#18000000"
    }
    Loader {
        id: blurLoader
        anchors.fill: parent
        active: panel.effectsEnabled && panel.backdropSource !== null && panel.width > 0 && panel.height > 0
        sourceComponent: Item {
            function refresh() { capture.scheduleUpdate() }
            ShaderEffectSource {
                id: capture
                objectName: "glassBackdropCapture"
                sourceItem: panel.backdropSource
                sourceRect: panel.captureRect
                textureSize: Qt.size(Math.max(1, panel.width / 2), Math.max(1, panel.height / 2))
                live: false; recursive: false; hideSource: false; visible: false
            }
            Rectangle { id: mask; anchors.fill: parent; radius: panel.radius; color: "white"; layer.enabled: true; visible: false }
            MultiEffect {
                anchors.fill: parent; source: capture
                blurEnabled: true; blurMax: 24; blur: 0.65; autoPaddingEnabled: false
                maskEnabled: true; maskSource: mask
            }
            Component.onCompleted: capture.scheduleUpdate()
            Connections {
                target: panel.backdropSource
                ignoreUnknownSignals: true
                function onPainted() { capture.scheduleUpdate() }
            }
        }
    }
    Rectangle {
        anchors.fill: parent; radius: panel.radius
        border.width: 1; border.color: Theme.edge
        gradient: Gradient {
            GradientStop { position: 0; color: Theme.glassTop }
            GradientStop { position: 1; color: Theme.glassBottom }
        }
    }
    Rectangle {
        x: panel.radius; y: 1
        width: Math.max(0, panel.width - panel.radius * 2); height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 0.35; color: "#63F2F0EB" }
            GradientStop { position: 0.75; color: "#38C7B38A" }
            GradientStop { position: 1; color: "transparent" }
        }
    }
}
