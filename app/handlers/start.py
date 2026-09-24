from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)


router = Router()


start_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="СТАРТ"
            )
        ]
    ],
    resize_keyboard=True,
)


async def show_start_screen(
    message: Message,
) -> None:
    await message.answer(
        "🎬 Отправь мне ссылку на видео с YouTube "
        "или Instagram Reels.\n\n"
        "Для YouTube я покажу доступные варианты качества, "
        "а Instagram Reel скачаю и подготовлю к отправке.",
        reply_markup=start_keyboard,
    )


@router.message(CommandStart())
async def start_handler(
    message: Message,
) -> None:
    await show_start_screen(
        message
    )


@router.message(F.text.contains("СТАРТ"))
async def start_button_handler(
    message: Message,
) -> None:
    await show_start_screen(
        message
    )