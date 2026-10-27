"""Test-only guards: no dotenv, production data, keys, network or live services."""
from pathlib import Path
import sys
import socket
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
settings_module = ModuleType("app.config.app_settings")
settings_module.settings = SimpleNamespace(
    bot_token="123456:TEST_ONLY_NOT_A_REAL_TOKEN", proxy_url=None,
    max_file_size_mb=49, max_video_duration_seconds=1800, max_concurrent_downloads=2,
    heartbeat_interval_seconds=30, heartbeat_timeout_seconds=300,
    restart_delay_seconds=3, max_restarts=5, restart_window_seconds=600,
)
sys.modules["app.config.app_settings"] = settings_module


def guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        # Windows asyncio uses stdlib socketpair for its private wakeup channel.
        # Permit only that exact stdlib implementation, never a service connection.
        fallback = getattr(socket, "_fallback_socketpair", None)
        if event == "socket.connect" and fallback and sys._getframe(1).f_code is fallback.__code__:
            return
        raise RuntimeError("Network forbidden in offline tests")
    if event == "open":
        raw, mode, flags = args
        if isinstance(raw, (str, bytes)):
            path = Path(raw).resolve()
            if path.name.startswith(".env") or path.suffix == ".key":
                raise RuntimeError("Secret access forbidden")
            writing = (isinstance(mode, str) and any(c in mode for c in "wa+")) or (
                isinstance(flags, int) and flags & (0x1 | 0x2 | 0x40 | 0x200))
            if writing and any(path.is_relative_to(ROOT / folder) for folder in ("data", "temp_downloads")):
                raise RuntimeError("Production data write forbidden")


sys.addaudithook(guard)
