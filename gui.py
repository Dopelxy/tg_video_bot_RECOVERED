import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QThread,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.storage.stats import stats_storage


PROJECT_DIR = Path(__file__).parent
LAUNCHER_FILE = PROJECT_DIR / "launcher.py"


def format_bytes(
    value: int,
) -> str:
    size = float(
        max(
            value,
            0,
        )
    )

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    )

    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"

        size /= 1024

    return f"{size:.1f} PB"


class ProcessOutputThread(QThread):
    line_received = Signal(str)

    def __init__(
        self,
        process: subprocess.Popen,
    ) -> None:
        super().__init__()

        self.process = process

    def run(self) -> None:
        if self.process.stdout is None:
            return

        for line in self.process.stdout:
            text = line.rstrip()

            if text:
                self.line_received.emit(
                    text
                )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.launcher_process: (
            subprocess.Popen | None
        ) = None

        self.output_thread: (
            ProcessOutputThread | None
        ) = None

        self.started_at: (
            datetime | None
        ) = None

        self.setWindowTitle(
            "Telegram Media Bot"
        )

        self.resize(
            900,
            680,
        )

        central_widget = QWidget()

        self.setCentralWidget(
            central_widget
        )

        main_layout = QVBoxLayout(
            central_widget
        )

        self.title_label = QLabel(
            "Telegram Media Bot"
        )

        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.title_label.setStyleSheet(
            "font-size: 24px; "
            "font-weight: bold;"
        )

        main_layout.addWidget(
            self.title_label
        )

        self.bot_status_label = QLabel(
            "Бот: 🔴 Остановлен"
        )

        self.watchdog_status_label = QLabel(
            "Watchdog: 🔴 Остановлен"
        )

        self.uptime_label = QLabel(
            "Uptime: 00:00:00"
        )

        main_layout.addWidget(
            self.bot_status_label
        )

        main_layout.addWidget(
            self.watchdog_status_label
        )

        main_layout.addWidget(
            self.uptime_label
        )

        self.start_button = QPushButton(
            "СТАРТ"
        )

        self.stop_button = QPushButton(
            "СТОП"
        )

        self.stop_button.setEnabled(
            False
        )

        main_layout.addWidget(
            self.start_button
        )

        main_layout.addWidget(
            self.stop_button
        )

        stats_group = QGroupBox(
            "Статистика"
        )

        stats_layout = QGridLayout(
            stats_group
        )

        self.total_downloads_label = QLabel("0")
        self.youtube_downloads_label = QLabel("0")
        self.instagram_downloads_label = QLabel("0")
        self.video_downloads_label = QLabel("0")
        self.audio_downloads_label = QLabel("0")
        self.failed_downloads_label = QLabel("0")
        self.total_bytes_label = QLabel("0 B")

        stats_layout.addWidget(
            QLabel("Всего загрузок:"),
            0,
            0,
        )

        stats_layout.addWidget(
            self.total_downloads_label,
            0,
            1,
        )

        stats_layout.addWidget(
            QLabel("YouTube:"),
            1,
            0,
        )

        stats_layout.addWidget(
            self.youtube_downloads_label,
            1,
            1,
        )

        stats_layout.addWidget(
            QLabel("Instagram:"),
            2,
            0,
        )

        stats_layout.addWidget(
            self.instagram_downloads_label,
            2,
            1,
        )

        stats_layout.addWidget(
            QLabel("Видео:"),
            0,
            2,
        )

        stats_layout.addWidget(
            self.video_downloads_label,
            0,
            3,
        )

        stats_layout.addWidget(
            QLabel("Аудио:"),
            1,
            2,
        )

        stats_layout.addWidget(
            self.audio_downloads_label,
            1,
            3,
        )

        stats_layout.addWidget(
            QLabel("Ошибок:"),
            2,
            2,
        )

        stats_layout.addWidget(
            self.failed_downloads_label,
            2,
            3,
        )

        stats_layout.addWidget(
            QLabel("Отправлено данных:"),
            3,
            0,
        )

        stats_layout.addWidget(
            self.total_bytes_label,
            3,
            1,
            1,
            3,
        )

        main_layout.addWidget(
            stats_group
        )

        logs_group = QGroupBox(
            "Логи"
        )

        logs_layout = QVBoxLayout(
            logs_group
        )

        self.log_output = QTextEdit()

        self.log_output.setReadOnly(
            True
        )

        self.log_output.setPlaceholderText(
            "Здесь будут логи..."
        )

        logs_layout.addWidget(
            self.log_output
        )

        main_layout.addWidget(
            logs_group
        )

        self.start_button.clicked.connect(
            self.start_bot
        )

        self.stop_button.clicked.connect(
            self.stop_bot
        )

        self.state_timer = QTimer(
            self
        )

        self.state_timer.setInterval(
            1000
        )

        self.state_timer.timeout.connect(
            self.update_state
        )

        self.state_timer.start()

        self.stats_timer = QTimer(
            self
        )

        self.stats_timer.setInterval(
            2000
        )

        self.stats_timer.timeout.connect(
            self.update_stats
        )

        self.stats_timer.start()

        self.add_log(
            "GUI запущен"
        )

        self.update_stats()

    def add_log(
        self,
        message: str,
    ) -> None:
        timestamp = (
            datetime.now()
            .strftime("%H:%M:%S")
        )

        self.log_output.append(
            f"{timestamp} | {message}"
        )

    def add_process_log(
        self,
        line: str,
    ) -> None:
        self.log_output.append(
            line
        )

        self.log_output.verticalScrollBar().setValue(
            self.log_output
            .verticalScrollBar()
            .maximum()
        )

        lower_line = line.lower()

        if (
            "watchdog запущен"
            in lower_line
        ):
            self.watchdog_status_label.setText(
                "Watchdog: 🟢 Активен"
            )

        if (
            "подключились к telegram"
            in lower_line
            or "run polling for bot"
            in lower_line
        ):
            self.bot_status_label.setText(
                "Бот: 🟢 Запущен"
            )

        if (
            "бот считается зависшим"
            in lower_line
            or "процесс бота завершился"
            in lower_line
        ):
            self.bot_status_label.setText(
                "Бот: 🟡 Перезапуск..."
            )

        if (
            "пауза"
            in lower_line
            and "серией"
            in lower_line
        ):
            self.bot_status_label.setText(
                "Бот: 🟠 Ожидание рестарта"
            )

    def update_stats(
        self,
    ) -> None:
        try:
            stats = stats_storage.get_stats()

        except Exception as error:
            self.add_log(
                "Ошибка чтения статистики: "
                f"{error}"
            )
            return

        self.total_downloads_label.setText(
            str(stats.total_downloads)
        )

        self.youtube_downloads_label.setText(
            str(stats.youtube_downloads)
        )

        self.instagram_downloads_label.setText(
            str(stats.instagram_downloads)
        )

        self.video_downloads_label.setText(
            str(stats.video_downloads)
        )

        self.audio_downloads_label.setText(
            str(stats.audio_downloads)
        )

        self.failed_downloads_label.setText(
            str(stats.failed_downloads)
        )

        self.total_bytes_label.setText(
            format_bytes(
                stats.total_bytes_sent
            )
        )

    def start_bot(
        self,
    ) -> None:
        if (
            self.launcher_process is not None
            and self.launcher_process.poll() is None
        ):
            self.add_log(
                "Launcher уже запущен"
            )
            return

        process_env = os.environ.copy()

        process_env["PYTHONUTF8"] = "1"
        process_env["PYTHONIOENCODING"] = "utf-8"

        creation_flags = 0

        if sys.platform == "win32":
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
            )

        try:
            self.launcher_process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(LAUNCHER_FILE),
                ],
                cwd=str(
                    PROJECT_DIR
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=process_env,
                creationflags=creation_flags,
            )

        except Exception as error:
            self.add_log(
                f"Ошибка запуска: {error}"
            )

            self.bot_status_label.setText(
                "Бот: 🔴 Ошибка запуска"
            )

            self.watchdog_status_label.setText(
                "Watchdog: 🔴 Ошибка запуска"
            )

            return

        self.started_at = datetime.now()

        self.bot_status_label.setText(
            "Бот: 🟡 Запуск..."
        )

        self.watchdog_status_label.setText(
            "Watchdog: 🟡 Запуск..."
        )

        self.start_button.setEnabled(
            False
        )

        self.stop_button.setEnabled(
            True
        )

        self.add_log(
            "Launcher запускается..."
        )

        self.output_thread = ProcessOutputThread(
            self.launcher_process
        )

        self.output_thread.line_received.connect(
            self.add_process_log
        )

        self.output_thread.start()

    def kill_project_processes(
        self,
    ) -> None:
        if sys.platform != "win32":
            return

        command = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.CommandLine -match "
            "'tg_video_bot.*(main\\.py|launcher\\.py)' "
            "} | "
            "ForEach-Object { "
            "Stop-Process -Id $_.ProcessId -Force "
            "}"
        )

        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    command,
                ],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )

        except Exception as error:
            self.add_log(
                "Ошибка очистки процессов: "
                f"{error}"
            )

    def stop_bot(
        self,
    ) -> None:
        self.add_log(
            "Останавливаю бота..."
        )

        if (
            self.launcher_process is not None
            and self.launcher_process.poll() is None
        ):
            try:
                self.launcher_process.terminate()

                self.launcher_process.wait(
                    timeout=5
                )

            except subprocess.TimeoutExpired:
                self.launcher_process.kill()

                self.launcher_process.wait()

            except Exception as error:
                self.add_log(
                    "Ошибка остановки launcher: "
                    f"{error}"
                )

        self.kill_project_processes()

        if self.output_thread is not None:
            self.output_thread.wait(
                2000
            )

            self.output_thread = None

        self.launcher_process = None
        self.started_at = None

        self.bot_status_label.setText(
            "Бот: 🔴 Остановлен"
        )

        self.watchdog_status_label.setText(
            "Watchdog: 🔴 Остановлен"
        )

        self.uptime_label.setText(
            "Uptime: 00:00:00"
        )

        self.start_button.setEnabled(
            True
        )

        self.stop_button.setEnabled(
            False
        )

        self.add_log(
            "Бот и watchdog остановлены"
        )

    def update_state(
        self,
    ) -> None:
        if self.launcher_process is None:
            return

        exit_code = (
            self.launcher_process.poll()
        )

        if exit_code is not None:
            self.add_log(
                "Launcher завершился "
                f"с кодом {exit_code}"
            )

            self.launcher_process = None
            self.started_at = None

            self.bot_status_label.setText(
                "Бот: 🔴 Остановлен"
            )

            self.watchdog_status_label.setText(
                "Watchdog: 🔴 Остановлен"
            )

            self.uptime_label.setText(
                "Uptime: 00:00:00"
            )

            self.start_button.setEnabled(
                True
            )

            self.stop_button.setEnabled(
                False
            )

            return

        if self.started_at is None:
            return

        elapsed = (
            datetime.now()
            - self.started_at
        )

        total_seconds = int(
            elapsed.total_seconds()
        )

        hours = (
            total_seconds
            // 3600
        )

        minutes = (
            total_seconds
            % 3600
            // 60
        )

        seconds = (
            total_seconds
            % 60
        )

        self.uptime_label.setText(
            "Uptime: "
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    def closeEvent(
        self,
        event,
    ) -> None:
        self.stop_bot()

        event.accept()


def main() -> None:
    app = QApplication(
        sys.argv
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()