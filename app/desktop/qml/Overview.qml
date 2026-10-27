import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    objectName: "overviewWindow"
    width: 1220; height: 760
    minimumWidth: 840; minimumHeight: 460
    visible: true
    title: "Telegram Media Bot — Обзор"
    color: Theme.background
    font.family: Theme.fontFamily
    palette.text: Theme.text; palette.windowText: Theme.text; palette.highlight: Theme.accent
    property bool liteEffects: false
    readonly property int rendererApi: ambient.GraphicsInfo.api
    readonly property bool blurEnabled: !liteEffects && rendererApi !== GraphicsInfo.Software
                                       && rendererApi !== GraphicsInfo.Unknown && rendererApi !== GraphicsInfo.Null
    readonly property bool compact: width < 1100
    readonly property bool shortViewport: height < 660
    readonly property int margin: compact ? 16 : 22
    property bool journalExpanded: false
    onClosing: function(event) { event.accepted = overview.requestClose() }
    Connections { target: overview; function onReadyToClose() { window.close() } }
    AmbientBackground { id: ambient; anchors.fill: parent }

    Item {
        id: navigation
        objectName: "floatingNavigation"
        x: window.margin; y: window.margin
        width: window.compact ? 82 : 200
        height: window.height - window.margin * 2
        GlassPanel { objectName: "navigationGlass"; anchors.fill: parent; backdropSource: ambient; effectsEnabled: window.blurEnabled }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: window.compact ? 10 : 18; spacing: 14
            RowLayout {
                Layout.topMargin: 6; Layout.bottomMargin: 22
                Layout.alignment: window.compact ? Qt.AlignHCenter : Qt.AlignLeft; spacing: 10
                Rectangle {
                    width: 34; height: 34; radius: 12; color: Theme.accent
                    Text { anchors.centerIn: parent; text: "M"; color: "#23211C"; font.family: Theme.fontFamily; font.pixelSize: 21; font.bold: true }
                }
                Column {
                    visible: !window.compact; spacing: 3
                    Text { text: "MEDIA BOT"; font.family: Theme.fontFamily; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold; font.letterSpacing: 0.7 }
                    Text { text: "Центр управления"; font.family: Theme.fontFamily; color: Theme.muted; font.pixelSize: 10 }
                }
            }
            Button {
                id: overviewTab
                objectName: "overviewTab"
                Layout.fillWidth: true; implicitHeight: window.compact ? 64 : 46
                text: "Обзор"; hoverEnabled: true; focusPolicy: Qt.StrongFocus; Accessible.name: text
                contentItem: Text { text: "Обзор"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: window.compact ? 11 : 13; font.weight: Font.DemiBold; verticalAlignment: Text.AlignVCenter; horizontalAlignment: window.compact ? Text.AlignHCenter : Text.AlignLeft; leftPadding: window.compact ? 0 : 16 }
                background: Rectangle { radius: 16; color: overviewTab.hovered ? "#36C7B38A" : "#20C7B38A"; border.color: overviewTab.activeFocus ? Theme.accent : "#49C7B38A"; border.width: overviewTab.activeFocus ? 2 : 1; Behavior on color { ColorAnimation { duration: Theme.motion } } }
            }
            Button {
                objectName: "futureBotsTab"
                Layout.fillWidth: true; implicitHeight: window.compact ? 66 : 46
                enabled: false; text: "Выбор бота · скоро"; Accessible.name: text
                contentItem: Text { text: window.compact ? "Выбор бота\n· скоро" : "Выбор бота · скоро"; color: Theme.disabledText; font.family: Theme.fontFamily; font.pixelSize: window.compact ? 10 : 11; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter; horizontalAlignment: window.compact ? Text.AlignHCenter : Text.AlignLeft; leftPadding: window.compact ? 0 : 12 }
                background: Rectangle { color: "transparent" }
            }
            Item { Layout.fillHeight: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#24F2F0EB" }
            Text { Layout.fillWidth: true; text: window.compact ? "На ПК" : "ЛОКАЛЬНОЕ УПРАВЛЕНИЕ"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: window.compact ? 10 : 9; horizontalAlignment: window.compact ? Text.AlignHCenter : Text.AlignLeft }
            Text { visible: !window.compact; Layout.fillWidth: true; text: "Закройте окно —\nбот продолжит работу."; color: Theme.secondary; font.family: Theme.fontFamily; font.pixelSize: 11; lineHeight: 1.4 }
            Item { height: 6 }
        }
    }
    ScrollView {
        id: mainScroll
        objectName: "mainScroll"
        x: navigation.x + navigation.width + (window.compact ? 18 : 26)
        y: window.margin; width: window.width - x - window.margin
        height: window.height - window.margin * 2
        clip: true; contentWidth: availableWidth; rightPadding: 12
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: ScrollBar {
            objectName: "mainVerticalScrollBar"
            parent: mainScroll
            anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
            policy: ScrollBar.AsNeeded; active: true
            contentItem: Rectangle { implicitWidth: 4; implicitHeight: 28; radius: 2; color: "#91C7B38A" }
            background: Rectangle { implicitWidth: 8; color: "transparent" }
        }
        ColumnLayout {
            id: content
            width: mainScroll.availableWidth; spacing: window.shortViewport ? Theme.compactGap : Theme.gap
            RowLayout {
                Layout.fillWidth: true; Layout.preferredHeight: window.shortViewport ? 42 : 46
                ColumnLayout {
                    spacing: 4
                    Text { text: "Обзор"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 25; font.weight: Font.DemiBold }
                    Text { text: "Локальное управление Telegram-ботом"; color: Theme.secondary; font.family: Theme.fontFamily; font.pixelSize: 11 }
                }
                Item { Layout.fillWidth: true }
                PillButton { objectName: "exitButton"; text: "Выход"; implicitWidth: 84; implicitHeight: 34; enabled: overview.canRefresh; onClicked: overview.shutdown() }
            }
            Rectangle {
                visible: overview.demoMode; Layout.fillWidth: true; implicitHeight: window.shortViewport ? 22 : 24
                color: "#25372F"; radius: 8; border.color: "#3765CBB8"
                Text { anchors.fill: parent; anchors.margins: 4; text: "ДЕМО · подменённый Agent · рабочие службы не используются"; color: "#A1D9C9"; font.family: Theme.fontFamily; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
            }
            Rectangle {
                objectName: "identityPanel"
                Layout.fillWidth: true; implicitHeight: window.shortViewport ? 76 : window.compact ? 88 : 94
                radius: Theme.radius; color: "#171C24"; border.color: Theme.cardBorder
                RowLayout {
                    anchors.fill: parent; anchors.margins: window.shortViewport ? 14 : 18; spacing: 14
                    Rectangle {
                        width: 48; height: 48; radius: 16; color: "#29362F"; border.color: "#3865CBB8"
                        Text { anchors.centerIn: parent; text: "TG"; color: Theme.success; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                        Text {
                            id: botTitle
                            objectName: "botTitle"
                            text: overview.botDisplayName
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: window.compact ? 19 : 23; font.weight: Font.DemiBold
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            textFormat: Text.PlainText; elide: Text.ElideMiddle; maximumLineCount: 1
                            HoverHandler { id: titleHover }
                            ToolTip.visible: titleHover.hovered && botTitle.truncated
                            ToolTip.text: overview.botDisplayName
                        }
                        Text { text: overview.botDisplayName === overview.botUsername ? "Telegram-бот · локальный Agent" : overview.botUsername; color: Theme.secondary; font.family: Theme.fontFamily; font.pixelSize: 11; textFormat: Text.PlainText; Layout.fillWidth: true; elide: Text.ElideRight }
                    }
                    Text { visible: !window.compact; text: "НА ЭТОМ ПК"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: 9; font.letterSpacing: 1 }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                StateCard { objectName: "agentCard"; Layout.fillWidth: true; heading: "AGENT"; value: overview.agentText; detail: "Локальная служба"; indicator: overview.agentState === "connected" ? Theme.success : overview.agentState === "disconnected" ? Theme.error : Theme.accent }
                StateCard { objectName: "processCard"; Layout.fillWidth: true; heading: "ПРОЦЕСС БОТА"; value: overview.processText; detail: overview.processDetail; indicator: overview.stale ? Theme.accent : overview.processRunning ? Theme.success : Theme.muted }
                StateCard { objectName: "telegramCard"; Layout.fillWidth: true; heading: "TELEGRAM API"; value: overview.telegramText; detail: "Последняя проверка Agent"; indicator: overview.stale ? Theme.accent : overview.telegramState === "reachable" ? Theme.success : Theme.muted }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: overview.lastUpdateText; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 10 }
                Text { visible: overview.stale; text: overview.hasSnapshot ? "· данные устарели" : "· нет свежих данных"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: 10 }
                Item { Layout.fillWidth: true }
            }
            Item {
                id: controlPanel
                objectName: "controlPanel"
                Layout.fillWidth: true; implicitHeight: window.shortViewport ? 100 : 112
                GlassPanel { objectName: "controlsGlass"; anchors.fill: parent; backdropSource: ambient; effectsEnabled: window.blurEnabled; scrollOffset: mainScroll.contentItem ? mainScroll.contentItem.contentY : 0 }
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: window.shortViewport ? 14 : 17; spacing: window.shortViewport ? 10 : 12
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Text { text: "УПРАВЛЕНИЕ"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: 10; font.letterSpacing: 0.9 }
                        Item { Layout.fillWidth: true }
                        BusyIndicator { objectName: "commandSpinner"; running: overview.busy; visible: overview.busy; implicitWidth: 18; implicitHeight: 18; palette.dark: Theme.accent }
                        Text { objectName: "commandLabel"; text: overview.commandLabel; color: Theme.secondary; font.family: Theme.fontFamily; font.pixelSize: 11; textFormat: Text.PlainText; Layout.maximumWidth: controlPanel.width * 0.68; maximumLineCount: 2; wrapMode: Text.WordWrap; elide: Text.ElideRight }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        PillButton { objectName: "startButton"; text: "Запустить"; primary: true; enabled: overview.canStart; onClicked: overview.startBot() }
                        PillButton { objectName: "stopButton"; text: "Остановить"; destructive: true; enabled: overview.canStop; onClicked: overview.stopBot() }
                        PillButton { objectName: "refreshButton"; text: "Обновить"; enabled: overview.canRefresh; onClicked: overview.refresh() }
                        Item { Layout.fillWidth: true }
                    }
                }
            }
            Rectangle {
                visible: overview.errorText.length > 0; Layout.fillWidth: true; implicitHeight: errorLabel.implicitHeight + 28
                color: "#302329"; radius: 16; border.color: "#715055"
                Text { id: errorLabel; anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 14; anchors.verticalCenter: parent.verticalCenter; text: overview.errorText; textFormat: Text.PlainText; color: Theme.error; font.family: Theme.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap }
            }
            Rectangle {
                id: journalPanel
                objectName: "journalPanel"
                Layout.fillWidth: true; implicitHeight: window.journalExpanded ? 300 : 130
                color: "#151A22"; radius: Theme.cardRadius; border.color: Theme.cardBorder
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 16; spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Журнал"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Text { text: overview.logCount + " / 200"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 10 }
                        Item { Layout.fillWidth: true }
                        Button {
                            id: expandButton
                            objectName: "expandJournalButton"
                            text: window.journalExpanded ? "Свернуть" : "Развернуть"
                            implicitWidth: 94; implicitHeight: 28; hoverEnabled: true; focusPolicy: Qt.StrongFocus
                            Accessible.name: text + " журнал"
                            contentItem: Text { text: expandButton.text; color: expandButton.enabled ? Theme.accent : Theme.disabledText; font.family: Theme.fontFamily; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
                            background: Rectangle { radius: 14; color: expandButton.hovered ? "#26C7B38A" : "transparent"; border.color: expandButton.activeFocus ? Theme.accent : "transparent"; border.width: 1; Behavior on color { ColorAnimation { duration: Theme.motion } } }
                            onClicked: window.journalExpanded = !window.journalExpanded
                        }
                    }
                    ListView {
                        id: logView
                        objectName: "logView"
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                        model: window.journalExpanded ? overview.logLines : overview.logLines.slice(-3)
                        onCountChanged: positionViewAtEnd()
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Text { required property string modelData; width: logView.width - 12; text: modelData; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; font.family: Theme.monoFamily; font.pixelSize: 11; color: Theme.secondary }
                        Text { visible: logView.count === 0; text: "События появятся после ответа Agent"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 11 }
                    }
                }
            }
            Item { height: 6 }
        }
    }
}
