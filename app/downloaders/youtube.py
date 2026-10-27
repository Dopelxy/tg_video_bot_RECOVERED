from pathlib import Path
import math
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
from app.services.download_worker_process import run_download_worker, WorkerError
from app.services.download_coordinator import download_coordinator
from app.services.media_files import download_options
from app.paths import TEMP_ROOT
from app.services.video_caption import platform_url


def normalize_height(value):
    """Accept exact numeric dimensions, never round a different resolution."""
    if isinstance(value, bool):
        return None
    try:
        height = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(height) if math.isfinite(height) and height > 0 and height.is_integer() else None


def video_format_selector(height):
    if height not in {360, 720, 1080}:
        raise ValueError("Неподдерживаемое качество видео")
    # Fallback may change codec/container, never the advertised resolution.
    exact = f"[height={height}]"
    return (f"bestvideo{exact}[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
            f"/best{exact}[ext=mp4]"
            f"/bestvideo{exact}+bestaudio/best{exact}")


def selected_height(info):
    height = normalize_height(info.get("height"))
    if height is not None:
        return height
    heights = {normalize_height(f.get("height")) for f in
               (info.get("requested_formats") or info.get("requested_downloads") or [])
               if f.get("vcodec") not in {None, "none"}}
    heights.discard(None)
    return next(iter(heights)) if len(heights) == 1 else None


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

        info = await self._get_info(url)

        return self._metadata_from_info(info, url)

    def _metadata_from_info(self, info, url):
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
                or info.get("channel")
            ),
            duration=(
                info.get("duration")
            ),
            webpage_url=(
                info.get("webpage_url")
                or url
            ),
            channel_url=platform_url(info.get("channel_url"), "youtube", author=True),
            uploader_url=platform_url(info.get("uploader_url"), "youtube", author=True),
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

        info = await self._get_info(url)

        return self._formats_from_info(info)

    def _formats_from_info(self, info):
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
            height = normalize_height(item.get("height"))

            video_codec = item.get(
                "vcodec"
            )

            if height is None:
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

    async def _get_info(self, url):
        if not self.supports_url(url):
            raise UnsupportedUrlError("Ссылка не поддерживается")
        async with download_coordinator.metadata_semaphore:
            return await run_download_worker("youtube_metadata", url=url,
                output_dir=TEMP_ROOT, max_height=None, progress=None, timeout=60)

    async def get_details(self, url):
        info = await self._get_info(url)
        return self._metadata_from_info(info, url), self._formats_from_info(info)

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

        try:
            video_path = await run_download_worker(
                "youtube_video", url=url, max_height=max_height,
                output_dir=output_dir, progress=progress,
            )
        except WorkerError as error:
            if error.code == "duration_limit":
                raise YouTubeDurationLimitError(
                    "Видео превышает разрешённую длительность"
                ) from error
            raise
        except RuntimeError as error:
            raise YouTubeMetadataError("Не удалось скачать видео") from error

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

        try:
            audio_path = await run_download_worker(
                "youtube_audio", url=url, max_height=None,
                output_dir=output_dir, progress=progress,
            )
        except WorkerError as error:
            if error.code == "duration_limit":
                raise YouTubeDurationLimitError(
                    "Видео превышает разрешённую длительность"
                ) from error
            raise
        except RuntimeError as error:
            raise YouTubeMetadataError("Не удалось скачать аудио") from error

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

        format_selector = video_format_selector(max_height)

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

        budget = download_options(output_dir)
        options["progress_hooks"] = budget.pop("progress_hooks") + options.get("progress_hooks", [])
        options.update(budget)
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

                if selected_height(info) != max_height:
                    raise WorkerError("quality_unavailable")

                info = ydl.extract_info(
                    url,
                    download=True,
                )

                if selected_height(info) != max_height:
                    raise WorkerError("quality_unavailable")

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

            candidates = [p for p in candidates if p.suffix.lower() in {".mp4", ".mkv", ".webm"}]
            if len(candidates) == 1:
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

        budget = download_options(output_dir)
        options["progress_hooks"] = budget.pop("progress_hooks") + options.get("progress_hooks", [])
        options.update(budget)
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

        candidates = [p for p in candidates if p.suffix.lower() == ".mp3"]
        if len(candidates) == 1:
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
            "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
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
