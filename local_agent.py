"""Local control process for the bot. Pilot stage; desktop integration follows.

Run `python local_agent.py serve` in one terminal and issue commands from
another terminal. The agent uses a loopback-only authenticated connection.
"""

import argparse
import asyncio
import os
import secrets
import sys
from datetime import datetime, timezone
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path

from app.services.bot_process import BotProcess
from app.services.runtime_status import read_telegram_status, record_probe_result


ADDRESS = ("127.0.0.1", 47631)
AUTH_FILE_NAME = "agent_auth.key"


async def _check_telegram_api() -> tuple[bool, str | None]:
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from app.config.app_settings import settings

    bot = Bot(token=settings.bot_token, session=AiohttpSession(proxy=settings.proxy_url))
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=10)
        return True, me.username
    finally:
        await bot.session.close()


def probe_telegram(runtime: BotProcess) -> dict:
    pid = runtime.pid
    result = {"ok": True, "launcher_pid": pid,
              "checked_at": datetime.now().strftime("%H:%M:%S")}
    if pid is None:
        result.update(telegram_api="unknown", bot_username=None)
        return result
    try:
        reachable, username = asyncio.run(_check_telegram_api())
    except Exception:
        reachable, username = False, None
    current = read_telegram_status(launcher_running=True)
    username = username or current.get("bot_username") or ""
    record_probe_result(reachable=reachable, username=username)
    result.update(telegram_api="reachable" if reachable else "unreachable",
                  bot_username=username or None)
    return result


def _auth_path(project_dir: Path) -> Path:
    return project_dir / "data" / AUTH_FILE_NAME


def _load_authkey(project_dir: Path, *, create: bool) -> bytes:
    path = _auth_path(project_dir)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as f:
                    f.write(secrets.token_bytes(32))
        if sys.platform != "win32":
            path.chmod(0o600)
    key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Ключ управления повреждён")
    return key


def request(project_dir: Path, command: str) -> dict:
    """Connect from a CLI or a future desktop window."""
    with Client(ADDRESS, authkey=_load_authkey(project_dir, create=False)) as conn:
        conn.send(command)
        response = conn.recv()
    if not isinstance(response, dict):
        raise RuntimeError("Некорректный ответ службы")
    return response


def serve(project_dir: Path) -> None:
    key = _load_authkey(project_dir, create=True)
    runtime = BotProcess(project_dir)
    with Listener(ADDRESS, authkey=key) as listener:
        print("Служба управления запущена на этом ПК", flush=True)
        try:
            while True:
                try:
                    conn = listener.accept()
                except (OSError, EOFError, AuthenticationError):
                    continue
                with conn:
                    try:
                        command = conn.recv()
                        if command == "status":
                            response = {"ok": True, "launcher_pid": runtime.pid}
                            response.update(
                                read_telegram_status(launcher_running=runtime.pid is not None)
                            )
                        elif command == "probe":
                            response = probe_telegram(runtime)
                        elif command == "start":
                            response = {"ok": True, "launcher_pid": runtime.start()}
                        elif command == "stop":
                            response = {"ok": runtime.stop(), "launcher_pid": runtime.pid}
                        elif command == "shutdown":
                            stopped = runtime.stop()
                            response = {"ok": stopped, "launcher_pid": runtime.pid}
                        else:
                            response = {"ok": False, "error": "Неизвестная команда"}
                        conn.send(response)
                        if command == "shutdown" and response["ok"]:
                            return
                    except (EOFError, BrokenPipeError):
                        continue
                    except Exception as error:
                        try:
                            conn.send({"ok": False, "error": str(error)})
                        except (EOFError, BrokenPipeError):
                            pass
        finally:
            if not runtime.stop():
                print("Не удалось подтвердить остановку бота", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("serve", "status", "probe", "start", "stop", "shutdown"))
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    try:
        if args.command == "serve":
            serve(project_dir)
            return 0
        result = request(project_dir, args.command)
        if result["ok"]:
            if args.command == "probe":
                state = result["telegram_api"]
                print("Telegram API: " + {"reachable": "доступен", "unreachable": "нет ответа",
                                          "unknown": "бот остановлен"}[state])
                print(f"Проверено: {result['checked_at']}")
                return 0
            print("Бот запущен" if result["launcher_pid"] else "Бот остановлен")
            if result["launcher_pid"]:
                print(f"Launcher PID: {result['launcher_pid']}")
            return 0
        print(result.get("error") or "Остановку не удалось подтвердить", file=sys.stderr)
        return 1
    except (OSError, EOFError, ConnectionError) as error:
        print(f"Нет связи со службой управления: {error}", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
