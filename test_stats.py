import unittest
import tempfile
from pathlib import Path

from app.storage.stats import StatsStorage


class TestStatsStorage(unittest.TestCase):
    def test_instagram_video_counts_toward_platform_and_media_totals(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        db_path = Path(temporary.name) / "stats.db"
        storage = StatsStorage(
            db_path=db_path
        )

        storage.record_instagram_download(
            file_size=10 * 1024 * 1024
        )

        stats = storage.get_stats()

        self.assertEqual(stats.total_downloads, 1)
        self.assertEqual(stats.instagram_downloads, 1)
        self.assertEqual(stats.video_downloads, 1)
        self.assertEqual(stats.total_bytes_sent, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
