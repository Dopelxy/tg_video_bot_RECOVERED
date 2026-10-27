"""Deliberately allowlisted diagnostics: never return extractor exception text."""
import errno

MESSAGES = {
    "duration_limit": "Превышена допустимая длительность",
    "size_limit": "Превышен допустимый размер файла",
    "disk_limit": "Недостаточно свободного места для задания",
    "ffmpeg_missing": "Не найден FFmpeg или ffprobe",
    "media_invalid": "Не удалось подготовить совместимый медиафайл",
    "network": "Сетевая ошибка загрузчика",
    "filesystem": "Ошибка доступа к локальным файлам",
    "extractor": "Источник не вернул доступный медиафайл",
    "quality_unavailable": "Выбранное качество недоступно. Отправь ссылку ещё раз.",
    "timeout": "Превышено время выполнения задания",
    "protocol": "Нарушен протокол дочернего процесса",
    "worker_exit": "Дочерний процесс завершился без результата",
    "internal": "Внутренняя ошибка загрузчика",
}


class WorkerError(RuntimeError):
    def __init__(self, code="internal", error_type="unknown"):
        self.code = code if code in MESSAGES else "internal"
        self.error_type = error_type if error_type in {
            "DownloadError", "PostProcessingError", "TimeoutError", "OSError",
            "YouTubeDurationLimitError", "InstagramDurationLimitError",
            "YouTubeMetadataError", "InstagramMetadataError", "WorkerError",
        } else "unknown"
        super().__init__(MESSAGES[self.code])


def classify(error):
    current = error
    seen = set()
    for _ in range(8):
        if id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, WorkerError):
            return current
        name = type(current).__name__
        if "DurationLimit" in name:
            return WorkerError("duration_limit", name)
        if "FileSizeLimit" in name:
            return WorkerError("size_limit", name)
        if isinstance(current, TimeoutError):
            return WorkerError("timeout", "TimeoutError")
        if isinstance(current, OSError):
            code = "filesystem"
            if current.errno == errno.ENOSPC:
                code = "disk_limit"
            elif current.errno in {errno.ETIMEDOUT, errno.ECONNRESET, errno.ENETUNREACH,
                                   errno.ECONNREFUSED, errno.EHOSTUNREACH}:
                code = "network"
            return WorkerError(code, "OSError")
        details = getattr(current, "exc_info", None)
        nested = details[1] if isinstance(details, tuple) and len(details) > 1 else None
        next_error = current.__cause__ or nested or current.__context__
        if not isinstance(next_error, BaseException) or id(next_error) in seen:
            break
        current = next_error
    name = type(current).__name__
    # Match known diagnostic markers internally; never copy raw text to output.
    detail = str(current).lower()
    if "requested format is not available" in detail:
        return WorkerError("quality_unavailable", name)
    if "ffmpeg" in detail and any(t in detail for t in ("not found", "not installed", "не найден")):
        return WorkerError("ffmpeg_missing", name)
    if name == "PostProcessingError":
        return WorkerError("media_invalid", name)
    if name in {"DownloadError", "YouTubeMetadataError", "InstagramMetadataError"}:
        return WorkerError("extractor", name)
    return WorkerError("internal", name)
