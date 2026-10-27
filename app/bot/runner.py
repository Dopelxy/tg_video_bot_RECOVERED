import asyncio
import logging
import uuid

from aiogram import (
    Bot,
    Dispatcher,
)
from aiogram.client.session.aiohttp import (
    AiohttpSession,
)

from app.config.app_settings import settings
from app.services.heartbeat import heartbeat_loop
from app.services.runtime_status import publish_status, clear_status


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(
    __name__
)


async def run_bot(
    dispatcher: Dispatcher,
) -> None:
    session = AiohttpSession(
        proxy=settings.proxy_url, timeout=600
    )

    bot = Bot(
        token=settings.bot_token,
        session=session,
    )

    heartbeat_task: (
        asyncio.Task | None
    ) = None
    instance_id = uuid.uuid4().hex

    try:
        me = await asyncio.wait_for(bot.me(), timeout=15)

        print(
            "Подключились к Telegram "
            f"как @{me.username}"
        )

        print(
            "Polling запущен. "
            "Жду сообщения..."
        )

        publish_status(
            instance_id,
            reachable=True,
            username=me.username or "",
        )
        heartbeat_task = (
            asyncio.create_task(
                heartbeat_loop(bot, instance_id, me.username or "")
            )
        )

        await dispatcher.start_polling(
            bot, tasks_concurrency_limit=32
        )

    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()

            try:
                await heartbeat_task

            except asyncio.CancelledError:
                pass

        clear_status(instance_id)
        await bot.session.close()
