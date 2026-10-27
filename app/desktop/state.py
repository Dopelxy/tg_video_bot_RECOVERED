"""Presentation state for the existing Agent contract. No Qt, I/O or secrets."""
from dataclasses import dataclass
from datetime import datetime


def label(value, limit=240):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


@dataclass
class OverviewState:
    agent: str = "unknown"
    has_snapshot: bool = False
    launcher_pid: int | None = None
    username: str = ""
    telegram: str = "unknown"
    received_at: datetime | None = None
    stale: bool = True
    error: str = ""
    checked_at: str = ""

    def accept(self, payload, command, now=None):
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ValueError("Некорректный ответ Agent")
        self.agent = "connected"
        if payload["ok"] is False:
            self.error = label(payload.get("error")) or "Agent не подтвердил выполнение команды."
            return False
        if "launcher_pid" not in payload:
            raise ValueError("В ответе Agent нет состояния процесса")
        pid = payload["launcher_pid"]
        if pid is not None and (type(pid) is not int or pid <= 0):
            raise ValueError("Некорректное состояние процесса")
        if not self.has_snapshot or pid != self.launcher_pid:
            self.telegram = "unknown"
        self.launcher_pid = pid
        self.has_snapshot = True
        if pid is None:
            self.telegram = "unknown"
        elif "telegram_api" in payload:
            value = payload["telegram_api"]
            self.telegram = value if value in {"reachable", "unreachable", "unknown"} else "unknown"
        username = label(payload.get("bot_username"), 64).lstrip("@")
        if username:
            self.username = username
        self.received_at = now or datetime.now().astimezone()
        self.checked_at = label(payload.get("checked_at"), 32) or self.checked_at
        self.stale = False
        self.error = ""
        return True

    def disconnect(self, message):
        self.agent = "disconnected"
        self.stale = True
        self.error = message

    @property
    def display_name(self):
        # There is no bot-name field in the current contract.
        return "@" + self.username if self.username else "Telegram-бот"

    @property
    def process_text(self):
        if not self.has_snapshot:
            return "Нет данных"
        value = "Launcher запущен" if self.launcher_pid is not None else "Остановлен"
        return "Последнее: " + value if self.stale else value

    @property
    def telegram_text(self):
        value = {"reachable": "Доступен", "unreachable": "Нет ответа", "unknown": "Не проверено"}[self.telegram]
        return "Последнее: " + value if self.stale and self.has_snapshot else value
