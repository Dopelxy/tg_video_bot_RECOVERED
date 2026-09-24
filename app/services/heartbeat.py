import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config.app_settings import settings


logger = logging.getLogger(__name__)


HEARTBEAT_DIR = Path("data")
HEARTBEAT_FILE = (
    HEARTBEAT_DIR
    / "bot_heartbeat.txt"
)


def write_heartbeat() -> None:
    HEARTBEAT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    HEARTBEAT_FILE.write_text(
        timestamp,
        encoding="utf-8",
    )


async def heartbeat_loop() -> None:
    logger.info(
        "Heartbeat запущен"
    )

    while True:
        try:
            write_heartbeat()

        except Exception:
            logger.exception(
                "Не удалось обновить heartbeat"
            )

        await asyncio.sleep(
            settings.heartbeat_interval_seconds
        )