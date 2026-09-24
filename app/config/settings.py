import os

from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv(
    "PROXY_URL",
    "http://127.0.0.1:10809",
)

MAX_VIDEO_DURATION_SECONDS = int(
    os.getenv(
        "MAX_VIDEO_DURATION_SECONDS",
        "1800",
    )
)

MAX_FILE_SIZE_MB = int(
    os.getenv(
        "MAX_FILE_SIZE_MB",
        "200",
    )
)

MAX_CONCURRENT_DOWNLOADS = int(
    os.getenv(
        "MAX_CONCURRENT_DOWNLOADS",
        "2",
    )
)


if not BOT_TOKEN:
    raise RuntimeError(
        "Переменная окружения BOT_TOKEN не задана"
    )