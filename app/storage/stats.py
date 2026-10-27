from dataclasses import dataclass
from pathlib import Path
from threading import Lock
import sqlite3
import asyncio
import logging
from contextlib import contextmanager
from app.paths import DATA_DIR

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStats:
    total_downloads: int
    youtube_downloads: int
    instagram_downloads: int
    video_downloads: int
    audio_downloads: int
    failed_downloads: int
    total_bytes_sent: int


class StatsStorage:
    def __init__(
        self,
        db_path: Path,
    ) -> None:
        self._db_path = db_path
        self._lock = Lock()

        self._initialized = False

    @contextmanager
    def _connect(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path, timeout=1
        )

        connection.row_factory = sqlite3.Row

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_database(
        self,
    ) -> None:
        with self._lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stats (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        total_downloads INTEGER NOT NULL DEFAULT 0,
                        youtube_downloads INTEGER NOT NULL DEFAULT 0,
                        instagram_downloads INTEGER NOT NULL DEFAULT 0,
                        video_downloads INTEGER NOT NULL DEFAULT 0,
                        audio_downloads INTEGER NOT NULL DEFAULT 0,
                        failed_downloads INTEGER NOT NULL DEFAULT 0,
                        total_bytes_sent INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )

                self._ensure_column(
                    connection=connection,
                    column_name="youtube_downloads",
                )

                self._ensure_column(
                    connection=connection,
                    column_name="instagram_downloads",
                )

                connection.execute(
                    """
                    INSERT OR IGNORE INTO stats (
                        id,
                        total_downloads,
                        youtube_downloads,
                        instagram_downloads,
                        video_downloads,
                        audio_downloads,
                        failed_downloads,
                        total_bytes_sent
                    )
                    VALUES (
                        1,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0
                    )
                    """
                )

                connection.commit()
            self._initialized = True

    def _ensure_column(
        self,
        *,
        connection: sqlite3.Connection,
        column_name: str,
    ) -> None:
        columns = connection.execute(
            """
            PRAGMA table_info(stats)
            """
        ).fetchall()

        existing_columns = {
            row["name"]
            for row in columns
        }

        if column_name in existing_columns:
            return

        allowed_columns = {
            "youtube_downloads",
            "instagram_downloads",
        }

        if column_name not in allowed_columns:
            raise ValueError(
                "Недопустимое имя столбца"
            )

        connection.execute(
            f"""
            ALTER TABLE stats
            ADD COLUMN {column_name}
            INTEGER NOT NULL DEFAULT 0
            """
        )

    def record_video_download(
        self,
        file_size: int,
    ) -> None:
        self._initialize_database()
        safe_file_size = max(
            int(file_size),
            0,
        )

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE stats
                    SET
                        total_downloads =
                            total_downloads + 1,
                        youtube_downloads =
                            youtube_downloads + 1,
                        video_downloads =
                            video_downloads + 1,
                        total_bytes_sent =
                            total_bytes_sent + ?
                    WHERE id = 1
                    """,
                    (safe_file_size,),
                )

                connection.commit()

    def record_audio_download(
        self,
        file_size: int,
    ) -> None:
        self._initialize_database()
        safe_file_size = max(
            int(file_size),
            0,
        )

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE stats
                    SET
                        total_downloads =
                            total_downloads + 1,
                        youtube_downloads =
                            youtube_downloads + 1,
                        audio_downloads =
                            audio_downloads + 1,
                        total_bytes_sent =
                            total_bytes_sent + ?
                    WHERE id = 1
                    """,
                    (safe_file_size,),
                )

                connection.commit()

    def record_instagram_download(
        self,
        file_size: int,
    ) -> None:
        self._initialize_database()
        safe_file_size = max(
            int(file_size),
            0,
        )

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE stats
                    SET
                        total_downloads =
                            total_downloads + 1,
                        instagram_downloads =
                            instagram_downloads + 1,
                        video_downloads =
                            video_downloads + 1,
                        total_bytes_sent =
                            total_bytes_sent + ?
                    WHERE id = 1
                    """,
                    (safe_file_size,),
                )

                connection.commit()

    def record_failure(
        self,
    ) -> None:
        self._initialize_database()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE stats
                    SET
                        failed_downloads =
                            failed_downloads + 1
                    WHERE id = 1
                    """
                )

                connection.commit()

    def get_stats(
        self,
    ) -> BotStats:
        self._initialize_database()
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        total_downloads,
                        youtube_downloads,
                        instagram_downloads,
                        video_downloads,
                        audio_downloads,
                        failed_downloads,
                        total_bytes_sent
                    FROM stats
                    WHERE id = 1
                    """
                ).fetchone()

        if row is None:
            raise RuntimeError(
                "Не удалось прочитать статистику"
            )

        return BotStats(
            total_downloads=int(
                row["total_downloads"]
            ),
            youtube_downloads=int(
                row["youtube_downloads"]
            ),
            instagram_downloads=int(
                row["instagram_downloads"]
            ),
            video_downloads=int(
                row["video_downloads"]
            ),
            audio_downloads=int(
                row["audio_downloads"]
            ),
            failed_downloads=int(
                row["failed_downloads"]
            ),
            total_bytes_sent=int(
                row["total_bytes_sent"]
            ),
        )


stats_storage = StatsStorage(
    db_path=DATA_DIR / "stats.db"
)

async def record_safely(method, **kwargs):
    try:
        await asyncio.to_thread(getattr(stats_storage, method), **kwargs)
        return True
    except Exception as error:
        logger.warning("Статистика не записана: operation=%s type=%s", method, type(error).__name__)
        return False
