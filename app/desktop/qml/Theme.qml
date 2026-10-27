pragma Singleton
import QtQuick

QtObject {
    readonly property color background: "#0D1015"
    readonly property color text: "#F2F0EB"
    readonly property color secondary: "#B6BAC4"
    readonly property color muted: "#979FAB"
    readonly property color accent: "#C7B38A"
    readonly property color success: "#65CBB8"
    readonly property color error: "#EF8F8F"
    readonly property color card: "#191E27"
    readonly property color cardBorder: "#303641"
    readonly property color glassTop: "#CF242831"
    readonly property color glassBottom: "#D9181D25"
    readonly property color edge: "#36F2F0EB"
    readonly property color disabledText: "#89929F"
    readonly property color disabledFill: "#1C222C"
    readonly property string fontFamily: Qt.platform.os === "windows" ? "Segoe UI" : "sans-serif"
    readonly property string monoFamily: Qt.platform.os === "windows" ? "Consolas" : "monospace"
    readonly property int radius: 24
    readonly property int cardRadius: 20
    readonly property int motion: 180
    readonly property int gap: 14
    readonly property int compactGap: 10
}
