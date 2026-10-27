import asyncio
import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.types import (
    FSInputFile,
    Message,
)

from app.config.app_settings import settings
from app.downloaders.instagram import (
    InstagramDownloadError,
    InstagramDownloader,
    InstagramDurationLimitError,
    InstagramFileSizeLimitError,
    InstagramMetadataError,
    UnsupportedInstagramUrlError,
)
from app.services.bot_identity import (
    load_bot_identity,
)
from app.services.download_coordinator import download_coordinator
from app.services.progress import (
    DownloadProgress,
    DownloadStage,
)
from app.storage.stats import record_safely
from app.services.job_files import current_job, with_job
from app.services.telegram_io import edit_status, StatusEditor, delivery_error
from aiogram.exceptions import TelegramAPIError
from app.services.worker_errors import WorkerError
from app.services.video_caption import video_caption


router = Router()
logger = logging.getLogger(__name__)

instagram_downloader = InstagramDownloader()


def format_bytes(
    value: int | None,
) -> str:
    if value is None:
        return "—"

    size = float(value)

    units = (
        "B",
        "KB",
        "MB",
        "GB",
    )

    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"

        size /= 1024

    return f"{size:.1f} TB"


def format_speed(
    value: float | None,
) -> str:
    if value is None:
        return "—"

    return (
        f"{format_bytes(int(value))}/s"
    )


def format_eta(
    seconds: int | None,
) -> str:
    if seconds is None:
        return "—"

    seconds = max(
        int(seconds),
        0,
    )

    if seconds < 60:
        return f"~{seconds} сек."

    minutes, remaining_seconds = divmod(
        seconds,
        60,
    )

    if minutes < 60:
        return (
            f"~{minutes} мин. "
            f"{remaining_seconds} сек."
        )

    hours, remaining_minutes = divmod(
        minutes,
        60,
    )

    return (
        f"~{hours} ч. "
        f"{remaining_minutes} мин."
    )


def build_progress_bar(
    percent: float,
) -> str:
    bar_length = 18

    safe_percent = max(
        0.0,
        min(
            percent,
            100.0,
        ),
    )

    filled = round(
        safe_percent
        / 100
        * bar_length
    )

    empty = (
        bar_length
        - filled
    )

    return (
        "█" * filled
        + "░" * empty
    )


def render_progress(
    progress: DownloadProgress,
) -> str:
    snapshot = progress.snapshot()

    if (
        snapshot.stage
        == DownloadStage.DOWNLOADING
    ):
        bar = build_progress_bar(
            snapshot.percent
        )

        if (
            snapshot.total_bytes
            is not None
        ):
            size_text = (
                f"{format_bytes(snapshot.downloaded_bytes)}"
                " / "
                f"{format_bytes(snapshot.total_bytes)}"
            )
        else:
            size_text = format_bytes(
                snapshot.downloaded_bytes
            )

        return (
            "📸 Instagram\n\n"
            f"⏳ {bar} "
            f"{snapshot.percent:.0f}%\n\n"
            f"📦 {size_text}\n"
            f"⚡ {format_speed(snapshot.speed_bytes_per_second)}\n"
            f"⏱ Осталось: {format_eta(snapshot.eta_seconds)}\n\n"
            f"{snapshot.status_text}"
        )

    if (
        snapshot.stage
        == DownloadStage.PROCESSING
    ):
        return (
            "📸 Instagram\n\n"
            "⚙️ "
            f"{snapshot.status_text}"
        )

    if (
        snapshot.stage
        == DownloadStage.UPLOADING
    ):
        return (
            "📸 Instagram\n\n"
            "📤 "
            f"{snapshot.status_text}"
        )

    if (
        snapshot.stage
        == DownloadStage.COMPLETE
    ):
        return (
            "📸 Instagram\n\n"
            "✅ Готово"
        )

    if (
        snapshot.stage
        == DownloadStage.FAILED
    ):
        return (
            "📸 Instagram\n\n"
            "❌ "
            f"{snapshot.status_text}"
        )

    return (
        "📸 Instagram\n\n"
        "⏳ Подготовка загрузки…"
    )


async def update_progress_message(
    *,
    status_message: Message,
    progress: DownloadProgress,
) -> None:
    last_text: str | None = None
    editor = StatusEditor(status_message)

    while True:
        text = render_progress(
            progress
        )

        if text != last_text:
            try:
                if await editor.edit(text):
                    last_text = text

            except Exception:
                # Ошибка редактирования статуса
                # не должна ломать загрузку.
                pass

        snapshot = progress.snapshot()

        if snapshot.stage in {
            DownloadStage.COMPLETE,
            DownloadStage.FAILED,
        }:
            return

        await asyncio.sleep(
            1.0
        )


@router.message(
    F.text.contains("instagram.com")
)
@with_job
async def instagram_link_handler(
    message: Message,
) -> None:
    if message.text is None:
        return

    if message.from_user is None:
        return

    url = message.text.strip()

    if not instagram_downloader.supports_url(
        url
    ):
        await message.answer(
            "❌ Эта ссылка Instagram "
            "не поддерживается."
        )
        return

    user_id = message.from_user.id

    user_claimed = download_coordinator.claim_user(
        user_id
    )

    if not user_claimed:
        await message.answer(
            "⏳ У тебя уже идёт загрузка.\n\n"
            "Дождись её завершения."
        )
        return

    output_dir = current_job.get()

    progress = DownloadProgress()

    progress_task: asyncio.Task | None = None

    status_message: Message | None = None

    try:
        status_message = await message.answer(
            "📸 Instagram\n\n"
            "🔎 Получаю информацию…"
        )

        metadata = (
            await instagram_downloader.get_metadata(
                url
            )
        )

        if metadata.media_type != "video":
            await edit_status(status_message,
                "❌ Пока поддерживаются "
                "только Instagram Reels "
                "и видеопосты."
            )
            return

        progress_task = asyncio.create_task(
            update_progress_message(
                status_message=status_message,
                progress=progress,
            )
        )

        async with download_coordinator.download_semaphore:
            video_path = (
                await instagram_downloader.download_video(
                    url=url,
                    output_dir=output_dir,
                    progress=progress,
                )
            )

        file_size = (
            video_path.stat().st_size
        )

        progress.set_uploading(
            "Отправляю видео в Telegram…"
        )

        # Сразу показываем этап отправки,
        # не ждём следующего тика таймера.
        try:
            await edit_status(status_message,
                render_progress(
                    progress
                )
            )
        except Exception:
            pass

        bot_identity = (
            await load_bot_identity(
                message.bot
            )
        )

        video_file = FSInputFile(
            video_path
        )

        async with download_coordinator.upload_semaphore:
            await message.answer_video(
                video=video_file,
                caption=video_caption(
                    platform="instagram", title=getattr(metadata, "title", "Instagram"),
                    author=metadata.uploader or "Instagram",
                    channel_url=getattr(metadata, "channel_url", None),
                    uploader_url=getattr(metadata, "uploader_url", None),
                    webpage_url=getattr(metadata, "webpage_url", None), source_url=url,
                    bot_name=bot_identity.name, bot_username=bot_identity.username,
                ),
                parse_mode="HTML",
                request_timeout=600,
            )

        await record_safely("record_instagram_download",
            file_size=file_size
        )

        progress.set_complete(
            "Готово"
        )

        try:
            await edit_status(status_message,
                "📸 Instagram\n\n"
                "✅ Готово"
            )
        except Exception:
            pass

    except InstagramDurationLimitError:
        await record_safely("record_failure")

        progress.set_failed(
            "Видео слишком длинное."
        )

        if status_message is not None:
            await edit_status(status_message,
                "❌ Видео слишком длинное.\n\n"
                "Максимальная длительность: "
                f"{settings.max_video_duration_seconds // 60} мин."
            )

    except InstagramFileSizeLimitError:
        await record_safely("record_failure")

        progress.set_failed(
            "Видео слишком большое."
        )

        if status_message is not None:
            await edit_status(status_message,
                "❌ Видео слишком большое.\n\n"
                "Максимальный размер: "
                f"{settings.max_file_size_mb} MB."
            )

    except UnsupportedInstagramUrlError:
        progress.set_failed(
            "Ссылка не поддерживается."
        )

        if status_message is not None:
            await edit_status(status_message,
                "❌ Эта ссылка Instagram "
                "не поддерживается."
            )

    except InstagramMetadataError:
        await record_safely("record_failure")

        progress.set_failed(
            "Не удалось получить "
            "информацию из Instagram."
        )

        if status_message is not None:
            await edit_status(status_message,
                "❌ Не удалось получить "
                "информацию из Instagram."
            )

    except InstagramDownloadError:
        await record_safely("record_failure")

        progress.set_failed(
            "Не удалось скачать видео."
        )

        if status_message is not None:
            await edit_status(status_message,
                "❌ Не удалось скачать "
                "видео из Instagram."
            )

    except WorkerError as error:
        await record_safely("record_failure")
        progress.set_failed(str(error))
        await edit_status(status_message, "\u274c " + str(error))

    except TelegramAPIError as error:
        await record_safely("record_failure")
        progress.set_failed(delivery_error(error))
        await edit_status(status_message, "\u274c " + delivery_error(error))

    except Exception:
        await record_safely("record_failure")

        progress.set_failed(
            "Внутренняя ошибка."
        )

        logger.error(
            "Неожиданная ошибка "
            "при обработке Instagram"
        )

        if status_message is not None:
            try:
                await edit_status(status_message,
                    "❌ Произошла внутренняя "
                    "ошибка при обработке Instagram."
                )
            except Exception:
                pass

    finally:
        if progress_task is not None:
            if not progress_task.done():
                progress_task.cancel()

            with suppress(
                asyncio.CancelledError
            ):
                await progress_task


        download_coordinator.release_user(
            user_id
        )
