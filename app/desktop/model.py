"""Qt-facing model. Every transport call (including log I/O) runs in QThread."""
from collections import deque
from datetime import datetime

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app.desktop.state import OverviewState
from app.desktop.transport import TransportFault, CALL_TIMEOUT


class CommandWorker(QThread):
    outcome = Signal(object)

    def __init__(self, transport, command, parent):
        super().__init__(parent)
        self.transport, self.command = transport, command

    def run(self):
        result = {"command": self.command}
        try:
            result["payload"] = (self.transport.ensure_agent() if self.command == "spawn"
                                 else self.transport.request(self.command))
        except TransportFault as error:
            result.update(fault=error.kind, message=str(error))
        except Exception:
            result.update(fault="connection", message="Не удалось выполнить локальную команду.")
        try:
            result["logs"] = self.transport.read_log()
        except Exception:
            result["logs"] = []
        self.outcome.emit(result)


class OverviewModel(QObject):
    changed = Signal()
    readyToClose = Signal()
    busyChanged = Signal()
    closePendingChanged = Signal()
    canStartChanged = Signal()
    canStopChanged = Signal()
    canRefreshChanged = Signal()
    botDisplayNameChanged = Signal()
    botUsernameChanged = Signal()
    agentTextChanged = Signal()
    agentStateChanged = Signal()
    processTextChanged = Signal()
    processDetailChanged = Signal()
    telegramTextChanged = Signal()
    telegramStateChanged = Signal()
    lastUpdateTextChanged = Signal()
    staleChanged = Signal()
    hasSnapshotChanged = Signal()
    processRunningChanged = Signal()
    errorTextChanged = Signal()
    commandLabelChanged = Signal()
    logLinesChanged = Signal()
    logCountChanged = Signal()

    _notified_properties = (
        "busy", "closePending", "canStart", "canStop", "canRefresh", "botDisplayName", "botUsername",
        "agentText", "agentState", "processText", "processDetail", "telegramText", "telegramState",
        "lastUpdateText", "stale", "hasSnapshot", "processRunning", "errorText", "commandLabel",
        "logLines", "logCount",
    )

    def __init__(self, transport, *, allow_autostart=False, poll_interval=2000, parent=None):
        super().__init__(parent)
        self.transport = transport
        self.state = OverviewState()
        self._worker = None
        self._command = ""
        self._pending_command = None
        self._events = deque(maxlen=50)
        self._runtime_lines = []
        self._closing = False
        self._allow_close = False
        self._shutdown_confirmed = False
        self._spawn_after_finish = False
        self._spawn_attempted = False
        self._sticky_error = False
        self._allow_autostart = allow_autostart and not transport.demo
        self.timer = QTimer(self)
        self.timer.setInterval(poll_interval)
        self.timer.timeout.connect(self.poll)
        self.age_timer = QTimer(self)
        self.age_timer.setInterval(1000)
        self.age_timer.timeout.connect(self._age)
        self._published = {name: getattr(self, name) for name in self._notified_properties}

    def _publish(self):
        """Notify only properties whose exposed values actually changed."""
        values = {name: getattr(self, name) for name in self._notified_properties}
        modified = [name for name, value in values.items() if self._published[name] != value]
        self._published.update(values)
        for name in modified:
            getattr(self, name + "Changed").emit()
        if modified:
            self.changed.emit()  # compatibility for Python observers, not QML bindings

    @property
    def operation_running(self):
        """Thread lifetime, distinct from the visible foreground busy state."""
        return self._worker is not None

    @property
    def foreground_command(self):
        return self._pending_command or (self._command if self._command != "status" else "")

    def _event(self, message):
        self._events.append(datetime.now().strftime("%H:%M:%S") + " · " + message)

    @Slot()
    def begin(self):
        self.timer.start()
        self.age_timer.start()
        self.poll()

    def _prepare_command(self, command):
        if command not in {"status", "spawn"}:
            self._sticky_error = False
            self.state.error = ""
        if command == "shutdown":
            self._shutdown_confirmed = False
            self._allow_autostart = False  # never respawn a service after an Exit attempt
            self._spawn_after_finish = False

    def _run(self, command, *, allow_closing=False):
        if self.operation_running or (self._closing and not allow_closing):
            return False
        self._command = command
        self._prepare_command(command)
        worker = CommandWorker(self.transport, command, self)
        self._worker = worker
        worker.outcome.connect(self._on_outcome)
        worker.finished.connect(self._on_finished)
        self._publish()
        worker.start()
        return True

    def _request_command(self, command):
        if self._closing or self.busy:
            return False
        if self.operation_running:
            # One accepted user action, ahead of any later poll. While queued it
            # is already foreground-busy, so repeat presses cannot pile up.
            self._pending_command = command
            self._prepare_command(command)
            self._publish()
            return True
        return self._run(command)

    @Slot()
    def poll(self):
        if not self._pending_command:
            self._run("status")

    @Slot()
    def refresh(self):
        self._request_command("probe")

    @Slot()
    def startBot(self):
        if self.canStart:
            self._request_command("start")

    @Slot()
    def stopBot(self):
        if self.canStop:
            self._request_command("stop")

    @Slot()
    def shutdown(self):
        self._request_command("shutdown")

    @Slot(result=bool)
    def requestClose(self):
        if self._allow_close:
            return True
        self.timer.stop()
        self._closing = True
        if self.operation_running:
            self._publish()
            return False
        self.age_timer.stop()
        self._allow_close = True
        return True

    @Slot(object)
    def _on_outcome(self, result):
        command = result["command"]
        self._runtime_lines = [str(line)[:1000] for line in result.get("logs", [])[-150:]]
        previous_error = self.state.error
        if "fault" in result:
            self.state.disconnect(result["message"])
            if (result["fault"] == "absent" and command == "status" and self._allow_autostart
                    and not self._spawn_attempted and not self.state.has_snapshot and not self._closing):
                self._spawn_attempted = True
                self._spawn_after_finish = True
        elif command == "spawn":
            self.state.agent = "starting"
            self.state.error = ""
            self._event("Запуск Agent запрошен; ожидаю подтверждения связи.")
        else:
            try:
                accepted = self.state.accept(result["payload"], command)
            except (ValueError, TypeError):
                accepted = False
                self.state.disconnect("Agent вернул некорректное состояние. Последние данные сохранены.")
            if command == "status" and accepted and self._sticky_error:
                self.state.error = previous_error
            elif not accepted and command != "status":
                self._sticky_error = True
            if command == "shutdown":
                self._shutdown_confirmed = accepted and self.state.launcher_pid is None
                if not self._shutdown_confirmed:
                    self.state.error = self.state.error or "Остановка локальной цепочки не подтверждена. Окно осталось открытым."
            elif command != "status" and accepted:
                self._event({"start": "Agent подтвердил запуск launcher.", "stop": "Agent подтвердил остановку launcher.",
                             "probe": "Ручная проверка завершена."}.get(command, "Команда завершена."))
        if self.state.error and (self.state.error != previous_error or command != "status"):
            self._event(self.state.error)
        # Even a normal window-close request during shutdown must not hide a
        # failure to confirm shutdown. Only finished() may authorize closing.
        if command == "shutdown" and not self._shutdown_confirmed:
            if "Остановка локальной цепочки не подтверждена" not in self.state.error:
                self.state.error = "Остановка локальной цепочки не подтверждена. " + self.state.error
            self._sticky_error = True
            self._closing = False
            self.timer.start()
        self._publish()

    @Slot()
    def _on_finished(self):
        worker = self._worker
        command = self._command
        self._worker = None
        self._command = ""
        worker.deleteLater()  # finished, never destroy or terminate a live thread
        if command == "shutdown" and self._shutdown_confirmed:
            self._closing = True
        if self._pending_command is not None:
            command = self._pending_command
            self._pending_command = None
            # A cross-click waits for the already accepted action as well. A
            # queued shutdown must still receive its own acknowledgement.
            self._run(command, allow_closing=True)
            return
        if self._closing:
            self.timer.stop()
            self.age_timer.stop()
            self._allow_close = True
            self._publish()
            QTimer.singleShot(0, self.readyToClose.emit)
            return
        if self._spawn_after_finish:
            self._spawn_after_finish = False
            self._run("spawn")
        elif command in {"spawn", "start", "stop"}:
            QTimer.singleShot(250, self.poll)
        self._publish()

    @Slot()
    def _age(self):
        if self.state.received_at and (datetime.now().astimezone() - self.state.received_at).total_seconds() > 10:
            if not self.state.stale:
                self.state.stale = True
                self._publish()

    def _command_label(self):
        if self.closePending:
            if self._pending_command:
                return f"Жду фоновый запрос и команду · до {CALL_TIMEOUT} с на запрос"
            return f"Жду завершения запроса · до {CALL_TIMEOUT} с"
        value = {"probe": "Проверяю Telegram через Agent…", "start": "Запускаю бота…",
                 "stop": "Останавливаю бота…", "shutdown": "Останавливаю бота и службу…",
                 "spawn": "Запускаю Agent…"}.get(self.foreground_command, "Готов к работе")
        return "Ожидает фонового ответа · " + value if self._pending_command else value

    busy = Property(bool, lambda self: bool(self.foreground_command), notify=busyChanged)
    demoMode = Property(bool, lambda self: self.transport.demo, constant=True)
    closePending = Property(bool, lambda self: self._closing and not self._allow_close, notify=closePendingChanged)
    canStart = Property(bool, lambda self: not self.busy and not self._closing and self.state.agent == "connected"
                        and self.state.has_snapshot and not self.state.stale and self.state.launcher_pid is None, notify=canStartChanged)
    canStop = Property(bool, lambda self: not self.busy and not self._closing and self.state.agent == "connected"
                       and self.state.has_snapshot and not self.state.stale and self.state.launcher_pid is not None, notify=canStopChanged)
    canRefresh = Property(bool, lambda self: not self.busy and not self._closing, notify=canRefreshChanged)
    botDisplayName = Property(str, lambda self: self.state.display_name, notify=botDisplayNameChanged)
    botUsername = Property(str, lambda self: "@" + self.state.username if self.state.username else "Username пока неизвестен", notify=botUsernameChanged)
    agentText = Property(str, lambda self: {"unknown": "Проверяю…", "connected": "На связи", "disconnected": "Нет связи",
                                          "starting": "Запускается…"}[self.state.agent], notify=agentTextChanged)
    agentState = Property(str, lambda self: self.state.agent, notify=agentStateChanged)
    processText = Property(str, lambda self: self.state.process_text, notify=processTextChanged)
    processDetail = Property(str, lambda self: f"Watchdog · PID {self.state.launcher_pid}" if self.state.launcher_pid
                             else "Нет подтверждённого launcher" if not self.state.has_snapshot else "Agent подтвердил остановку launcher", notify=processDetailChanged)
    telegramText = Property(str, lambda self: self.state.telegram_text, notify=telegramTextChanged)
    telegramState = Property(str, lambda self: self.state.telegram, notify=telegramStateChanged)
    lastUpdateText = Property(str, lambda self: "Ответ Agent: " + self.state.received_at.strftime("%H:%M:%S")
                              if self.state.received_at else "Ответ Agent ещё не получен", notify=lastUpdateTextChanged)
    stale = Property(bool, lambda self: self.state.stale, notify=staleChanged)
    hasSnapshot = Property(bool, lambda self: self.state.has_snapshot, notify=hasSnapshotChanged)
    processRunning = Property(bool, lambda self: self.state.launcher_pid is not None, notify=processRunningChanged)
    errorText = Property(str, lambda self: self.state.error, notify=errorTextChanged)
    commandLabel = Property(str, _command_label, notify=commandLabelChanged)
    logLines = Property("QStringList", lambda self: (self._runtime_lines + list(self._events))[-200:], notify=logLinesChanged)
    logCount = Property(int, lambda self: len(self.logLines), notify=logCountChanged)
