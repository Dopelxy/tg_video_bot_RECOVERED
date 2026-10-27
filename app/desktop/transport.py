"""Desktop transports. Demo is independent of client, auth files and services."""
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from app.paths import PROJECT_DIR
from app.desktop.agent_call import MESSAGES
from app.services.process_tree import entry_command, popen_owned, stop_owned

CALL_TIMEOUT = 45
LOG_LIMIT = 150


class TransportFault(Exception):
    def __init__(self, kind, message=None):
        self.kind = kind if kind in MESSAGES else "connection"
        super().__init__(message or MESSAGES[self.kind])


def tail(path):
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 65536))
            return [line[:1000] for line in handle.read().decode("utf-8", errors="replace").splitlines()[-LOG_LIMIT:]]
    except OSError:
        return []


class AgentTransport:
    demo = False

    def __init__(self, project_dir=PROJECT_DIR):
        self.project_dir = Path(project_dir)
        self.agent_process = None

    def request(self, command):
        process = job = None
        try:
            environment = os.environ.copy()
            environment["MEDIA_BOT_AGENT_COMMAND"] = command
            process, job = popen_owned(
                entry_command(module="app.desktop.agent_call"), cwd=self.project_dir,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
            )
            process.stdin = None  # the launch gate has already closed this pipe
            output, _ = process.communicate(timeout=CALL_TIMEOUT - 5)
            if process.returncode:
                raise ValueError()
            envelope = json.loads(output)
            if not isinstance(envelope, dict) or type(envelope.get("ok")) is not bool:
                raise ValueError()
        except subprocess.TimeoutExpired:
            raise TransportFault("timeout") from None
        except (OSError, subprocess.SubprocessError, ValueError):
            raise TransportFault("protocol") from None
        finally:
            if process is not None:
                stop_owned(process, job, timeout=5)
        if not envelope["ok"]:
            raise TransportFault(envelope.get("kind", "connection"))
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise TransportFault("protocol")
        return payload

    def ensure_agent(self):
        # Repeat the absence check in this worker immediately before spawning,
        # since another UI might have started the service in the meantime.
        try:
            self.request("status")
            return {"spawned": False}
        except TransportFault as error:
            if error.kind != "absent":
                raise
        folder = self.project_dir / "data"
        folder.mkdir(parents=True, exist_ok=True)
        options = ({"creationflags": subprocess.DETACHED_PROCESS} if sys.platform == "win32"
                   else {"start_new_session": True})
        with (folder / "agent.log").open("ab", buffering=0) as log:
            self.agent_process = subprocess.Popen(
                [sys.executable, "-B", "-X", "utf8", "-u", str(self.project_dir / "local_agent.py"), "serve"],
                cwd=self.project_dir, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options,
            )
        return {"spawned": True}

    def read_log(self):
        return tail(self.project_dir / "data" / "runtime.log")


class DemoTransport:
    demo = True

    def __init__(self, scenario="running", delay=0.12):
        self.scenario = scenario
        self.delay = delay
        self.running = scenario != "stopped"
        self.calls = []
        self.temporary = tempfile.TemporaryDirectory(prefix="media_bot_qml_demo_")
        self.log_path = Path(self.temporary.name) / "demo.log"
        self.log_path.write_text(
            "ТЕСТОВЫЕ ДАННЫЕ · настоящий Agent не используется\n"
            "10:42:01 · Демонстрационный транспорт готов\n"
            "10:42:02 · Получено состояние локальной цепочки\n"
            "10:42:03 · Журнал ограничен 200 строками\n", encoding="utf-8")

    def request(self, command):
        self.calls.append(command)
        time.sleep(1.8 if self.scenario == "busy" and command != "status" else self.delay)
        if self.scenario == "disconnected" and len(self.calls) > 1:
            raise TransportFault("connection")
        if self.scenario == "error" and command != "status":
            return {"ok": False, "error": "Тестовая ошибка: Agent не подтвердил выполнение команды."}
        if command == "start":
            self.running = True
        if command in {"stop", "shutdown"}:
            self.running = False
        result = {"ok": True, "launcher_pid": 4242 if self.running else None}
        if command in {"status", "probe"}:
            result.update(telegram_api="reachable" if self.running else "unknown",
                          bot_username="media_demo_bot" if self.running else None)
        if command == "probe":
            result["checked_at"] = "10:42:05"
        return result

    def ensure_agent(self):
        raise AssertionError("Demo must never start a service")

    def read_log(self):
        return tail(self.log_path)

    def close(self):
        self.temporary.cleanup()
