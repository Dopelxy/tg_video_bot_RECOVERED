import asyncio
import sys

from aiogram import Dispatcher

from app.bot.runner import run_bot
from app.config.app_settings import settings
from app.services.instance_lock import token_instance, InstanceBusy
from app.handlers.instagram import router as instagram_router
from app.handlers.start import router as start_router
from app.handlers.youtube import router as youtube_router


async def main() -> None:
    with token_instance(settings.bot_token):
        dispatcher = Dispatcher()

        dispatcher.include_router(start_router)

        # Instagram ставим раньше общего
        # YouTube text-handler.
        dispatcher.include_router(instagram_router)
        dispatcher.include_router(youtube_router)

        await run_bot(dispatcher)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except InstanceBusy as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(78)
