import asyncio
import logging

from aiogram import (
    Bot,
    Dispatcher,
)
from aiogram.client.session.aiohttp import (
    AiohttpSession,
)

from app.config.app_settings import settings
from app.services.heartbeat import heartbeat_loop


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
        proxy=settings.proxy_url
    )

    bot = Bot(
        token=settings.bot_token,
        session=session,
    )

    heartbeat_task: (
        asyncio.Task | None
    ) = None

    try:
        me = await bot.get_me()

        print(
            "Подключились к Telegram "
            f"как @{me.username}"
        )

        print(
            "Polling запущен. "
            "Жду сообщения..."
        )

        heartbeat_task = (
            asyncio.create_task(
                heartbeat_loop()
            )
        )

        await dispatcher.start_polling(
            bot
        )

    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()

            try:
                await heartbeat_task

            except asyncio.CancelledError:
                pass

        await bot.session.close()