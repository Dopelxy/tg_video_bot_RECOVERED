import logging

from aiogram import Bot

from app.models.bot_identity import BotIdentity


logger = logging.getLogger(__name__)


async def load_bot_identity(
    bot: Bot,
) -> BotIdentity:
    try:
        bot_info = await bot.get_me()

        name = (
            bot_info.first_name
            or "Telegram Bot"
        )

        username = (
            bot_info.username
            or "telegram_bot"
        )

        return BotIdentity(
            name=name,
            username=username,
        )

    except Exception:
        logger.exception(
            "Не удалось получить информацию о боте"
        )

        return BotIdentity(
            name="Telegram Bot",
            username="telegram_bot",
        )
    