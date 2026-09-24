import logging
import shutil
import uuid
from pathlib import Path

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config.app_settings import settings
from app.downloaders.youtube import (
    UnsupportedUrlError,
    YouTubeDownloader,
    YouTubeDurationLimitError,
    YouTubeFileSizeLimitError,
    YouTubeMetadataError,
)
from app.services.bot_identity import load_bot_identity
from app.services.download_coordinator import download_coordinator
from app.services.progress import DownloadProgress
from app.services.telegram_progress import (
    TelegramProgressUpdater,
)
from app.storage.stats import stats_storage


router = Router()
logger = logging.getLogger(__name__)

youtube_downloader = YouTubeDownloader()

TEMP_ROOT = Path("temp_downloads")


youtube_requests: dict[
    str,
    dict[str, str | int],
] = {}


def format_duration(
    seconds: int | None,
) -> str:
    if seconds is None:
        return "неизвестно"

    minutes, secs = divmod(
        seconds,
        60,
    )

    hours, minutes = divmod(
        minutes,
        60,
    )

    if hours:
        return (
            f"{hours}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    return (
        f"{minutes}:"
        f"{secs:02d}"
    )


def get_duration_limit_minutes() -> int:
    return (
        settings.max_video_duration_seconds
        // 60
    )


def create_request_id() -> str:
    return uuid.uuid4().hex[:12]


def build_quality_keyboard(
    available_heights: set[int],
    request_id: str,
) -> InlineKeyboardMarkup:
    buttons: list[
        list[InlineKeyboardButton]
    ] = []

    for height in (
        360,
        720,
        1080,
    ):
        if height not in available_heights:
            continue

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🎬 {height}p",
                    callback_data=(
                        f"ytq:"
                        f"{request_id}:"
                        f"{height}"
                    ),
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🎵 Audio",
                callback_data=(
                    f"yta:{request_id}"
                ),
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons,
    )


def get_request(
    request_id: str,
    user_id: int,
) -> dict[str, str | int] | None:
    request_data = youtube_requests.get(
        request_id
    )

    if request_data is None:
        return None

    owner_user_id = request_data.get(
        "user_id"
    )

    if owner_user_id != user_id:
        return None

    return request_data


@router.message(F.text)
async def youtube_link_handler(
    message: Message,
) -> None:
    url = message.text.strip()

    if not youtube_downloader.supports_url(
        url
    ):
        return

    if message.from_user is None:
        return

    status_message = await message.answer(
        "Ссылка получена. "
        "Получаю информацию…"
    )

    try:
        metadata = (
            await youtube_downloader.get_metadata(
                url
            )
        )

        formats = (
            await youtube_downloader.get_formats(
                url
            )
        )

        request_id = create_request_id()

        youtube_requests[request_id] = {
            "user_id": message.from_user.id,
            "url": url,
            "title": metadata.title,
            "uploader": (
                metadata.uploader
                or "неизвестен"
            ),
        }

        available_heights = {
            media_format.height
            for media_format in formats
        }

        keyboard = build_quality_keyboard(
            available_heights=available_heights,
            request_id=request_id,
        )

        uploader = (
            metadata.uploader
            or "неизвестен"
        )

        response = (
            "🎬 YouTube\n\n"
            f"Название: "
            f"{metadata.title}\n"
            f"Автор: "
            f"{uploader}\n"
            f"Длительность: "
            f"{format_duration(metadata.duration)}"
            "\n\n"
            "Выбери качество:"
        )

        await status_message.edit_text(
            response,
            reply_markup=keyboard,
        )

    except UnsupportedUrlError:
        await status_message.edit_text(
            "❌ Эта ссылка "
            "не поддерживается."
        )

    except YouTubeDurationLimitError:
        await status_message.edit_text(
            "❌ Видео слишком длинное."
            "\n\n"
            "Максимальная длительность: "
            f"{get_duration_limit_minutes()} "
            "минут."
        )

    except YouTubeMetadataError:
        await status_message.edit_text(
            "❌ Не удалось получить "
            "информацию о видео."
        )

    except Exception:
        logger.exception(
            "Неожиданная ошибка "
            "при получении метаданных YouTube"
        )

        await status_message.edit_text(
            "❌ Произошла "
            "внутренняя ошибка."
        )


@router.callback_query(
    F.data.startswith("ytq:")
)
async def youtube_quality_handler(
    callback: CallbackQuery,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    await callback.answer()

    callback_data = callback.data

    if callback_data is None:
        return

    try:
        _, request_id, height_text = (
            callback_data.split(
                ":",
                maxsplit=2,
            )
        )

        height = int(
            height_text
        )

    except (
        ValueError,
        IndexError,
    ):
        await callback.message.answer(
            "❌ Не удалось определить "
            "выбранное качество."
        )
        return

    if height not in {
        360,
        720,
        1080,
    }:
        await callback.message.answer(
            "❌ Такое качество "
            "не поддерживается."
        )
        return

    user_id = callback.from_user.id

    request_data = get_request(
        request_id=request_id,
        user_id=user_id,
    )

    if request_data is None:
        await callback.message.answer(
            "❌ Эта карточка уже "
            "недоступна.\n"
            "Отправь ссылку боту "
            "ещё раз."
        )
        return

    url = str(
        request_data["url"]
    )

    title = str(
        request_data["title"]
    )

    bot_identity = await load_bot_identity(
        callback.bot
    )

    job_id = uuid.uuid4().hex

    output_dir = (
        TEMP_ROOT
        / str(user_id)
        / job_id
    )

    progress = DownloadProgress()

    status_message = (
        await callback.message.answer(
            "⏳ Подготавливаю загрузку…"
        )
    )

    progress_updater = (
        TelegramProgressUpdater(
            message=status_message,
            progress=progress,
            title=title,
            format_name=(
                f"{height}p • MP4"
            ),
            bot_identity=bot_identity,
        )
    )

    if not download_coordinator.claim_user(user_id):
        await status_message.edit_text(
            "⏳ У тебя уже идёт загрузка. "
            "Дождись её завершения."
        )
        return

    try:
        progress_updater.start()
        async with download_coordinator.download_semaphore:
            video_path = (
                await youtube_downloader.download_video(
                    url=url,
                    max_height=height,
                    output_dir=output_dir,
                    progress=progress,
                )
            )

        file_size = (
            video_path.stat().st_size
        )

        progress.set_uploading(
            "Файл готов. "
            "Отправляю в Telegram…"
        )

        video_file = FSInputFile(
            video_path
        )

        await callback.message.answer_video(
            video=video_file,
            caption=(
                f"🎬 {title}\n"
                f"📺 Качество: {height}p\n"
                "\n"
                f"◆ {bot_identity.name}\n"
                f"{bot_identity.username_with_at}"
            ),
        )

        stats_storage.record_video_download(
            file_size=file_size
        )

        progress.set_complete(
            "Загрузка завершена"
        )

        await progress_updater.stop(
            file_size=file_size,
            show_complete=True,
        )

    except YouTubeDurationLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Видео слишком длинное"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Видео слишком длинное."
            "\n\n"
            "Максимальная длительность: "
            f"{get_duration_limit_minutes()} "
            "минут."
        )

    except YouTubeFileSizeLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Файл слишком большой"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Файл получился "
            "слишком большим."
            "\n\n"
            "Максимальный размер: "
            f"{settings.max_file_size_mb} МБ."
        )

    except YouTubeMetadataError:
        stats_storage.record_failure()

        progress.set_failed(
            "Не удалось скачать видео"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Не удалось "
            "скачать видео."
        )

    except Exception:
        stats_storage.record_failure()

        progress.set_failed(
            "Внутренняя ошибка"
        )

        await progress_updater.stop()

        logger.exception(
            "Неожиданная ошибка "
            "при скачивании YouTube-видео"
        )

        await status_message.edit_text(
            "❌ Произошла "
            "внутренняя ошибка "
            "при обработке видео."
        )

    finally:
        await progress_updater.stop()

        download_coordinator.release_user(user_id)

        shutil.rmtree(
            output_dir,
            ignore_errors=True,
        )


@router.callback_query(
    F.data.startswith("yta:")
)
async def youtube_audio_handler(
    callback: CallbackQuery,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    await callback.answer()

    callback_data = callback.data

    if callback_data is None:
        return

    try:
        _, request_id = (
            callback_data.split(
                ":",
                maxsplit=1,
            )
        )

    except (
        ValueError,
        IndexError,
    ):
        await callback.message.answer(
            "❌ Не удалось определить "
            "аудиозапрос."
        )
        return

    user_id = callback.from_user.id

    request_data = get_request(
        request_id=request_id,
        user_id=user_id,
    )

    if request_data is None:
        await callback.message.answer(
            "❌ Эта карточка уже "
            "недоступна.\n"
            "Отправь ссылку боту "
            "ещё раз."
        )
        return

    url = str(
        request_data["url"]
    )

    title = str(
        request_data["title"]
    )

    uploader = str(
        request_data["uploader"]
    )

    bot_identity = await load_bot_identity(
        callback.bot
    )

    job_id = uuid.uuid4().hex

    output_dir = (
        TEMP_ROOT
        / str(user_id)
        / job_id
    )

    progress = DownloadProgress()

    status_message = (
        await callback.message.answer(
            "⏳ Подготавливаю аудио…"
        )
    )

    progress_updater = (
        TelegramProgressUpdater(
            message=status_message,
            progress=progress,
            title=title,
            format_name="MP3 • 192 kbps",
            bot_identity=bot_identity,
        )
    )

    if not download_coordinator.claim_user(user_id):
        await status_message.edit_text(
            "⏳ У тебя уже идёт загрузка. "
            "Дождись её завершения."
        )
        return

    try:
        progress_updater.start()
        async with download_coordinator.download_semaphore:
            audio_path = (
                await youtube_downloader.download_audio(
                    url=url,
                    output_dir=output_dir,
                    progress=progress,
                )
            )

        file_size = (
            audio_path.stat().st_size
        )

        progress.set_uploading(
            "Аудио готово. "
            "Отправляю в Telegram…"
        )

        audio_file = FSInputFile(
            audio_path
        )

        await callback.message.answer_audio(
            audio=audio_file,
            title=title,
            performer=(
                uploader
                or "YouTube"
            ),
            caption=(
                f"🎵 {title}\n"
                "🎧 Качество: MP3 • 192 kbps\n"
                "\n"
                f"◆ {bot_identity.name}\n"
                f"{bot_identity.username_with_at}"
            ),
        )

        stats_storage.record_audio_download(
            file_size=file_size
        )

        progress.set_complete(
            "Загрузка завершена"
        )

        await progress_updater.stop(
            file_size=file_size,
            show_complete=True,
        )

    except YouTubeDurationLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Видео слишком длинное"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Видео слишком длинное."
            "\n\n"
            "Максимальная длительность: "
            f"{get_duration_limit_minutes()} "
            "минут."
        )

    except YouTubeFileSizeLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Аудиофайл слишком большой"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Аудиофайл получился "
            "слишком большим."
            "\n\n"
            "Максимальный размер: "
            f"{settings.max_file_size_mb} МБ."
        )

    except YouTubeMetadataError:
        stats_storage.record_failure()

        progress.set_failed(
            "Не удалось скачать аудио"
        )

        await progress_updater.stop()

        await status_message.edit_text(
            "❌ Не удалось "
            "скачать аудио."
        )

    except Exception:
        stats_storage.record_failure()

        progress.set_failed(
            "Внутренняя ошибка"
        )

        await progress_updater.stop()

        logger.exception(
            "Неожиданная ошибка "
            "при скачивании YouTube-аудио"
        )

        await status_message.edit_text(
            "❌ Произошла "
            "внутренняя ошибка "
            "при обработке аудио."
        )

    finally:
        await progress_updater.stop()

        download_coordinator.release_user(user_id)

        shutil.rmtree(
            output_dir,
            ignore_errors=True,
        )