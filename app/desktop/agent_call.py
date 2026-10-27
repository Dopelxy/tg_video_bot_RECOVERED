"""One bounded helper call to the existing client; never starts Agent or bot."""
import errno
import json
import os
import socket
import sys

from app.paths import PROJECT_DIR

MESSAGES = {
    "absent": "Служба Agent не запущена.",
    "timeout": "Agent не ответил вовремя. Повторный запуск службы не выполнялся.",
    "auth": "Не удалось подтвердить доступ к Agent. Проверь локальную службу.",
    "connection": "Нет связи с Agent. Последние данные сохранены.",
    "protocol": "Agent вернул некорректный ответ.",
}


def refused(error):
    return isinstance(error, ConnectionRefusedError) or getattr(error, "winerror", None) == 10061 or getattr(error, "errno", None) == errno.ECONNREFUSED


def perform(command, *, request_fn=None, connect_fn=None):
    from local_agent import request, ADDRESS
    request_fn = request_fn or request
    connect_fn = connect_fn or socket.create_connection
    try:
        if command not in {"status", "start", "stop", "probe", "shutdown"}:
            raise ValueError()
        payload = request_fn(PROJECT_DIR, command)
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ValueError()
        return {"ok": True, "payload": payload}
    except FileNotFoundError:
        # A missing key alone does not establish absence. Confirm a refused
        # loopback connection; an open socket means a service may already exist.
        try:
            with connect_fn(ADDRESS, timeout=1):
                pass
            kind = "auth"
        except OSError as error:
            kind = "absent" if refused(error) else "timeout" if isinstance(error, TimeoutError) else "connection"
    except TimeoutError:
        kind = "timeout"
    except OSError as error:
        kind = "absent" if refused(error) else "auth" if str(error) == "IPC authentication failed" else "connection"
    except (EOFError, RuntimeError):
        kind = "auth"
    except Exception:
        kind = "protocol"
    return {"ok": False, "kind": kind, "message": MESSAGES[kind]}


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) == 2 else os.environ.get("MEDIA_BOT_AGENT_COMMAND", "invalid")
    print(json.dumps(perform(command), ensure_ascii=True), flush=True)
