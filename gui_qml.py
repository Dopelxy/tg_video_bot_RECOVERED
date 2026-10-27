"""Qt Quick shell. --demo never constructs the real transport or reads keys."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Use temporary data and a fake Agent")
    parser.add_argument("--demo-state", choices=("running", "stopped", "disconnected", "busy", "error"), default="running")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--quit-after", type=int)
    parser.add_argument("--lite", action="store_true", help="Use glass tints without shader effects")
    parser.add_argument("--preview-size", help="Demo client viewport in physical pixels, e.g. 1366x768")
    parser.add_argument("--preview-scale", type=float, choices=(1.0, 1.25, 1.5))
    parser.add_argument("--long-username", action="store_true", help="Demo layout stress fixture")
    parser.add_argument("--preview-report", type=Path, help="Demo layout/renderer JSON")
    args = parser.parse_args()
    if not args.demo and (args.offscreen or args.screenshot or args.quit_after or args.demo_state != "running"
                         or args.preview_size or args.preview_scale or args.long_username or args.preview_report):
        parser.error("Preview options require --demo")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if args.preview_scale:
        # Override this preview process only, instead of multiplying the host's
        # native DPI (which may already be 125% or 150%).
        native_scale = 1.0
        if sys.platform == "win32" and not args.offscreen:
            import ctypes
            api = ctypes.WinDLL("shcore")
            api.GetScaleFactorForDevice.argtypes = [ctypes.c_int]
            api.GetScaleFactorForDevice.restype = ctypes.c_int
            factor = api.GetScaleFactorForDevice(0)
            if 50 <= factor <= 500:
                native_scale = factor / 100
        os.environ["QT_SCALE_FACTOR"] = str(args.preview_scale / native_scale)
        os.environ["QT_SCREEN_SCALE_FACTORS"] = ""
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    from PySide6.QtCore import QTimer, QUrl, QCoreApplication, QEvent
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtQuickControls2 import QQuickStyle
    from app.desktop.model import OverviewModel
    from app.desktop.transport import AgentTransport, DemoTransport
    from app.desktop.fonts import load_system_fonts
    from app.paths import PROJECT_DIR

    QQuickStyle.setStyle("Basic")
    if args.offscreen:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.Software)
    app = QGuiApplication([sys.argv[0]])
    load_system_fonts()
    app.setApplicationName("Telegram Media Bot")
    transport = DemoTransport(args.demo_state) if args.demo else AgentTransport()
    if args.demo and args.long_username:
        original_request = transport.request
        def with_long_username(command):
            response = original_request(command)
            if response.get("ok") and command in {"status", "probe"}:
                response["bot_username"] = "demo_bot_with_long_username_12345"
            return response
        transport.request = with_long_username
    model = OverviewModel(transport, allow_autostart=not args.demo)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("overview", model)
    engine.load(QUrl.fromLocalFile(str(PROJECT_DIR / "app" / "desktop" / "qml" / "Overview.qml")))
    if not engine.rootObjects():
        if args.demo:
            transport.close()
        return 1
    window = engine.rootObjects()[0]
    window.setProperty("liteEffects", args.lite)
    if args.preview_size:
        try:
            physical_width, physical_height = (int(value) for value in args.preview_size.lower().split("x"))
            if not (840 <= physical_width <= 3840 and 460 <= physical_height <= 2160):
                raise ValueError()
        except ValueError:
            parser.error("--preview-size must be a viewport between 840x460 and 3840x2160")
        ratio = window.devicePixelRatio()
        window.setWidth(round(physical_width / ratio))
        window.setHeight(round(physical_height / ratio))
    else:
        available = window.screen().availableGeometry()
        window.setWidth(min(window.width(), available.width() - 32))
        window.setHeight(min(window.height(), available.height() - 48))
    model.begin()
    if args.demo and args.demo_state in {"disconnected", "busy", "error"}:
        QTimer.singleShot(350, model.refresh)
    screenshot_ok = [True]
    if args.preview_report:
        def report():
            import json
            from PySide6.QtCore import QObject, QPointF
            names = ("floatingNavigation", "controlPanel", "journalPanel", "botTitle", "startButton",
                     "stopButton", "refreshButton", "exitButton", "futureBotsTab", "commandSpinner", "mainScroll")
            data = {"width": window.width(), "height": window.height(), "dpr": window.devicePixelRatio(),
                    "blur": window.property("blurEnabled"), "scale": args.preview_scale or 1,
                    "scenario": args.demo_state,
                    "renderer": str(QSGRendererInterface.GraphicsApi(window.property("rendererApi"))),
                    "manual_busy": model.busy, "command_label": model.commandLabel, "items": {}}
            for name in names:
                item = window.findChild(QObject, name)
                if item:
                    data["items"][name] = {key: item.property(key) for key in ("x", "y", "width", "height", "visible", "enabled")}
                    point = item.mapToItem(window.contentItem(), QPointF(0, 0))
                    data["items"][name].update(scene_x=point.x(), scene_y=point.y())
            data["glass_sources"] = [{"source": capture.property("sourceItem").objectName(),
                                       "recursive": capture.property("recursive"), "live": capture.property("live")}
                                      for capture in window.findChildren(QObject, "glassBackdropCapture")]
            args.preview_report.parent.mkdir(parents=True, exist_ok=True)
            args.preview_report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(900, report)
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            screenshot_ok[0] = window.grabWindow().save(str(args.screenshot))
        QTimer.singleShot(900, capture)
    if args.quit_after:
        QTimer.singleShot(max(1100, args.quit_after), window.close)
    result = app.exec()
    # All closing routes go through requestClose; the worker has finished here.
    engine.deleteLater()
    model.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if args.demo:
        transport.close()
    return result if screenshot_ok[0] else 2


if __name__ == "__main__":
    raise SystemExit(main())
