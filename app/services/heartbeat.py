import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from app.config.app_settings import settings
from app.services.runtime_status import DATA_DIR, HEARTBEAT_FILE, publish_status


logger = logging.getLogger(__name__)


def write_heartbeat(instance_id: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    HEARTBEAT_FILE.write_text(f"{instance_id} {timestamp}", encoding="utf-8")


async def heartbeat_loop(bot: Bot, instance_id: str, username: str) -> None:
    logger.info("Heartbeat запущен")
    while True:
        try:
            write_heartbeat(instance_id)
        except Exception:
            logger.exception("Не удалось обновить heartbeat")

        await asyncio.sleep(settings.heartbeat_interval_seconds)
        try:
            await asyncio.wait_for(bot.get_me(), timeout=10)
            reachable = True
        except Exception:
            reachable = False
            logger.warning("Проверка связи с Telegram не прошла")

        try:
            publish_status(instance_id, reachable=reachable, username=username)
        except Exception:
            logger.exception("Не удалось обновить состояние Telegram")
