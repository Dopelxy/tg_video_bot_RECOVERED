"""First desktop window connected to the independent local agent.

This is a functional control pilot. The final dashboard will use Qt Quick.
"""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from local_agent import request


PROJECT_DIR = Path(__file__).resolve().parent


class CommandThread(QThread):
    result = Signal(object)

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command

    def run(self) -> None:
        try:
            self.result.emit(request(PROJECT_DIR, self.command))
        except Exception as error:
            self.result.emit({"ok": False, "error": type(error).__name__})


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Telegram Media Bot — управление")
        self.resize(780, 590)
        self._worker: CommandThread | None = None
        self._last_log = None
        self._agent_process: subprocess.Popen | None = None
        self._agent_start_error: str | None = None
        self._exit_confirmed = False
        self._agent_attempted = False

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        root = QWidget()
        self.tabs.addTab(root, "Управление")
        bot_picker = QWidget()
        self.tabs.addTab(bot_picker, "Выбор бота · скоро")
        self.tabs.setTabEnabled(1, False)
        self.tabs.setTabToolTip(1, "Здесь появится выбор бота для управления")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 25, 28, 25)
        layout.setSpacing(18)

        title = QLabel("TELEGRAM MEDIA BOT")
        title.setObjectName("title")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        self.exit_button = QPushButton("Выход")
        self.exit_button.setObjectName("exit")
        self.exit_button.setFixedWidth(95)
        header.addWidget(self.exit_button)
        layout.addLayout(header)
        subtitle = QLabel("Локальное управление")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        self.service_label = QLabel("Служба: проверяю соединение…")
        self.service_label.setObjectName("card")
        self.bot_label = QLabel("Бот: состояние неизвестно")
        self.bot_label.setObjectName("card")
        self.telegram_label = QLabel("Telegram API: ожидаю данные…")
        self.telegram_label.setObjectName("card")
        layout.addWidget(self.service_label)
        layout.addWidget(self.bot_label)
        layout.addWidget(self.telegram_label)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.start_button = QPushButton("▶  ЗАПУСТИТЬ")
        self.start_button.setObjectName("start")
        self.stop_button = QPushButton("■  ОСТАНОВИТЬ")
        self.stop_button.setObjectName("stop")
        self.refresh_button = QPushButton("⟳  ОБНОВИТЬ")
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)
        self.checked_label = QLabel("Ручная проверка: ещё не выполнялась")
        self.checked_label.setObjectName("subtitle")
        layout.addWidget(self.checked_label)

        log_title = QLabel("ЖУРНАЛ")
        log_title.setObjectName("section")
        layout.addWidget(log_title)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("События бота появятся здесь")
        layout.addWidget(self.log_view, stretch=1)

        self.start_button.clicked.connect(lambda: self.run_command("start"))
        self.stop_button.clicked.connect(lambda: self.run_command("stop"))
        self.refresh_button.clicked.connect(lambda: self.run_command("probe"))
        self.exit_button.clicked.connect(lambda: self.run_command("shutdown"))

        self.setStyleSheet("""
            QWidget { background: #11151f; color: #e9eef9;
                      font-family: 'Segoe UI'; font-size: 14px; }
            QLabel#title { color: #79d9ff; font-size: 25px;
                           font-weight: 700; letter-spacing: 2px; }
            QLabel#subtitle { color: #8998af; font-size: 14px; }
            QLabel#section { color: #9eb2cf; font-size: 12px;
                             font-weight: 700; }
            QLabel#card { background: #1c2534; border: 1px solid #33445e;
                          border-radius: 11px; padding: 15px; font-size: 17px; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #1c2534; color: #aab8cc;
                           padding: 10px 18px; margin-right: 4px;
                           border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #29364a; color: #79d9ff; }
            QTabBar::tab:disabled { background: #171d28; color: #687487; }
            QPushButton { padding: 12px 16px; border-radius: 9px;
                          background: #29364a; font-weight: 600; }
            QPushButton:hover { background: #38526b; }
            QPushButton:disabled { color: #788394; background: #202937; }
            QPushButton#start { background: #197d78; }
            QPushButton#start:hover { background: #229c94; }
            QPushButton#stop { background: #74424a; }
            QPushButton#stop:hover { background: #94515b; }
            QPushButton#exit { padding: 7px 10px; font-size: 12px;
                               background: #343b4b; }
            QPushButton#exit:hover { background: #74424a; }
            QPlainTextEdit { background: #0c1119; border: 1px solid #33445e;
                             border-radius: 9px; padding: 10px;
                             font-family: 'Consolas'; font-size: 12px; }
        """)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _ensure_agent(self) -> None:
        if self._agent_attempted:
            return
        self._agent_attempted = True
        data_dir = PROJECT_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        options: dict = {}
        if sys.platform == "win32":
            # No console and no ownership link to the desktop window.
            options["creationflags"] = subprocess.DETACHED_PROCESS
        else:
            options["start_new_session"] = True

        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            with (data_dir / "agent.log").open("ab", buffering=0) as log_file:
                self._agent_process = subprocess.Popen(
                    [sys.executable, "-u", str(PROJECT_DIR / "local_agent.py"), "serve"],
                    cwd=PROJECT_DIR,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    **options,
                )
        except OSError as error:
            self._agent_start_error = str(error)

    def run_command(self, command: str) -> None:
        if self._worker is not None:
            return
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.exit_button.setEnabled(False)
        if command == "probe":
            self.checked_label.setText("Ручная проверка: выполняется…")
            self.telegram_label.setText("Telegram API: проверяю сейчас…")
        elif command == "shutdown":
            self._exit_confirmed = False
            self.checked_label.setText("Выход: останавливаю бота и службу…")
        worker = CommandThread(command)
        self._worker = worker
        worker.result.connect(self._on_result)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_result(self, response: dict) -> None:
        if self._worker is not None and self._worker.command == "status":
            if response.get("ok"):
                self._apply_status(response)
            else:
                self.service_label.setText("Служба: нет соединения")
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(False)
                self._ensure_agent()
            self._refresh_log()
            return
        checking = self._worker is not None and self._worker.command == "probe"
        shutting_down = self._worker is not None and self._worker.command == "shutdown"
        if shutting_down:
            self._exit_confirmed = bool(response.get("ok")) and response.get("launcher_pid") is None
            if not self._exit_confirmed:
                reason = response.get("error") or "Не удалось подтвердить остановку"
                self.checked_label.setText(f"Выход не выполнен: {reason}")
        if not response.get("ok"):
            self.service_label.setText("Служба: ошибка команды")
            self.bot_label.setText(response.get("error", "Состояние неизвестно"))
            if checking:
                self.checked_label.setText("Ручная проверка: не удалась")
                self.telegram_label.setText("Telegram API: состояние неизвестно")
        else:
            pid = response.get("launcher_pid")
            self.bot_label.setText(
                f"Бот: launcher работает · PID {pid}" if pid else "Бот: остановлен"
            )
            if checking:
                self.checked_label.setText(f"Ручная проверка: {response['checked_at']}")
                state = response.get("telegram_api")
                if not pid:
                    self.telegram_label.setText("Telegram API: бот остановлен")
                elif state == "reachable":
                    username = response.get("bot_username") or "бот"
                    self.telegram_label.setText(f"Telegram API: доступен · @{username}")
                else:
                    self.telegram_label.setText("Telegram API: нет ответа при ручной проверке")

    def _on_finished(self) -> None:
        was_status = self._worker is not None and self._worker.command == "status"
        was_probe = self._worker is not None and self._worker.command == "probe"
        was_shutdown = self._worker is not None and self._worker.command == "shutdown"
        self._worker = None
        if was_shutdown and self._exit_confirmed:
            self.timer.stop()
            self.close()
            return
        if was_status:
            self.refresh_button.setEnabled(True)
        elif was_probe:
            self.refresh_button.setEnabled(True)
            self.start_button.setEnabled(self.bot_label.text() == "Бот: остановлен")
            self.stop_button.setEnabled(self.bot_label.text().startswith("Бот: launcher работает"))
        else:
            self.refresh()
        self.exit_button.setEnabled(True)

    def refresh(self) -> None:
        if self._worker is None:
            self.run_command("status")

    def _apply_status(self, status: dict) -> None:
        self._agent_start_error = None
        self.service_label.setText("Служба: подключена к этому ПК")
        pid = status.get("launcher_pid")
        self.bot_label.setText(
            f"Бот: launcher работает · PID {pid}" if pid else "Бот: остановлен"
        )
        api_state = status.get("telegram_api")
        if not pid:
            self.telegram_label.setText("Telegram API: бот остановлен")
        elif api_state == "reachable":
            username = status.get("bot_username") or "бот"
            self.telegram_label.setText(f"Telegram API: доступен · @{username}")
        elif api_state == "unreachable":
            self.telegram_label.setText("Telegram API: нет ответа при последней проверке")
        else:
            self.telegram_label.setText("Telegram API: проверяю / бот перезапускается")
        self.start_button.setEnabled(pid is None)
        self.stop_button.setEnabled(pid is not None)

    def _refresh_log(self) -> None:
        log_path = PROJECT_DIR / "data" / "runtime.log"
        try:
            with log_path.open("rb") as log_file:
                log_file.seek(0, 2)
                size = log_file.tell()
                log_file.seek(max(0, size - 100_000))
                chunk = log_file.read()
            lines = chunk.decode("utf-8", errors="replace").splitlines()[-70:]
            current = "\n".join(lines)
        except OSError:
            current = ""
        if current != self._last_log:
            self._last_log = current
            self.log_view.setPlainText(current)
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self.bot_label.setText("Дождись завершения команды перед закрытием")
            event.ignore()
            return
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
