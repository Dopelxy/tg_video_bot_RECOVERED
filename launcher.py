import logging
import subprocess
import sys
import time
from pathlib import Path

from app.config.app_settings import settings


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(
    "watchdog"
)


PROJECT_DIR = Path(__file__).parent

MAIN_FILE = (
    PROJECT_DIR
    / "main.py"
)

HEARTBEAT_FILE = (
    PROJECT_DIR
    / "data"
    / "bot_heartbeat.txt"
)


CHECK_INTERVAL_SECONDS = 5

RETRY_PAUSE_SECONDS = (
    15 * 60
)


def clear_old_heartbeat() -> None:
    try:
        HEARTBEAT_FILE.unlink(
            missing_ok=True
        )

    except OSError:
        logger.exception(
            "Не удалось удалить "
            "старый heartbeat-файл"
        )


def start_bot() -> tuple[
    subprocess.Popen,
    float,
]:
    clear_old_heartbeat()

    logger.info(
        "Запускаю процесс бота..."
    )

    process = subprocess.Popen(
        [
            sys.executable,
            str(MAIN_FILE),
        ],
        cwd=str(PROJECT_DIR),
    )

    started_at = time.time()

    logger.info(
        "Бот запущен. PID=%s",
        process.pid,
    )

    return (
        process,
        started_at,
    )


def stop_bot(
    process: subprocess.Popen,
) -> None:
    if process.poll() is not None:
        return

    logger.warning(
        "Останавливаю процесс "
        "бота PID=%s",
        process.pid,
    )

    process.terminate()

    try:
        process.wait(
            timeout=10
        )

    except subprocess.TimeoutExpired:
        logger.warning(
            "Бот не завершился. "
            "Убиваю процесс."
        )

        process.kill()
        process.wait()


def heartbeat_is_stale(
    *,
    process_started_at: float,
) -> bool:
    if not HEARTBEAT_FILE.exists():
        age_without_heartbeat = (
            time.time()
            - process_started_at
        )

        return (
            age_without_heartbeat
            > settings.heartbeat_timeout_seconds
        )

    try:
        modified_time = (
            HEARTBEAT_FILE
            .stat()
            .st_mtime
        )

    except OSError:
        logger.exception(
            "Не удалось прочитать "
            "heartbeat-файл"
        )

        return False

    heartbeat_age = (
        time.time()
        - modified_time
    )

    return (
        heartbeat_age
        > settings.heartbeat_timeout_seconds
    )


def clean_old_restarts(
    restart_times: list[float],
) -> None:
    now = time.time()

    restart_times[:] = [
        restart_time
        for restart_time
        in restart_times
        if (
            now
            - restart_time
            <= settings.restart_window_seconds
        )
    ]


def restart_limit_reached(
    restart_times: list[float],
) -> bool:
    clean_old_restarts(
        restart_times
    )

    return (
        len(restart_times)
        >= settings.max_restarts
    )


def register_restart(
    restart_times: list[float],
) -> None:
    restart_times.append(
        time.time()
    )


def wait_for_retry_cycle() -> None:
    logger.warning(
        "Лимит быстрых рестартов исчерпан."
    )

    logger.warning(
        "Пауза %s минут перед "
        "новой серией попыток.",
        RETRY_PAUSE_SECONDS // 60,
    )

    time.sleep(
        RETRY_PAUSE_SECONDS
    )

    logger.info(
        "Пауза завершена. "
        "Начинаю новую серию рестартов."
    )


def restart_bot(
    *,
    process: subprocess.Popen,
    restart_times: list[float],
) -> tuple[
    subprocess.Popen,
    float,
]:
    if restart_limit_reached(
        restart_times
    ):
        stop_bot(
            process
        )

        wait_for_retry_cycle()

        restart_times.clear()

    else:
        register_restart(
            restart_times
        )

        logger.warning(
            "Перезапуск через %s сек...",
            settings.restart_delay_seconds,
        )

        time.sleep(
            settings.restart_delay_seconds
        )

    return start_bot()


def main() -> None:
    logger.info(
        "WATCHDOG запущен"
    )

    logger.info(
        "Heartbeat timeout: %s сек.",
        settings.heartbeat_timeout_seconds,
    )

    logger.info(
        "Быстрых рестартов: %s "
        "за %s сек.",
        settings.max_restarts,
        settings.restart_window_seconds,
    )

    logger.info(
        "Пауза между сериями: %s мин.",
        RETRY_PAUSE_SECONDS // 60,
    )

    restart_times: list[float] = []

    process, process_started_at = (
        start_bot()
    )

    try:
        while True:
            exit_code = process.poll()

            if exit_code is not None:
                logger.error(
                    "Процесс бота завершился. "
                    "Код=%s",
                    exit_code,
                )

                (
                    process,
                    process_started_at,
                ) = restart_bot(
                    process=process,
                    restart_times=restart_times,
                )

                continue

            if heartbeat_is_stale(
                process_started_at=(
                    process_started_at
                )
            ):
                logger.error(
                    "Heartbeat не обновлялся "
                    "более %s сек. "
                    "Бот считается зависшим.",
                    settings.heartbeat_timeout_seconds,
                )

                stop_bot(
                    process
                )

                (
                    process,
                    process_started_at,
                ) = restart_bot(
                    process=process,
                    restart_times=restart_times,
                )

                continue

            time.sleep(
                CHECK_INTERVAL_SECONDS
            )

    except KeyboardInterrupt:
        logger.info(
            "Получена команда остановки"
        )

    finally:
        stop_bot(
            process
        )

        logger.info(
            "WATCHDOG остановлен"
        )


if __name__ == "__main__":
    main()