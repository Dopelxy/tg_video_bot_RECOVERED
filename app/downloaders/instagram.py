import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from app.config.app_settings import settings
from app.config.app_settings import settings
from app.services.progress import DownloadProgress


logger = logging.getLogger(__name__)


class InstagramError(Exception):
    pass


class UnsupportedInstagramUrlError(
    InstagramError
):
    pass


class InstagramMetadataError(
    InstagramError
):
    pass


class InstagramDownloadError(
    InstagramError
):
    pass


class InstagramDurationLimitError(
    InstagramError
):
    pass


class InstagramFileSizeLimitError(
    InstagramError
):
    pass


@dataclass(
    slots=True,
    frozen=True,
)
class InstagramMetadata:
    title: str
    uploader: str | None
    duration: int | None
    webpage_url: str
    media_type: str


class InstagramDownloader:
    SUPPORTED_HOSTS = {
        "instagram.com",
        "www.instagram.com",
    }

    VIDEO_SUFFIXES = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
    }

    def supports_url(
        self,
        url: str,
    ) -> bool:
        try:
            parsed_url = urlparse(
                url
            )
        except ValueError:
            return False

        if parsed_url.scheme not in {
            "http",
            "https",
        }:
            return False

        if parsed_url.hostname not in (
            self.SUPPORTED_HOSTS
        ):
            return False

        path = parsed_url.path.lower()

        supported_paths = (
            "/reel/",
            "/reels/",
            "/p/",
            "/tv/",
        )

        return path.startswith(
            supported_paths
        )

    async def get_metadata(
        self,
        url: str,
    ) -> InstagramMetadata:
        if not self.supports_url(
            url
        ):
            raise UnsupportedInstagramUrlError(
                "Ссылка Instagram "
                "не поддерживается"
            )

        try:
            info = await asyncio.to_thread(
                self._extract_info_sync,
                url,
            )

        except InstagramError:
            raise

        except Exception as error:
            logger.exception(
                "Не удалось получить "
                "метаданные Instagram"
            )

            raise InstagramMetadataError(
                "Не удалось получить "
                "метаданные Instagram"
            ) from error

        metadata = self._build_metadata(
            info=info,
            original_url=url,
        )

        self._validate_duration(
            metadata.duration
        )

        self._validate_estimated_size(
            info
        )

        return metadata

    async def download_video(
        self,
        *,
        url: str,
        output_dir: Path,
        progress: DownloadProgress | None = None,
    ) -> Path:
        if not self.supports_url(
            url
        ):
            raise UnsupportedInstagramUrlError(
                "Ссылка Instagram "
                "не поддерживается"
            )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        if progress is not None:
            progress.set_processing(
                "Подготовка загрузки Instagram…"
            )

        try:
            video_path = await asyncio.to_thread(
                self._download_video_sync,
                url,
                output_dir,
                progress,
            )

            self._validate_downloaded_file_size(
                video_path
            )

            return video_path

        except InstagramError:
            raise

        except Exception as error:
            logger.exception(
                "Не удалось скачать "
                "Instagram-видео"
            )

            raise InstagramDownloadError(
                "Не удалось скачать "
                "Instagram-видео"
            ) from error

    def _extract_info_sync(
        self,
        url: str,
    ) -> dict:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }

        with YoutubeDL(
            options
        ) as ydl:
            info = ydl.extract_info(
                url,
                download=False,
            )

        if not isinstance(
            info,
            dict,
        ):
            raise InstagramMetadataError(
                "Некорректный ответ yt-dlp"
            )

        return info

    def _download_video_sync(
        self,
        url: str,
        output_dir: Path,
        progress: DownloadProgress | None,
    ) -> Path:
        output_template = str(
            output_dir
            / "%(id)s.%(ext)s"
        )

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": output_template,
            "format": (
                "bestvideo+bestaudio/"
                "best"
            ),
            "merge_output_format": "mp4",
        }

        if progress is not None:
            options["progress_hooks"] = [
                self._create_progress_hook(
                    progress
                )
            ]

        with YoutubeDL(
            options
        ) as ydl:
            info = ydl.extract_info(
                url,
                download=True,
            )

            if not isinstance(
                info,
                dict,
            ):
                raise InstagramDownloadError(
                    "Некорректный ответ yt-dlp"
                )

            prepared_filename = (
                ydl.prepare_filename(
                    info
                )
            )

        if progress is not None:
            progress.set_processing(
                "Обрабатываю видео…"
            )

        prepared_path = Path(
            prepared_filename
        )

        mp4_path = (
            prepared_path.with_suffix(
                ".mp4"
            )
        )

        if mp4_path.exists():
            return mp4_path

        if prepared_path.exists():
            return prepared_path

        media_files = [
            path
            for path in output_dir.iterdir()
            if (
                path.is_file()
                and path.suffix.lower()
                in self.VIDEO_SUFFIXES
            )
        ]

        if len(media_files) == 1:
            return media_files[0]

        raise InstagramDownloadError(
            "Скачанный видеофайл "
            "не найден"
        )

    def _create_progress_hook(
        self,
        progress: DownloadProgress,
    ):
        def hook(
            data: dict,
        ) -> None:
            status = data.get(
                "status"
            )

            if status == "downloading":
                downloaded_bytes = int(
                    data.get(
                        "downloaded_bytes",
                        0,
                    )
                    or 0
                )

                total_bytes_raw = (
                    data.get("total_bytes")
                    or data.get(
                        "total_bytes_estimate"
                    )
                )

                total_bytes = (
                    int(total_bytes_raw)
                    if total_bytes_raw
                    else None
                )

                speed_raw = data.get(
                    "speed"
                )

                speed = (
                    float(speed_raw)
                    if speed_raw
                    else None
                )

                eta_raw = data.get(
                    "eta"
                )

                eta = (
                    int(eta_raw)
                    if eta_raw is not None
                    else None
                )

                progress.update_download(
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                    speed_bytes_per_second=speed,
                    eta_seconds=eta,
                )

            elif status == "finished":
                progress.set_processing(
                    "Загрузка завершена. "
                    "Обрабатываю файл…"
                )

        return hook

    def _build_metadata(
        self,
        *,
        info: dict,
        original_url: str,
    ) -> InstagramMetadata:
        title = self._get_title(
            info
        )

        uploader = (
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
        )

        duration_raw = info.get(
            "duration"
        )

        duration = (
            int(duration_raw)
            if duration_raw is not None
            else None
        )

        webpage_url = (
            info.get("webpage_url")
            or original_url
        )

        media_type = (
            self._detect_media_type(
                info
            )
        )

        return InstagramMetadata(
            title=title,
            uploader=uploader,
            duration=duration,
            webpage_url=webpage_url,
            media_type=media_type,
        )

    def _validate_duration(
        self,
        duration: int | None,
    ) -> None:
        if duration is None:
            return

        if (
            duration
            > settings.max_video_duration_seconds
        ):
            raise InstagramDurationLimitError(
                "Видео превышает "
                "допустимую длительность"
            )

    def _validate_estimated_size(
        self,
        info: dict,
    ) -> None:
        max_bytes = (
            settings.max_file_size_mb
            * 1024
            * 1024
        )

        filesize_raw = (
            info.get("filesize")
            or info.get(
                "filesize_approx"
            )
        )

        if filesize_raw is None:
            return

        try:
            filesize = int(
                filesize_raw
            )
        except (
            TypeError,
            ValueError,
        ):
            return

        if filesize > max_bytes:
            raise InstagramFileSizeLimitError(
                "Видео превышает "
                "допустимый размер"
            )

    def _validate_downloaded_file_size(
        self,
        video_path: Path,
    ) -> None:
        max_bytes = (
            settings.max_file_size_mb
            * 1024
            * 1024
        )

        actual_size = (
            video_path.stat().st_size
        )

        if actual_size > max_bytes:
            raise InstagramFileSizeLimitError(
                "Скачанный файл превышает "
                "допустимый размер"
            )

    def _get_title(
        self,
        info: dict,
    ) -> str:
        title = info.get(
            "title"
        )

        if isinstance(
            title,
            str,
        ):
            cleaned_title = (
                title.strip()
            )

            if cleaned_title:
                return cleaned_title

        description = info.get(
            "description"
        )

        if isinstance(
            description,
            str,
        ):
            cleaned_description = (
                description.strip()
            )

            if cleaned_description:
                return (
                    cleaned_description[:120]
                )

        return "Instagram media"

    def _detect_media_type(
        self,
        info: dict,
    ) -> str:
        entries = info.get(
            "entries"
        )

        if entries:
            return "carousel"

        video_codec = info.get(
            "vcodec"
        )

        if (
            isinstance(
                video_codec,
                str,
            )
            and video_codec != "none"
        ):
            return "video"

        return "image"