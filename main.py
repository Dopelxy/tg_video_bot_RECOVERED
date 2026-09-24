import asyncio

from aiogram import Dispatcher

from app.bot.runner import run_bot
from app.handlers.instagram import router as instagram_router
from app.handlers.start import router as start_router
from app.handlers.youtube import router as youtube_router


async def main() -> None:
    dispatcher = Dispatcher()

    dispatcher.include_router(start_router)

    # Instagram ставим раньше общего
    # YouTube text-handler.
    dispatcher.include_router(instagram_router)
    dispatcher.include_router(youtube_router)

    await run_bot(dispatcher)


if __name__ == "__main__":
    asyncio.run(main())