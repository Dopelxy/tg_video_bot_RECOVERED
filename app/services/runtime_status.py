"""Small status snapshots shared by the bot and its local control agent."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STATUS_FILE = DATA_DIR / "bot_status.json"
HEARTBEAT_FILE = DATA_DIR / "bot_heartbeat.txt"
MAX_STATUS_AGE_SECONDS = 90


def publish_status(instance_id: str, *, reachable: bool, username: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "instance_id": instance_id,
        "telegram_reachable": reachable,
        "username": username,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = STATUS_FILE.with_name(f".bot_status.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS_FILE)


def clear_status(instance_id: str) -> None:
    try:
        payload = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if payload.get("instance_id") == instance_id:
            STATUS_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def record_probe_result(*, reachable: bool, username: str) -> bool:
    """Update the active bot's snapshot after a manual API check."""
    try:
        heartbeat = HEARTBEAT_FILE.read_text(encoding="utf-8").split()
        if len(heartbeat) < 2:
            return False
        if not 0 <= time.time() - HEARTBEAT_FILE.stat().st_mtime <= MAX_STATUS_AGE_SECONDS:
            return False
        instance_id = heartbeat[0]
        snapshot = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if snapshot.get("instance_id") != instance_id:
            return False
        publish_status(instance_id, reachable=reachable, username=username)
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def read_telegram_status(*, launcher_running: bool) -> dict:
    result = {"telegram_api": "unknown", "bot_username": None}
    if not launcher_running:
        return result
    try:
        snapshot = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        heartbeat = HEARTBEAT_FILE.read_text(encoding="utf-8").split()
        now = time.time()
        status_age = now - STATUS_FILE.stat().st_mtime
        heartbeat_age = now - HEARTBEAT_FILE.stat().st_mtime
        if (
            len(heartbeat) < 2
            or snapshot.get("instance_id") != heartbeat[0]
            or not 0 <= status_age <= MAX_STATUS_AGE_SECONDS
            or not 0 <= heartbeat_age <= MAX_STATUS_AGE_SECONDS
        ):
            return result
        state = snapshot.get("telegram_reachable")
        if state is True:
            result["telegram_api"] = "reachable"
        elif state is False:
            result["telegram_api"] = "unreachable"
        result["bot_username"] = snapshot.get("username")
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return result
