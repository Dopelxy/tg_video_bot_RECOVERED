import asyncio
import logging
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

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
from app.storage.stats import stats_storage


router = Router()
logger = logging.getLogger(__name__)

instagram_downloader = InstagramDownloader()

TEMP_ROOT = Path("temp_downloads")

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

    while True:
        text = render_progress(
            progress
        )

        if text != last_text:
            try:
                await status_message.edit_text(
                    text
                )

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

    job_id = uuid.uuid4().hex

    output_dir = (
        TEMP_ROOT
        / str(user_id)
        / job_id
    )

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
            await status_message.edit_text(
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
            await status_message.edit_text(
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

        await message.answer_video(
            video=video_file,
            caption=(
                "📸 Instagram\n"
                f"👤 "
                f"{metadata.uploader or 'Instagram'}\n"
                "\n"
                f"◆ {bot_identity.name}\n"
                f"{bot_identity.username_with_at}"
            ),
        )

        stats_storage.record_instagram_download(
            file_size=file_size
        )

        progress.set_complete(
            "Готово"
        )

        try:
            await status_message.edit_text(
                "📸 Instagram\n\n"
                "✅ Готово"
            )
        except Exception:
            pass

    except InstagramDurationLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Видео слишком длинное."
        )

        if status_message is not None:
            await status_message.edit_text(
                "❌ Видео слишком длинное.\n\n"
                "Максимальная длительность: "
                f"{settings.max_video_duration_seconds // 60} мин."
            )

    except InstagramFileSizeLimitError:
        stats_storage.record_failure()

        progress.set_failed(
            "Видео слишком большое."
        )

        if status_message is not None:
            await status_message.edit_text(
                "❌ Видео слишком большое.\n\n"
                "Максимальный размер: "
                f"{settings.max_file_size_mb} MB."
            )

    except UnsupportedInstagramUrlError:
        progress.set_failed(
            "Ссылка не поддерживается."
        )

        if status_message is not None:
            await status_message.edit_text(
                "❌ Эта ссылка Instagram "
                "не поддерживается."
            )

    except InstagramMetadataError:
        stats_storage.record_failure()

        progress.set_failed(
            "Не удалось получить "
            "информацию из Instagram."
        )

        if status_message is not None:
            await status_message.edit_text(
                "❌ Не удалось получить "
                "информацию из Instagram."
            )

    except InstagramDownloadError:
        stats_storage.record_failure()

        progress.set_failed(
            "Не удалось скачать видео."
        )

        if status_message is not None:
            await status_message.edit_text(
                "❌ Не удалось скачать "
                "видео из Instagram."
            )

    except Exception:
        stats_storage.record_failure()

        progress.set_failed(
            "Внутренняя ошибка."
        )

        logger.exception(
            "Неожиданная ошибка "
            "при обработке Instagram"
        )

        if status_message is not None:
            try:
                await status_message.edit_text(
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

        shutil.rmtree(
            output_dir,
            ignore_errors=True,
        )

        download_coordinator.release_user(
            user_id
        )