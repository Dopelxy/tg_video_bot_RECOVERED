import asyncio
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from app.config.app_settings import settings
from app.models.media import (
    MediaFormat,
    MediaMetadata,
)
from app.services.progress import (
    DownloadProgress,
)


class UnsupportedUrlError(ValueError):
    pass


class YouTubeMetadataError(RuntimeError):
    pass


class YouTubeDurationLimitError(RuntimeError):
    pass


class YouTubeFileSizeLimitError(RuntimeError):
    pass


class YouTubeDownloader:
    _ALLOWED_HOSTS = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    }

    def supports_url(
        self,
        url: str,
    ) -> bool:
        try:
            parsed = urlparse(url)

            if parsed.scheme not in {
                "http",
                "https",
            }:
                return False

            hostname = parsed.hostname

            if hostname is None:
                return False

            return (
                hostname.lower()
                in self._ALLOWED_HOSTS
            )

        except ValueError:
            return False

    async def get_metadata(
        self,
        url: str,
    ) -> MediaMetadata:
        if not self.supports_url(url):
            raise UnsupportedUrlError(
                "Ссылка не относится "
                "к поддерживаемым адресам YouTube"
            )

        info = await asyncio.to_thread(
            self._extract_info_sync,
            url,
        )

        self._validate_duration(
            info
        )

        return MediaMetadata(
            title=(
                info.get("title")
                or "Без названия"
            ),
            uploader=(
                info.get("uploader")
            ),
            duration=(
                info.get("duration")
            ),
            webpage_url=(
                info.get("webpage_url")
                or url
            ),
        )

    async def get_formats(
        self,
        url: str,
    ) -> list[MediaFormat]:
        if not self.supports_url(url):
            raise UnsupportedUrlError(
                "Ссылка не относится "
                "к поддерживаемым адресам YouTube"
            )

        info = await asyncio.to_thread(
            self._extract_info_sync,
            url,
        )

        self._validate_duration(
            info
        )

        formats = (
            info.get("formats")
            or []
        )

        best_by_height: dict[
            int,
            MediaFormat,
        ] = {}

        for item in formats:
            height = item.get(
                "height"
            )

            video_codec = item.get(
                "vcodec"
            )

            if not isinstance(
                height,
                int,
            ):
                continue

            if video_codec in {
                None,
                "none",
            }:
                continue

            ext = (
                item.get("ext")
                or "unknown"
            )

            format_id = str(
                item.get("format_id")
                or ""
            )

            if not format_id:
                continue

            filesize = (
                item.get("filesize")
                or item.get(
                    "filesize_approx"
                )
            )

            candidate = MediaFormat(
                format_id=format_id,
                height=height,
                ext=ext,
                filesize=filesize,
            )

            current = (
                best_by_height.get(
                    height
                )
            )

            if current is None:
                best_by_height[
                    height
                ] = candidate

                continue

            if (
                current.ext != "mp4"
                and candidate.ext == "mp4"
            ):
                best_by_height[
                    height
                ] = candidate

        return sorted(
            best_by_height.values(),
            key=lambda item: item.height,
        )

    async def download_video(
        self,
        url: str,
        max_height: int,
        output_dir: Path,
        progress: DownloadProgress | None = None,
    ) -> Path:
        if not self.supports_url(url):
            raise UnsupportedUrlError(
                "Ссылка не относится "
                "к поддерживаемым адресам YouTube"
            )

        if max_height not in {
            360,
            720,
            1080,
        }:
            raise ValueError(
                "Неподдерживаемое "
                "качество видео"
            )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        video_path = (
            await asyncio.to_thread(
                self._download_video_sync,
                url,
                max_height,
                output_dir,
                progress,
            )
        )

        self._validate_file_size(
            video_path
        )

        return video_path

    async def download_audio(
        self,
        url: str,
        output_dir: Path,
        progress: DownloadProgress | None = None,
    ) -> Path:
        if not self.supports_url(url):
            raise UnsupportedUrlError(
                "Ссылка не относится "
                "к поддерживаемым адресам YouTube"
            )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        audio_path = (
            await asyncio.to_thread(
                self._download_audio_sync,
                url,
                output_dir,
                progress,
            )
        )

        self._validate_file_size(
            audio_path
        )

        return audio_path

    def _create_progress_hook(
        self,
        progress: DownloadProgress | None,
    ):
        def progress_hook(
            data: dict,
        ) -> None:
            if progress is None:
                return

            status = data.get(
                "status"
            )

            if status == "downloading":
                downloaded_bytes = int(
                    data.get(
                        "downloaded_bytes"
                    )
                    or 0
                )

                total_bytes_raw = (
                    data.get(
                        "total_bytes"
                    )
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
                    downloaded_bytes=(
                        downloaded_bytes
                    ),
                    total_bytes=(
                        total_bytes
                    ),
                    speed_bytes_per_second=(
                        speed
                    ),
                    eta_seconds=(
                        eta
                    ),
                )

            elif status == "finished":
                progress.set_processing(
                    "Медиапоток загружен. "
                    "Обрабатываю…"
                )

        return progress_hook

    def _download_video_sync(
        self,
        url: str,
        max_height: int,
        output_dir: Path,
        progress: DownloadProgress | None,
    ) -> Path:
        output_template = str(
            output_dir
            / "%(id)s.%(ext)s"
        )

        format_selector = (
            f"bestvideo"
            f"[height<={max_height}]"
            f"[vcodec^=avc1]"
            "+bestaudio"
            "[acodec^=mp4a]"
            f"/best"
            f"[height<={max_height}]"
            f"[ext=mp4]"
            f"/bestvideo"
            f"[height<={max_height}]"
            "+bestaudio"
            f"/best"
            f"[height<={max_height}]"
        )

        options = {
            "format": (
                format_selector
            ),
            "outtmpl": (
                output_template
            ),
            "noplaylist": True,
            "merge_output_format": (
                "mp4"
            ),
            "quiet": False,
            "no_warnings": False,
            "progress_hooks": [
                self._create_progress_hook(
                    progress
                )
            ],
        }

        try:
            with yt_dlp.YoutubeDL(
                options
            ) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )

                if not info:
                    raise YouTubeMetadataError(
                        "YouTube не вернул "
                        "информацию о видео"
                    )

                self._validate_duration(
                    info
                )

                info = ydl.extract_info(
                    url,
                    download=True,
                )

                prepared_filename = Path(
                    ydl.prepare_filename(
                        info
                    )
                )

        except YouTubeDurationLimitError:
            raise

        except yt_dlp.utils.DownloadError as exc:
            raise YouTubeMetadataError(
                "Не удалось скачать видео"
            ) from exc

        expected_mp4 = (
            prepared_filename.with_suffix(
                ".mp4"
            )
        )

        if expected_mp4.exists():
            return expected_mp4

        if prepared_filename.exists():
            return prepared_filename

        video_id = info.get(
            "id"
        )

        if video_id:
            candidates = list(
                output_dir.glob(
                    f"{video_id}.*"
                )
            )

            if candidates:
                return candidates[0]

        raise YouTubeMetadataError(
            "Загрузка завершилась, "
            "но итоговый файл не найден"
        )

    def _download_audio_sync(
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
            "format": (
                "bestaudio/best"
            ),
            "outtmpl": (
                output_template
            ),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "progress_hooks": [
                self._create_progress_hook(
                    progress
                )
            ],
            "postprocessors": [
                {
                    "key": (
                        "FFmpegExtractAudio"
                    ),
                    "preferredcodec": (
                        "mp3"
                    ),
                    "preferredquality": (
                        "192"
                    ),
                }
            ],
        }

        try:
            with yt_dlp.YoutubeDL(
                options
            ) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )

                if not info:
                    raise YouTubeMetadataError(
                        "YouTube не вернул "
                        "информацию о видео"
                    )

                self._validate_duration(
                    info
                )

                info = ydl.extract_info(
                    url,
                    download=True,
                )

        except YouTubeDurationLimitError:
            raise

        except yt_dlp.utils.DownloadError as exc:
            raise YouTubeMetadataError(
                "Не удалось скачать аудио"
            ) from exc

        video_id = info.get(
            "id"
        )

        if not video_id:
            raise YouTubeMetadataError(
                "Не удалось определить "
                "ID видео"
            )

        expected_mp3 = (
            output_dir
            / f"{video_id}.mp3"
        )

        if expected_mp3.exists():
            return expected_mp3

        candidates = list(
            output_dir.glob(
                f"{video_id}.*"
            )
        )

        if candidates:
            return candidates[0]

        raise YouTubeMetadataError(
            "Аудио обработано, "
            "но итоговый файл не найден"
        )

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

        try:
            with yt_dlp.YoutubeDL(
                options
            ) as ydl:
                info = ydl.extract_info(
                    url,
                    download=False,
                )

        except yt_dlp.utils.DownloadError as exc:
            raise YouTubeMetadataError(
                "Не удалось получить "
                "информацию о видео"
            ) from exc

        if not info:
            raise YouTubeMetadataError(
                "YouTube не вернул "
                "информацию о видео"
            )

        return info

    def _validate_duration(
        self,
        info: dict,
    ) -> None:
        duration = info.get(
            "duration"
        )

        if duration is None:
            return

        try:
            duration_seconds = int(
                duration
            )

        except (
            TypeError,
            ValueError,
        ):
            return

        if (
            duration_seconds
            > settings.max_video_duration_seconds
        ):
            raise YouTubeDurationLimitError(
                "Видео превышает "
                "разрешённую длительность"
            )

    def _validate_file_size(
        self,
        file_path: Path,
    ) -> None:
        if not file_path.exists():
            raise YouTubeMetadataError(
                "Итоговый файл не найден"
            )

        max_bytes = (
            settings.max_file_size_mb
            * 1024
            * 1024
        )

        actual_bytes = (
            file_path.stat().st_size
        )

        if actual_bytes > max_bytes:
            raise YouTubeFileSizeLimitError(
                "Файл превышает "
                "разрешённый размер"
            )