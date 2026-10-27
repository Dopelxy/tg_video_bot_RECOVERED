import offline_support
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.downloaders import worker
from app.services import download_worker_process as runner
from app.services.process_tree import entry_command
from app.services.worker_errors import WorkerError


class WorkerProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_worker_protocol_with_offline_downloader(self):
        for action in ("youtube_video", "youtube_audio", "instagram_video"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                script = folder / "offline_worker.py"
                script.write_text(
                    f"import sys\nsys.path.insert(0,{str(offline_support.ROOT / 'tests')!r})\n"
                    "import offline_support\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
                    "from app.downloaders.youtube import YouTubeDownloader\n"
                    "from app.downloaders.instagram import InstagramDownloader\n"
                    "from app.downloaders.worker import main\n"
                    f"result=Path({str(folder / 'ready.mp4')!r})\nresult.write_bytes(b'offline-test')\n"
                    "with patch.object(YouTubeDownloader,'_download_video_sync',return_value=result), "
                    "patch.object(YouTubeDownloader,'_download_audio_sync',return_value=result), "
                    "patch.object(InstagramDownloader,'_download_video_sync',return_value=result), "
                    "patch('app.services.media_files.prepare_media',return_value=result):\n    main()\n",
                    encoding="utf-8")
                with patch.object(runner, "entry_command", return_value=entry_command(path=script)):
                    result = await runner.run_download_worker(action, url="https://example.invalid",
                        output_dir=folder, max_height=360, progress=None, timeout=10)
                self.assertEqual(result.read_bytes(), b"offline-test")

    async def run_fake(self, body, *, timeout=5, cancel=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            script = folder / "fake.py"
            script.write_text("import sys,json,time\nfrom pathlib import Path\n"
                              "job=json.loads(sys.stdin.readline())\n" + body, encoding="utf-8")
            with patch.object(runner, "entry_command", return_value=entry_command(path=script)):
                task = asyncio.create_task(runner.run_download_worker(
                    "youtube_video", url="https://example.invalid/test", output_dir=folder,
                    max_height=360, progress=None, timeout=timeout))
                if cancel:
                    await asyncio.sleep(0.15)
                    task.cancel()
                return await task

    async def test_success_owned_process_and_absolute_path(self):
        result = await self.run_fake(
            "p=Path(job['output_dir'])/'ready.mp4'\np.write_bytes(b'test')\n"
            "print(json.dumps({'kind':'result','path':str(p)}),flush=True)\n")
        self.assertTrue(result.is_absolute())

    async def test_timeout(self):
        with self.assertRaises(WorkerError) as caught:
            await self.run_fake("time.sleep(60)\n", timeout=0.15)
        self.assertEqual(caught.exception.code, "timeout")

    async def test_cancel_reaps_process(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.run_fake("time.sleep(60)\n", cancel=True)

    async def test_error_code_and_unknown_text_are_safe(self):
        with self.assertRaises(WorkerError) as caught:
            await self.run_fake("print(json.dumps({'kind':'error','code':'extractor',"
                                "'error_type':'PRIVATE'}),flush=True)\n")
        self.assertEqual(caught.exception.code, "extractor")
        self.assertNotIn("PRIVATE", str(caught.exception))

    async def test_invalid_protocol(self):
        with self.assertRaises(WorkerError) as caught:
            await self.run_fake("print('invalid-json',flush=True)\n")
        self.assertEqual(caught.exception.code, "protocol")

    async def test_unexpected_exit(self):
        with self.assertRaises(WorkerError) as caught:
            await self.run_fake("sys.exit(7)\n")
        self.assertEqual(caught.exception.code, "worker_exit")

    async def test_outside_result_rejected(self):
        with self.assertRaises(WorkerError) as caught:
            await self.run_fake("print(json.dumps({'kind':'result','path':sys.executable}),flush=True)\n")
        self.assertEqual(caught.exception.code, "protocol")


class WorkerRoutingTests(unittest.TestCase):
    def test_video_audio_instagram_dispatch(self):
        from app.downloaders.youtube import YouTubeDownloader
        from app.downloaders.instagram import InstagramDownloader
        for action, cls, method in [
            ("youtube_video", YouTubeDownloader, "_download_video_sync"),
            ("youtube_audio", YouTubeDownloader, "_download_audio_sync"),
            ("instagram_video", InstagramDownloader, "_download_video_sync"),
        ]:
            events = []
            with tempfile.TemporaryDirectory() as directory:
                result = Path(directory) / "result.mp4"
                request = {"action": action, "url": "https://example.invalid", "output_dir": directory,
                           "max_height": 360}
                with patch.object(worker.sys, "stdin", io.StringIO(json.dumps(request))), \
                     patch.object(worker, "emit", side_effect=events.append), \
                     patch.object(worker.shutil, "which", return_value="test-tool"), \
                     patch.object(cls, method, return_value=result) as download, \
                     patch("app.services.media_files.prepare_media", return_value=result):
                    worker.main()
                download.assert_called_once()
                self.assertEqual(events[-1]["kind"], "result")

    def test_metadata_drops_private_format_urls(self):
        from app.downloaders.youtube import YouTubeDownloader
        events = []
        request = {"action": "youtube_metadata", "url": "https://example.invalid", "output_dir": "."}
        with patch.object(worker.sys, "stdin", io.StringIO(json.dumps(request))), \
             patch.object(worker, "emit", side_effect=events.append), \
             patch.object(YouTubeDownloader, "_extract_info_sync", return_value={
                 "title": "test", "formats": [{"height": 360, "url": "PRIVATE", "http_headers": "PRIVATE"}]}):
            worker.main()
        self.assertNotIn("PRIVATE", json.dumps(events))


if __name__ == "__main__":
    unittest.main()
