from dataclasses import dataclass
from enum import Enum
from threading import Lock
from time import monotonic


class DownloadStage(str, Enum):
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class ProgressSnapshot:
    stage: DownloadStage

    percent: float

    downloaded_bytes: int
    total_bytes: int | None

    speed_bytes_per_second: float | None
    eta_seconds: int | None

    status_text: str

    elapsed_seconds: float


class DownloadProgress:
    def __init__(self) -> None:
        self._lock = Lock()

        self._stage = DownloadStage.PREPARING

        self._percent = 0.0

        self._downloaded_bytes = 0
        self._total_bytes: int | None = None

        self._speed_bytes_per_second: float | None = None
        self._eta_seconds: int | None = None

        self._status_text = "Подготовка загрузки…"

        self._started_at = monotonic()

    def update_download(
        self,
        *,
        downloaded_bytes: int,
        total_bytes: int | None,
        speed_bytes_per_second: float | None,
        eta_seconds: int | None,
    ) -> None:
        percent = 0.0

        if (
            total_bytes is not None
            and total_bytes > 0
        ):
            percent = (
                downloaded_bytes
                / total_bytes
                * 100
            )

        percent = max(
            0.0,
            min(
                percent,
                100.0,
            ),
        )

        with self._lock:
            self._stage = (
                DownloadStage.DOWNLOADING
            )

            self._percent = percent

            self._downloaded_bytes = max(
                downloaded_bytes,
                0,
            )

            self._total_bytes = (
                total_bytes
            )

            self._speed_bytes_per_second = (
                speed_bytes_per_second
            )

            self._eta_seconds = (
                eta_seconds
            )

            self._status_text = (
                "Загрузка медиапотока…"
            )

    def set_processing(
        self,
        text: str = "Финальная обработка…",
    ) -> None:
        with self._lock:
            self._stage = (
                DownloadStage.PROCESSING
            )

            self._speed_bytes_per_second = None
            self._eta_seconds = None

            self._status_text = text

    def set_uploading(
        self,
        text: str = "Отправляю в Telegram…",
    ) -> None:
        with self._lock:
            self._stage = (
                DownloadStage.UPLOADING
            )

            self._percent = 100.0

            self._speed_bytes_per_second = None
            self._eta_seconds = None

            self._status_text = text

    def set_complete(
        self,
        text: str = "Готово",
    ) -> None:
        with self._lock:
            self._stage = (
                DownloadStage.COMPLETE
            )

            self._percent = 100.0

            self._speed_bytes_per_second = None
            self._eta_seconds = None

            self._status_text = text

    def set_failed(
        self,
        text: str,
    ) -> None:
        with self._lock:
            self._stage = (
                DownloadStage.FAILED
            )

            self._speed_bytes_per_second = None
            self._eta_seconds = None

            self._status_text = text

    def snapshot(
        self,
    ) -> ProgressSnapshot:
        with self._lock:
            return ProgressSnapshot(
                stage=self._stage,

                percent=self._percent,

                downloaded_bytes=(
                    self._downloaded_bytes
                ),

                total_bytes=(
                    self._total_bytes
                ),

                speed_bytes_per_second=(
                    self._speed_bytes_per_second
                ),

                eta_seconds=(
                    self._eta_seconds
                ),

                status_text=self._status_text,

                elapsed_seconds=(
                    monotonic()
                    - self._started_at
                ),
            )