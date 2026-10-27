import offline_support
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QML_DISABLE_DISK_CACHE"] = "1"

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import gc
import threading
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer, QUrl, QObject, QEvent, QCoreApplication, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest, QSignalSpy

from app.desktop.agent_call import perform
from app.desktop.model import OverviewModel
from app.desktop.state import OverviewState
from app.desktop.transport import AgentTransport, DemoTransport, TransportFault
from app.paths import PROJECT_DIR
from app.desktop.fonts import load_system_fonts

_app = None


def app():
    global _app
    if _app is None:
        QQuickStyle.setStyle("Basic")
        QQuickWindow.setGraphicsApi(QSGRendererInterface.Software)
        _app = QGuiApplication.instance() or QGuiApplication([])
        load_system_fonts()
        _app.setQuitOnLastWindowClosed(False)
    return _app


def wait_for(predicate, timeout=4000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        app().processEvents()
        QTest.qWait(10)
    if not predicate():
        raise AssertionError("Qt condition timed out")
    app().processEvents()


def tearDownModule():
    global _app
    if _app is not None:
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        _app.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        _app = None
    gc.collect()


class StateTests(unittest.TestCase):
    def test_contract_fallback_and_authoritative_stopped_state(self):
        state = OverviewState()
        self.assertEqual(state.display_name, "Telegram-бот")
        self.assertEqual(state.process_text, "Нет данных")
        state.accept({"ok": True, "launcher_pid": None}, "status")
        self.assertEqual(state.process_text, "Остановлен")
        state.accept({"ok": True, "launcher_pid": 42, "bot_username": "real_name",
                      "telegram_api": "reachable"}, "status")
        self.assertEqual(state.display_name, "@real_name")
        self.assertEqual(state.process_text, "Launcher запущен")
        self.assertEqual(state.telegram_text, "Доступен")

    def test_connection_loss_keeps_last_pid_identity_and_timestamp(self):
        state = OverviewState()
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        state.accept({"ok": True, "launcher_pid": 42, "bot_username": "known_bot",
                      "telegram_api": "reachable"}, "status", now)
        state.disconnect("Нет связи")
        self.assertEqual((state.launcher_pid, state.username, state.received_at), (42, "known_bot", now))
        self.assertTrue(state.stale)
        self.assertTrue(state.process_text.startswith("Последнее:"))

    def test_failed_and_malformed_response_never_claim_stopped(self):
        state = OverviewState()
        state.accept({"ok": True, "launcher_pid": 42}, "status")
        self.assertFalse(state.accept({"ok": False, "error": "failed"}, "stop"))
        self.assertEqual(state.launcher_pid, 42)
        with self.assertRaises(ValueError):
            state.accept({"ok": True}, "shutdown")
        self.assertEqual(state.launcher_pid, 42)


class AbsenceTests(unittest.TestCase):
    def test_missing_key_requires_refused_connection_to_establish_absence(self):
        request = Mock(side_effect=FileNotFoundError())
        for error, expected in [(ConnectionRefusedError(), "absent"), (TimeoutError(), "timeout")]:
            result = perform("status", request_fn=request, connect_fn=Mock(side_effect=error))
            self.assertEqual(result["kind"], expected)
        socket = Mock()
        socket.__enter__ = Mock(return_value=socket)
        socket.__exit__ = Mock(return_value=None)
        self.assertEqual(perform("status", request_fn=request, connect_fn=Mock(return_value=socket))["kind"], "auth")

    def test_timeout_and_authentication_are_not_absence(self):
        for error, expected in [(TimeoutError(), "timeout"), (ConnectionError("IPC authentication failed"), "auth")]:
            result = perform("status", request_fn=Mock(side_effect=error))
            self.assertEqual(result["kind"], expected)

    def test_helper_timeout_reaps_only_owned_helper(self):
        process, job = Mock(), Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("synthetic-helper", 40)
        with patch("app.desktop.transport.popen_owned", return_value=(process, job)), \
             patch("app.desktop.transport.stop_owned") as stop:
            with self.assertRaises(TransportFault) as caught:
                AgentTransport().request("status")
        self.assertEqual(caught.exception.kind, "timeout")
        stop.assert_called_once_with(process, job, timeout=5)

    def test_real_spawn_rechecks_absence_before_any_files_or_processes(self):
        transport = AgentTransport()
        with patch.object(transport, "request", side_effect=TransportFault("auth")), \
             patch("app.desktop.transport.subprocess.Popen") as spawn:
            with self.assertRaises(TransportFault):
                transport.ensure_agent()
            spawn.assert_not_called()


class ModelHarness(unittest.TestCase):
    def setUp(self):
        app()
        self.models = []
        self.transports = []

    def tearDown(self):
        for model in self.models:
            model.requestClose()
            wait_for(lambda: not model.operation_running)
            model.deleteLater()
        app().processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for transport in self.transports:
            transport.close()

    def model(self, scenario="running", delay=0.01, **kwargs):
        transport = DemoTransport(scenario, delay)
        self.transports.append(transport)
        model = OverviewModel(transport, poll_interval=60000, **kwargs)
        self.models.append(model)
        model.begin()
        wait_for(lambda: not model.operation_running)
        return model, transport

class ModelTests(ModelHarness):
    def test_repeated_identical_polls_emit_no_property_notifications(self):
        model, transport = self.model()
        observed = {name: QSignalSpy(getattr(model, name + "Changed"))
                    for name in model._notified_properties}
        aggregate = QSignalSpy(model.changed)
        # Keep the visible receive-time unchanged too, to test value-based
        # notification rather than depending on the wall-clock second.
        with patch("app.desktop.state.datetime") as clock:
            clock.now.return_value = model.state.received_at
            for _ in range(3):
                model.poll()
                self.assertTrue(model.operation_running)
                self.assertFalse(model.busy)
                self.assertTrue(model.canStop and model.canRefresh)
                self.assertEqual(model.commandLabel, "Готов к работе")
                wait_for(lambda: not model.operation_running)
        self.assertEqual(transport.calls, ["status"] * 4)
        self.assertEqual(aggregate.count(), 0)
        self.assertTrue(all(spy.count() == 0 for spy in observed.values()))

    def test_poll_only_notifies_receive_time_when_other_values_are_unchanged(self):
        from datetime import timedelta
        model, _ = self.model()
        observed = {name: QSignalSpy(getattr(model, name + "Changed"))
                    for name in model._notified_properties}
        with patch("app.desktop.state.datetime") as clock:
            clock.now.return_value = model.state.received_at + timedelta(seconds=2)
            model.poll()
            wait_for(lambda: not model.operation_running)
        self.assertEqual(observed["lastUpdateText"].count(), 1)
        self.assertTrue(all(spy.count() == 0 for name, spy in observed.items() if name != "lastUpdateText"))

    def test_slow_poll_keeps_last_cards_controls_and_label_until_reply(self):
        model, transport = self.model()
        entered, release = threading.Event(), threading.Event()
        before = (model.processText, model.telegramText, model.agentText, model.commandLabel,
                  model.canStart, model.canStop, model.canRefresh)
        def slow(_command):
            entered.set()
            release.wait(2)
            return {"ok": True, "launcher_pid": None, "telegram_api": "unknown"}
        with patch.object(transport, "request", side_effect=slow):
            try:
                model.poll()
                wait_for(entered.is_set)
                self.assertFalse(model.busy)
                self.assertEqual(before, (model.processText, model.telegramText, model.agentText, model.commandLabel,
                                         model.canStart, model.canStop, model.canRefresh))
            finally:
                release.set()
                wait_for(lambda: not model.operation_running)
        self.assertEqual(model.processText, "Остановлен")

    def test_each_manual_action_during_poll_is_queued_once_before_next_poll(self):
        for command, method in [("probe", "refresh"), ("start", "startBot"),
                                ("stop", "stopBot"), ("shutdown", "shutdown")]:
            with self.subTest(command=command):
                model, transport = self.model("stopped" if command == "start" else "running")
                entered, release = threading.Event(), threading.Event()
                requests = []
                active = [0, 0]
                def request(action):
                    active[0] += 1
                    active[1] = max(active)
                    requests.append(action)
                    try:
                        if action == "status":
                            entered.set()
                            release.wait(2)
                        return {"ok": True, "launcher_pid": None if action in {"stop", "shutdown"} else 4242}
                    finally:
                        active[0] -= 1
                with patch.object(transport, "request", side_effect=request):
                    try:
                        model.poll()
                        wait_for(entered.is_set)
                        getattr(model, method)()
                        self.assertTrue(model.busy)
                        self.assertEqual(model._pending_command, command)
                        self.assertIn("Ожидает фонового ответа", model.commandLabel)
                        self.assertFalse(model.canStart or model.canStop or model.canRefresh)
                        getattr(model, method)()  # repeat press must not queue another action
                        model.poll()  # another timer tick cannot get ahead of the user
                        self.assertEqual(requests, ["status"])
                    finally:
                        release.set()
                        wait_for(lambda: not model.operation_running)
                self.assertEqual(requests, ["status", command])
                self.assertEqual(active[1], 1)

    def test_queued_shutdown_and_cross_wait_for_shutdown_ack_success_or_error(self):
        for success in (True, False):
            with self.subTest(success=success):
                model, transport = self.model()
                bg_entered, bg_release = threading.Event(), threading.Event()
                exit_entered, exit_release = threading.Event(), threading.Event()
                closed = QSignalSpy(model.readyToClose)
                def request(command):
                    if command == "status":
                        bg_entered.set()
                        bg_release.wait(2)
                        return {"ok": True, "launcher_pid": 4242}
                    self.assertEqual(command, "shutdown")
                    exit_entered.set()
                    exit_release.wait(2)
                    return {"ok": True, "launcher_pid": None} if success else {"ok": False, "error": "Остановка отклонена"}
                with patch.object(transport, "request", side_effect=request):
                    try:
                        model.poll()
                        wait_for(bg_entered.is_set)
                        model.shutdown()
                        self.assertFalse(model.requestClose())
                        bg_release.set()
                        wait_for(exit_entered.is_set)
                        self.assertEqual(closed.count(), 0)
                    finally:
                        bg_release.set()
                        exit_release.set()
                        wait_for(lambda: not model.operation_running)
                if success:
                    wait_for(lambda: closed.count() == 1)
                else:
                    self.assertEqual(closed.count(), 0)
                    self.assertFalse(model.closePending)
                    self.assertIn("не подтверждена", model.errorText)

    def test_background_disconnect_and_age_are_still_notified(self):
        from datetime import timedelta
        model, transport = self.model()
        stale = QSignalSpy(model.staleChanged)
        state = QSignalSpy(model.agentTextChanged)
        model.state.received_at -= timedelta(seconds=11)
        model._age()
        self.assertTrue(model.stale)
        self.assertEqual(stale.count(), 1)
        model._age()
        self.assertEqual(stale.count(), 1)
        with patch.object(transport, "request", side_effect=TransportFault("connection")):
            model.poll()
            wait_for(lambda: not model.operation_running)
        self.assertEqual(model.agentText, "Нет связи")
        self.assertEqual(state.count(), 1)
        self.assertEqual(model.state.launcher_pid, 4242)

    def test_ordinary_close_during_background_waits_without_shutdown(self):
        model, transport = self.model(delay=0.1)
        closed = QSignalSpy(model.readyToClose)
        model.poll()
        self.assertFalse(model.busy)
        self.assertFalse(model.requestClose())
        wait_for(lambda: closed.count() == 1)
        self.assertFalse(model.operation_running)
        self.assertNotIn("shutdown", transport.calls)

    def test_close_during_hung_synthetic_helper_is_bounded_and_responsive(self):
        # Real owned subprocess, but only stdlib sleep: no Agent client, key or socket.
        with tempfile.TemporaryDirectory() as directory:
            transport = AgentTransport(project_dir=directory)
            model = OverviewModel(transport, allow_autostart=False, poll_interval=60000)
            self.models.append(model)
            closed = QSignalSpy(model.readyToClose)
            ticks = []
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: ticks.append(1))
            command = [sys.executable, "-B", "-c", "import sys,time;sys.stdin.readline();time.sleep(60)"]
            with patch("app.desktop.transport.entry_command", return_value=command), \
                 patch("app.desktop.transport.CALL_TIMEOUT", 5.3):
                timer.start()
                model.poll()
                self.assertFalse(model.requestClose())
                wait_for(lambda: closed.count() == 1, timeout=3500)
                timer.stop()
            self.assertFalse(model.busy)
            self.assertGreater(len(ticks), 3)
            self.assertIn("вовремя", model.errorText)

    def test_running_and_stopped_controls(self):
        model, _ = self.model()
        self.assertTrue(model.canStop)
        self.assertFalse(model.canStart)
        model.stopBot()
        wait_for(lambda: not model.operation_running)
        self.assertTrue(model.canStart)
        self.assertEqual(model.processText, "Остановлен")

    def test_disconnection_preserves_snapshot_and_disables_mutating_controls(self):
        model, _ = self.model("disconnected")
        stamp = model.lastUpdateText
        model.refresh()
        wait_for(lambda: not model.operation_running)
        self.assertEqual(model.agentText, "Нет связи")
        self.assertEqual(model.botDisplayName, "@media_demo_bot")
        self.assertEqual(model.lastUpdateText, stamp)
        self.assertTrue(model.stale)
        self.assertFalse(model.canStart or model.canStop)

    def test_busy_rejects_repeated_commands_and_ui_keeps_ticking(self):
        model, transport = self.model(delay=0.15)
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        count = len(transport.calls)
        model.refresh()
        model.refresh()
        model.startBot()
        model.stopBot()
        wait_for(lambda: not model.operation_running)
        timer.stop()
        self.assertEqual(len(transport.calls), count + 1)
        self.assertGreater(len(ticks), 2)

    def test_cross_close_waits_for_thread_without_shutdown(self):
        model, transport = self.model(delay=0.15)
        closed = QSignalSpy(model.readyToClose)
        model.refresh()
        self.assertFalse(model.requestClose())
        self.assertTrue(model.closePending)
        wait_for(lambda: closed.count() == 1)
        self.assertFalse(model.busy)
        self.assertNotIn("shutdown", transport.calls)
        self.assertTrue(model.requestClose())

    def test_exit_only_closes_after_explicit_stopped_ack(self):
        model, transport = self.model()
        closed = QSignalSpy(model.readyToClose)
        model.shutdown()
        wait_for(lambda: closed.count() == 1)
        self.assertIn("shutdown", transport.calls)
        self.assertFalse(model.busy)

    def test_exit_error_keeps_window_open_even_if_cross_clicked(self):
        model, _ = self.model("error", delay=0.1)
        closed = QSignalSpy(model.readyToClose)
        model.shutdown()
        self.assertFalse(model.requestClose())
        wait_for(lambda: not model.operation_running)
        self.assertEqual(closed.count(), 0)
        self.assertFalse(model.closePending)
        self.assertIn("не подтвердил", model.errorText)
        self.assertEqual(model.state.launcher_pid, 4242)

    def test_exit_without_process_ack_keeps_window_open(self):
        model, transport = self.model()
        closed = QSignalSpy(model.readyToClose)
        with patch.object(transport, "request", return_value={"ok": True}):
            model.shutdown()
            wait_for(lambda: not model.operation_running)
        self.assertEqual(closed.count(), 0)
        self.assertTrue(model.errorText)

    def test_exit_error_remains_after_background_poll_and_no_respawn(self):
        model, transport = self.model("error")
        model.shutdown()
        wait_for(lambda: not model.operation_running)
        error = model.errorText
        model.poll()
        wait_for(lambda: not model.operation_running)
        self.assertEqual(model.errorText, error)
        self.assertFalse(model._allow_autostart)

    def test_known_service_loss_does_not_trigger_initial_auto_start(self):
        transport = Mock(demo=False)
        transport.request.side_effect = [{"ok": True, "launcher_pid": 123}, TransportFault("absent")]
        transport.read_log.return_value = []
        model = OverviewModel(transport, allow_autostart=True, poll_interval=60000)
        self.models.append(model)
        model.begin()
        wait_for(lambda: not model.operation_running)
        model.poll()
        wait_for(lambda: not model.operation_running)
        transport.ensure_agent.assert_not_called()
        self.assertEqual(model.state.launcher_pid, 123)

    def test_no_auto_start_on_timeout_auth_or_demo_absence(self):
        for fault in ("timeout", "auth", "absent"):
            model, transport = self.model()
            with patch.object(transport, "request", side_effect=TransportFault(fault)), \
                 patch.object(transport, "ensure_agent") as spawn:
                model.poll()
                wait_for(lambda: not model.operation_running)
                spawn.assert_not_called()

    def test_confirmed_absence_auto_start_once_on_non_demo_injected_transport(self):
        # Injection only. No AgentTransport or real process can be reached.
        transport = Mock(demo=False)
        transport.request.side_effect = TransportFault("absent")
        transport.read_log.return_value = []
        transport.ensure_agent.return_value = {"spawned": True}
        model = OverviewModel(transport, allow_autostart=True, poll_interval=60000)
        self.models.append(model)
        model.begin()
        wait_for(lambda: not model.operation_running and transport.ensure_agent.call_count == 1)
        model.poll()
        wait_for(lambda: not model.operation_running)
        self.assertEqual(transport.ensure_agent.call_count, 1)

    def test_log_is_bounded(self):
        model, _ = self.model()
        model._runtime_lines = ["fixture"] * 150
        for i in range(500):
            model._event(str(i))
        self.assertEqual(model.logCount, 200)


class QMLTests(ModelHarness):
    def load_window(self, model):
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda values: warnings.extend(str(value) for value in values))
        engine.rootContext().setContextProperty("overview", model)
        engine.load(QUrl.fromLocalFile(str(PROJECT_DIR / "app/desktop/qml/Overview.qml")))
        self.assertTrue(engine.rootObjects(), warnings)
        window = engine.rootObjects()[0]
        QTest.qWait(70)
        return engine, window, warnings

    def dispose(self, engine, window, model):
        window.close()
        wait_for(lambda: not model.operation_running)
        app().processEvents()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_glass_layout_at_three_logical_dpi_viewports_and_long_username(self):
        for scale in (1, 1.25, 1.5):
            with self.subTest(scale=scale):
                model, _ = self.model()
                model.state.username = "a_long_username_to_check_the_narrow_window_and_elision_123456"
                model._publish()
                engine, window, warnings = self.load_window(model)
                try:
                    window.setWidth(round(1366 / scale))
                    window.setHeight(round(768 / scale))
                    QTest.qWait(80)
                    for name in ("identityPanel", "agentCard", "processCard", "telegramCard",
                                 "controlPanel", "startButton", "stopButton", "refreshButton", "exitButton"):
                        item = window.findChild(QObject, name)
                        point = item.mapToItem(window.contentItem(), QPointF(0, 0))
                        self.assertGreaterEqual(point.x(), 0)
                        self.assertLessEqual(point.x() + item.property("width"), window.width() + 1)
                        if name in {"startButton", "stopButton", "refreshButton"}:
                            self.assertLessEqual(point.y() + item.property("height"), window.height() + 1)
                    title = window.findChild(QObject, "botTitle")
                    self.assertEqual(title.property("text"), model.botDisplayName)
                    self.assertLess(title.property("width"), window.width())
                    scroll = window.findChild(QObject, "mainScroll")
                    self.assertLessEqual(scroll.property("contentWidth"), scroll.property("availableWidth") + 1)
                    bar = window.findChild(QObject, "mainVerticalScrollBar")
                    self.assertAlmostEqual(bar.property("height"), scroll.property("height"), delta=1)
                    point = bar.mapToItem(window.contentItem(), QPointF(0, 0))
                    self.assertGreater(point.x(), window.width() - 40)
                    self.assertFalse(warnings)
                finally:
                    self.dispose(engine, window, model)

    def test_compact_journal_expands_by_keyboard_without_changing_actions(self):
        model, _ = self.model()
        engine, window, warnings = self.load_window(model)
        try:
            journal = window.findChild(QObject, "journalPanel")
            button = window.findChild(QObject, "expandJournalButton")
            initial_height = journal.property("height")
            view = window.findChild(QObject, "logView")
            self.assertLessEqual(view.property("count"), 3)
            button.forceActiveFocus()
            self.assertTrue(button.property("activeFocus"))
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(80)
            self.assertTrue(window.property("journalExpanded"))
            self.assertGreater(journal.property("height"), initial_height)
            self.assertEqual(button.property("text"), "Свернуть")
            self.assertEqual(view.property("count"), model.logCount)
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(80)
            self.assertEqual(journal.property("height"), initial_height)
            self.assertTrue(model.canStop)
            self.assertFalse(warnings)
        finally:
            self.dispose(engine, window, model)

    def test_lite_mode_only_uses_background_source_and_never_fades_labels(self):
        model, _ = self.model()
        engine, window, warnings = self.load_window(model)
        try:
            window.setProperty("liteEffects", True)
            QTest.qWait(40)
            self.assertFalse(window.property("blurEnabled"))
            source = window.findChild(QObject, "ambientBackground")
            for name in ("navigationGlass", "controlsGlass"):
                self.assertEqual(window.findChild(QObject, name).property("backdropSource"), source)
            self.assertEqual(window.findChildren(QObject, "glassBackdropCapture"), [])
            for name in ("startButton", "stopButton", "refreshButton", "exitButton"):
                item = window.findChild(QObject, name)
                self.assertEqual(item.property("opacity"), 1)
                self.assertEqual(item.property("contentItem").property("opacity"), 1)
            self.assertFalse(window.findChild(QObject, "futureBotsTab").property("enabled"))
            self.assertFalse(warnings)
        finally:
            self.dispose(engine, window, model)

    def test_capsule_keyboard_focus_and_activation(self):
        model, _ = self.model()
        engine, window, warnings = self.load_window(model)
        try:
            button = window.findChild(QObject, "stopButton")
            button.forceActiveFocus()
            self.assertTrue(button.property("activeFocus"))
            QTest.keyClick(window, Qt.Key_Space)
            wait_for(lambda: not model.operation_running)
            self.assertEqual(model.state.launcher_pid, None)
            self.assertTrue(model.canStart)
            self.assertFalse(warnings)
        finally:
            self.dispose(engine, window, model)

    def test_rendered_background_contrast_for_text_glass_and_disabled_button(self):
        def luminance(color):
            values = [color.redF(), color.greenF(), color.blueF()]
            values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
            return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722)))
        def contrast(a, b):
            a, b = sorted((luminance(a), luminance(b)))
            return (b + 0.05) / (a + 0.05)
        model, _ = self.model()
        engine, window, warnings = self.load_window(model)
        try:
            image = window.grabWindow()
            ratio = window.devicePixelRatio()
            def sample(name, dx, dy):
                item = window.findChild(QObject, name)
                point = item.mapToItem(window.contentItem(), QPointF(dx, dy))
                return image.pixelColor(int(point.x() * ratio), int(point.y() * ratio))
            card = sample("agentCard", 8, 55)
            nav = sample("floatingNavigation", 30, 350)
            controls = window.findChild(QObject, "controlPanel")
            glass = sample("controlPanel", controls.property("width") - 35, 85)
            disabled = sample("startButton", 76, 36)
            for foreground in ("#F2F0EB", "#B6BAC4", "#979FAB"):
                self.assertGreaterEqual(contrast(QColor(foreground), card), 4.5)
            for background in (nav, glass):
                self.assertGreaterEqual(contrast(QColor("#C7B38A"), background), 4.5)
                self.assertGreaterEqual(contrast(QColor("#B6BAC4"), background), 4.5)
            self.assertGreaterEqual(contrast(QColor("#89929F"), disabled), 4.5)
            self.assertGreaterEqual(contrast(QColor("#102D27"), QColor("#60BEAC")), 4.5)
            self.assertGreaterEqual(contrast(QColor("#EF8F8F"), QColor("#302329")), 4.5)
            self.assertFalse(warnings)
        finally:
            self.dispose(engine, window, model)

    def test_qml_loads_all_five_states_and_renders(self):
        for scenario in ("running", "stopped", "disconnected", "busy", "error"):
            with self.subTest(scenario=scenario):
                model, _ = self.model(scenario)
                engine = QQmlApplicationEngine()
                warnings = []
                engine.warnings.connect(lambda values: warnings.extend(str(value) for value in values))
                engine.rootContext().setContextProperty("overview", model)
                engine.load(QUrl.fromLocalFile(str(PROJECT_DIR / "app/desktop/qml/Overview.qml")))
                self.assertTrue(engine.rootObjects(), warnings)
                window = engine.rootObjects()[0]
                QTest.qWait(80)
                if scenario in {"disconnected", "busy", "error"}:
                    model.refresh()
                    if scenario == "busy":
                        QTest.qWait(40)
                        self.assertTrue(model.busy)
                    else:
                        wait_for(lambda: not model.operation_running)
                self.assertFalse(window.grabWindow().isNull())
                for name in ("startButton", "stopButton", "refreshButton", "exitButton", "logView"):
                    self.assertIsNotNone(window.findChild(QObject, name))
                self.assertFalse(warnings, warnings)
                window.close()
                wait_for(lambda: not model.operation_running)
                app().processEvents()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
