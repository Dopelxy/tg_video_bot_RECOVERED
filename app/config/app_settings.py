from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(
    slots=True,
    frozen=True,
)
class AppSettings:
    bot_token: str

    proxy_url: str | None

    max_video_duration_seconds: int
    max_file_size_mb: int
    max_concurrent_downloads: int

    heartbeat_interval_seconds: int
    heartbeat_timeout_seconds: int

    restart_delay_seconds: int
    max_restarts: int
    restart_window_seconds: int


def _get_int(
    name: str,
    default: int,
) -> int:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return default

    try:
        return int(
            raw_value
        )

    except ValueError as error:
        raise RuntimeError(
            f"Переменная {name} "
            "должна быть числом"
        ) from error


def _get_optional_string(
    name: str,
    default: str | None = None,
) -> str | None:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return default

    value = raw_value.strip()

    if not value:
        return None

    return value


BOT_TOKEN = os.getenv(
    "BOT_TOKEN"
)

if not BOT_TOKEN:
    raise RuntimeError(
        "Переменная окружения "
        "BOT_TOKEN не задана"
    )


settings = AppSettings(
    bot_token=BOT_TOKEN,

    proxy_url=_get_optional_string(
        "PROXY_URL",
        "http://127.0.0.1:10809",
    ),

    max_video_duration_seconds=_get_int(
        "MAX_VIDEO_DURATION_SECONDS",
        1800,
    ),

    max_file_size_mb=_get_int(
        "MAX_FILE_SIZE_MB",
        200,
    ),

    max_concurrent_downloads=_get_int(
        "MAX_CONCURRENT_DOWNLOADS",
        2,
    ),

    heartbeat_interval_seconds=_get_int(
        "HEARTBEAT_INTERVAL_SECONDS",
        30,
    ),

    heartbeat_timeout_seconds=_get_int(
        "HEARTBEAT_TIMEOUT_SECONDS",
        300,
    ),

    restart_delay_seconds=_get_int(
        "RESTART_DELAY_SECONDS",
        3,
    ),

    max_restarts=_get_int(
        "MAX_RESTARTS",
        5,
    ),

    restart_window_seconds=_get_int(
        "RESTART_WINDOW_SECONDS",
        600,
    ),
)
