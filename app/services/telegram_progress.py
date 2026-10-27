import asyncio
import contextlib
from app.services.telegram_io import StatusEditor

from aiogram.types import Message

from app.models.bot_identity import BotIdentity
from app.services.progress import (
    DownloadProgress,
    DownloadStage,
)
from app.services.progress_renderer import (
    render_complete,
    render_progress,
)


class TelegramProgressUpdater:
    def __init__(
        self,
        *,
        message: Message,
        progress: DownloadProgress,
        title: str,
        format_name: str,
        bot_identity: BotIdentity,
        update_interval: float = 1.0,
    ) -> None:
        self._message = message
        self._editor = StatusEditor(message)
        self._progress = progress
        self._title = title
        self._format_name = format_name
        self._bot_identity = bot_identity
        self._update_interval = update_interval

        self._task: asyncio.Task | None = None
        self._last_text: str | None = None
        self._stopped = False

    def start(self) -> None:
        if self._task is not None:
            return

        self._task = asyncio.create_task(
            self._run()
        )

    async def stop(
        self,
        *,
        file_size: int | None = None,
        show_complete: bool = False,
    ) -> None:
        self._stopped = True

        if self._task is not None:
            self._task.cancel()

            with contextlib.suppress(
                asyncio.CancelledError
            ):
                await self._task

            self._task = None

        if (
            show_complete
            and file_size is not None
        ):
            snapshot = (
                self._progress.snapshot()
            )

            text = render_complete(
                title=self._title,
                format_name=self._format_name,
                bot_name=self._bot_identity.name,
                bot_username=self._bot_identity.username,
                file_size=file_size,
                snapshot=snapshot,
            )

            await self._safe_edit(
                text
            )

    async def _run(self) -> None:
        while not self._stopped:
            snapshot = (
                self._progress.snapshot()
            )

            text = render_progress(
                title=self._title,
                format_name=self._format_name,
                bot_name=self._bot_identity.name,
                bot_username=self._bot_identity.username,
                snapshot=snapshot,
            )

            await self._safe_edit(
                text
            )

            if snapshot.stage in {
                DownloadStage.COMPLETE,
                DownloadStage.FAILED,
            }:
                break

            await asyncio.sleep(
                self._update_interval
            )

    async def _safe_edit(
        self,
        text: str,
    ) -> None:
        if text == self._last_text:
            return

        if await self._editor.edit(text):
            self._last_text = text
