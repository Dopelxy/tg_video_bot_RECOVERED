from app.services.progress import (
    DownloadStage,
    ProgressSnapshot,
)


BAR_LENGTH = 18
TITLE_MAX_LENGTH = 42


def format_bytes(
    value: int | None,
) -> str:
    if value is None:
        return "—"

    mb = value / 1024 / 1024

    if mb < 1024:
        return f"{mb:.1f} МБ"

    gb = mb / 1024

    return f"{gb:.2f} ГБ"


def format_speed(
    value: float | None,
) -> str:
    if value is None:
        return "—"

    mb_per_second = (
        value
        / 1024
        / 1024
    )

    return f"{mb_per_second:.1f} МБ/с"


def format_eta(
    seconds: int | None,
) -> str:
    if seconds is None:
        return "—"

    if seconds < 60:
        return f"~{seconds} сек"

    minutes, secs = divmod(
        seconds,
        60,
    )

    return (
        f"~{minutes} мин "
        f"{secs:02d} сек"
    )


def format_elapsed(
    seconds: float,
) -> str:
    total_seconds = int(
        max(
            seconds,
            0,
        )
    )

    if total_seconds < 60:
        return f"{total_seconds} сек"

    minutes, secs = divmod(
        total_seconds,
        60,
    )

    return (
        f"{minutes} мин "
        f"{secs:02d} сек"
    )


def shorten_title(
    title: str,
) -> str:
    clean_title = " ".join(
        title.split()
    )

    if len(clean_title) <= TITLE_MAX_LENGTH:
        return clean_title

    return (
        clean_title[
            : TITLE_MAX_LENGTH - 3
        ]
        + "..."
    )


def progress_bar(
    percent: float,
) -> str:
    safe_percent = max(
        0.0,
        min(
            percent,
            100.0,
        ),
    )

    filled = int(
        BAR_LENGTH
        * safe_percent
        / 100
    )

    empty = (
        BAR_LENGTH
        - filled
    )

    if filled >= BAR_LENGTH:
        return "━" * BAR_LENGTH

    return (
        "━" * filled
        + "╸"
        + "─" * max(
            empty - 1,
            0,
        )
    )


def stage_title(
    stage: DownloadStage,
) -> str:
    titles = {
        DownloadStage.PREPARING:
            "◌ ПОДГОТОВКА",

        DownloadStage.DOWNLOADING:
            "◉ ЗАГРУЗКА",

        DownloadStage.PROCESSING:
            "◈ ОБРАБОТКА",

        DownloadStage.UPLOADING:
            "◇ ОТПРАВКА",

        DownloadStage.COMPLETE:
            "◆ ГОТОВО",

        DownloadStage.FAILED:
            "× ОШИБКА",
    }

    return titles[stage]


def render_header(
    bot_name: str,
    bot_username: str,
) -> str:
    username = bot_username.lstrip("@")

    return (
        f"◆ {bot_name}\n"
        f"  @{username}"
    )


def render_progress(
    *,
    title: str,
    format_name: str,
    bot_name: str,
    bot_username: str,
    snapshot: ProgressSnapshot,
) -> str:
    display_title = shorten_title(
        title
    )

    stage = stage_title(
        snapshot.stage
    )

    bar = progress_bar(
        snapshot.percent
    )

    percent = (
        f"{snapshot.percent:.0f}%"
    )

    downloaded = format_bytes(
        snapshot.downloaded_bytes
    )

    total = format_bytes(
        snapshot.total_bytes
    )

    speed = format_speed(
        snapshot.speed_bytes_per_second
    )

    eta = format_eta(
        snapshot.eta_seconds
    )

    return (
        f"{render_header(bot_name, bot_username)}"
        "\n\n"
        "╭────────────────────\n"
        f"│ {display_title}\n"
        "│\n"
        f"│ ◈ {format_name}\n"
        "│\n"
        f"│ {stage}  {percent}\n"
        f"│ {bar}\n"
        "│\n"
        f"│ {downloaded} / {total}\n"
        f"│ ⌁ {speed}   ◷ {eta}\n"
        "╰────────────────────\n"
        f"  {snapshot.status_text}"
    )


def render_complete(
    *,
    title: str,
    format_name: str,
    bot_name: str,
    bot_username: str,
    file_size: int,
    snapshot: ProgressSnapshot,
) -> str:
    display_title = shorten_title(
        title
    )

    return (
        f"{render_header(bot_name, bot_username)}"
        "\n\n"
        "╭────────────────────\n"
        f"│ {display_title}\n"
        "│\n"
        f"│ ◈ {format_name}\n"
        f"│ ⟡ {format_bytes(file_size)}\n"
        f"│ ◷ {format_elapsed(snapshot.elapsed_seconds)}\n"
        "│\n"
        "│ ◆ ГОТОВО\n"
        "╰────────────────────\n"
        "  ✓ Файл отправлен"
    )
