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
            self.result.emit({"ok": False, "error": str(error)})


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Telegram Media Bot — управление")
        self.resize(780, 590)
        self._worker: CommandThread | None = None
        self._last_log = None
        self._agent_process: subprocess.Popen | None = None
        self._agent_start_error: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 25, 28, 25)
        layout.setSpacing(18)

        title = QLabel("TELEGRAM MEDIA BOT")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Локальное управление")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        self.service_label = QLabel("Служба: проверяю соединение…")
        self.service_label.setObjectName("card")
        self.bot_label = QLabel("Бот: состояние неизвестно")
        self.bot_label.setObjectName("card")
        layout.addWidget(self.service_label)
        layout.addWidget(self.bot_label)

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

        log_title = QLabel("ЖУРНАЛ")
        log_title.setObjectName("section")
        layout.addWidget(log_title)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("События бота появятся здесь")
        layout.addWidget(self.log_view, stretch=1)

        self.start_button.clicked.connect(lambda: self.run_command("start"))
        self.stop_button.clicked.connect(lambda: self.run_command("stop"))
        self.refresh_button.clicked.connect(self.refresh)

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
            QPushButton { padding: 12px 16px; border-radius: 9px;
                          background: #29364a; font-weight: 600; }
            QPushButton:hover { background: #38526b; }
            QPushButton:disabled { color: #788394; background: #202937; }
            QPushButton#start { background: #197d78; }
            QPushButton#start:hover { background: #229c94; }
            QPushButton#stop { background: #74424a; }
            QPushButton#stop:hover { background: #94515b; }
            QPlainTextEdit { background: #0c1119; border: 1px solid #33445e;
                             border-radius: 9px; padding: 10px;
                             font-family: 'Consolas'; font-size: 12px; }
        """)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self._ensure_agent()
        self.refresh()

    def _ensure_agent(self) -> None:
        try:
            request(PROJECT_DIR, "status")
            return
        except (OSError, EOFError, ConnectionError):
            pass

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
        worker = CommandThread(command)
        self._worker = worker
        worker.result.connect(self._on_result)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_result(self, response: dict) -> None:
        if not response.get("ok"):
            self.service_label.setText("Служба: ошибка команды")
            self.bot_label.setText(response.get("error", "Состояние неизвестно"))
        else:
            pid = response.get("launcher_pid")
            self.bot_label.setText(
                f"Бот: launcher работает · PID {pid}" if pid else "Бот: остановлен"
            )

    def _on_finished(self) -> None:
        self._worker = None
        self.refresh()

    def refresh(self) -> None:
        if self._worker is not None:
            return
        try:
            status = request(PROJECT_DIR, "status")
        except Exception as error:
            self.service_label.setText("Служба: нет соединения")
            if self._agent_start_error is not None:
                detail = self._agent_start_error
            elif self._agent_process is not None and self._agent_process.poll() is None:
                detail = "Запускается…"
            else:
                detail = f"Не удалось подключиться: {error}"
            self.bot_label.setText(detail)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
        else:
            self._agent_start_error = None
            self.service_label.setText("Служба: подключена к этому ПК")
            pid = status.get("launcher_pid")
            self.bot_label.setText(
                f"Бот: launcher работает · PID {pid}" if pid else "Бот: остановлен"
            )
            self.start_button.setEnabled(pid is None)
            self.stop_button.setEnabled(pid is not None)
        self.refresh_button.setEnabled(True)
        self._refresh_log()

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
