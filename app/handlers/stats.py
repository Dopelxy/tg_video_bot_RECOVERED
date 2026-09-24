from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.storage.stats import stats_storage


router = Router()


def format_bytes(
    size_bytes: int,
) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} Б"

    size_kb = size_bytes / 1024

    if size_kb < 1024:
        return f"{size_kb:.2f} КБ"

    size_mb = size_kb / 1024

    if size_mb < 1024:
        return f"{size_mb:.2f} МБ"

    size_gb = size_mb / 1024

    return f"{size_gb:.2f} ГБ"


@router.message(Command("stats"))
async def stats_handler(
    message: Message,
) -> None:
    stats = stats_storage.get_stats()

    response = (
        "📊 Статистика бота\n\n"
        f"Всего загрузок: {stats.total_downloads}\n"
        f"🎬 Видео: {stats.video_downloads}\n"
        f"🎵 Аудио: {stats.audio_downloads}\n"
        f"❌ Ошибок: {stats.failed_downloads}\n"
        f"📦 Передано: "
        f"{format_bytes(stats.total_bytes_sent)}"
    )

    await message.answer(
        response
    )