import offline_support
import asyncio
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services import job_files, local_ipc, media_files
from app.services.download_coordinator import DownloadCoordinator
from app.services.instance_lock import token_instance, InstanceBusy
from app.services.request_cache import RequestCache
from app.services.telegram_io import StatusEditor
from app.services.worker_errors import WorkerError
from app.storage import stats
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.methods import EditMessageText


class LocalStateTests(unittest.TestCase):
    def test_cache_ttl_and_capacity(self):
        now = [0]
        cache = RequestCache(ttl=10, capacity=2, clock=lambda: now[0])
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3
        self.assertIsNone(cache.get("a"))
        now[0] = 10
        self.assertIsNone(cache.get("b"))

    def test_stats_lazy_and_connections_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new" / "test.db"
            storage = stats.StatsStorage(path)
            self.assertFalse(path.parent.exists())
            storage.record_video_download(10)
            storage.record_audio_download(20)
            storage.record_instagram_download(30)
            storage.record_failure()
            result = storage.get_stats()
            self.assertEqual((result.total_downloads, result.youtube_downloads,
                              result.instagram_downloads, result.failed_downloads,
                              result.total_bytes_sent), (3, 2, 1, 1, 60))
            with storage._connect() as conn:
                pass
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_job_cleanup_on_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                with job_files.managed_job(root=root) as folder:
                    (folder / "part").write_bytes(b"test")
                    raise ValueError()
            self.assertFalse(folder.exists())

    def test_sweep_preserves_live_and_unmarked_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with job_files.managed_job(root=root) as live:
                unmarked = root / "managed" / ("a" * 32)
                unmarked.mkdir()
                abandoned = root / "managed" / ("b" * 32)
                abandoned.mkdir()
                (abandoned / ".lease").touch()
                job_files.sweep(root, max_age=-1)
                self.assertTrue(live.exists())
                self.assertTrue(unmarked.exists())
                self.assertFalse(abandoned.exists())

    def test_token_lock_released_after_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            with token_instance("fake-test-identity", directory=directory):
                with self.assertRaises(InstanceBusy):
                    with token_instance("fake-test-identity", directory=directory):
                        self.fail("second owner")
                with token_instance("another-test-identity", directory=directory):
                    pass
            with token_instance("fake-test-identity", directory=directory):
                pass


class AsyncStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_limits_and_release(self):
        coordinator = DownloadCoordinator(2)
        coordinator.max_jobs = 2
        self.assertTrue(coordinator.claim_user(1))
        self.assertFalse(coordinator.claim_user(1))
        self.assertTrue(coordinator.claim_user(2))
        self.assertFalse(coordinator.claim_user(3))
        coordinator.release_user(1)
        self.assertTrue(coordinator.claim_user(3))
        for semaphore in [coordinator.metadata_semaphore, coordinator.upload_semaphore]:
            active = 0
            peak = 0
            async def operation():
                nonlocal active, peak
                async with semaphore:
                    active += 1
                    peak = max(peak, active)
                    await asyncio.sleep(0.005)
                    active -= 1
            await asyncio.gather(*(operation() for _ in range(8)))
            self.assertEqual(peak, 2)

    async def test_stats_error_is_nonfatal(self):
        with patch.object(stats.stats_storage, "record_video_download", side_effect=OSError("PRIVATE")):
            self.assertFalse(await stats.record_safely("record_video_download", file_size=10))

    async def test_status_retry_after_cooldown(self):
        message = SimpleNamespace(edit_text=AsyncMock(side_effect=TelegramRetryAfter(
            method=EditMessageText(text="test"), message="limited", retry_after=30)))
        editor = StatusEditor(message)
        await editor.edit("first")
        await editor.edit("second")
        self.assertEqual(message.edit_text.await_count, 1)

    async def test_status_permanent_error_disables_updates(self):
        message = SimpleNamespace(edit_text=AsyncMock(side_effect=TelegramBadRequest(
            method=EditMessageText(text="test"), message="deleted")))
        editor = StatusEditor(message)
        await editor.edit("first")
        await editor.edit("second")
        self.assertEqual(message.edit_text.await_count, 1)

    async def test_unchanged_status_is_success_not_permanent_failure(self):
        message = SimpleNamespace(edit_text=AsyncMock(side_effect=[TelegramBadRequest(
            method=EditMessageText(text="test"), message="message is not modified"), None]))
        editor = StatusEditor(message)
        self.assertTrue(await editor.edit("same"))
        self.assertTrue(await editor.edit("next"))
        self.assertFalse(editor.disabled)


class IPCTests(unittest.TestCase):
    def test_listener_releases_stalled_authentication_socket(self):
        listener = local_ipc.Listener.__new__(local_ipc.Listener)
        listener.key = b"synthetic-test-key"
        listener.socket = Mock()
        sock = Mock()
        listener.socket.accept.return_value = (sock, ("127.0.0.1", 1))
        with patch.object(local_ipc.Connection, "send"), \
             patch.object(local_ipc.Connection, "recv", side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                listener.accept()
        sock.close.assert_called_once()

    def test_service_continues_after_silent_client(self):
        import local_agent
        silent = Mock()
        silent.recv.side_effect = TimeoutError()
        silent.__enter__ = Mock(return_value=silent)
        silent.__exit__ = Mock(return_value=None)
        shutdown = Mock()
        shutdown.recv.return_value = "shutdown"
        shutdown.__enter__ = Mock(return_value=shutdown)
        shutdown.__exit__ = Mock(return_value=None)
        listener = Mock()
        listener.accept.side_effect = [silent, shutdown]
        listener.__enter__ = Mock(return_value=listener)
        listener.__exit__ = Mock(return_value=None)
        runtime = Mock(pid=None)
        runtime.stop.return_value = True
        with patch.object(local_agent, "_load_authkey", return_value=b"test-only"), \
             patch.object(local_agent, "Listener", return_value=listener), \
             patch.object(local_agent, "BotProcess", return_value=runtime):
            local_agent.serve(Path("test-only-unused"))
        shutdown.send.assert_called_once_with({"ok": True, "launcher_pid": None})
        runtime.start.assert_not_called()

    def test_frame_size_and_timeout(self):
        sock = Mock()
        sock.recv.return_value = (local_ipc.MAX_FRAME + 1).to_bytes(4, "big")
        with self.assertRaises(ValueError):
            local_ipc.Connection(sock).recv()
        sock.recv.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            local_ipc.Connection(sock).recv()

    def test_fragmented_json_frame(self):
        data = json.dumps({"ok": True}).encode()
        sock = Mock()
        sock.recv.side_effect = [len(data).to_bytes(4, "big")[:2],
                                 len(data).to_bytes(4, "big")[2:], data[:3], data[3:]]
        self.assertEqual(local_ipc.Connection(sock).recv(), {"ok": True})

    def test_client_mutual_authentication_and_response_deadline(self):
        key = b"synthetic-test-key"
        own = "b" * 64
        with patch.object(local_ipc.socket, "create_connection", return_value=Mock()) as connect, \
             patch.object(local_ipc.secrets, "token_hex", return_value=own), \
             patch.object(local_ipc.Connection, "recv", side_effect=["a" * 64, local_ipc._digest(key, own)]), \
             patch.object(local_ipc.Connection, "send"):
            with local_ipc.Client(("127.0.0.1", 1), authkey=key) as conn:
                self.assertEqual(conn.timeout, local_ipc.RESPONSE_TIMEOUT)
            self.assertEqual(connect.call_args.kwargs["timeout"], local_ipc.CONNECT_TIMEOUT)

    def test_fake_server_rejected(self):
        sock = Mock()
        with patch.object(local_ipc.socket, "create_connection", return_value=sock), \
             patch.object(local_ipc.Connection, "recv", side_effect=["a" * 64, "wrong-proof"]), \
             patch.object(local_ipc.Connection, "send"):
            with self.assertRaises(ConnectionError):
                local_ipc.Client(("127.0.0.1", 1), authkey=b"test-only")
            sock.close.assert_called_once()


class MediaTests(unittest.TestCase):
    def test_size_and_disk_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkerError) as caught:
                media_files.check_budget(directory, estimated=media_files.max_bytes() + 1)
            self.assertEqual(caught.exception.code, "size_limit")
            with patch.object(media_files.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
                with self.assertRaises(WorkerError) as caught:
                    media_files.check_budget(directory)
                self.assertEqual(caught.exception.code, "disk_limit")

    def test_combined_stream_estimate_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            options = media_files.download_options(directory)
            with self.assertRaises(WorkerError):
                options["match_filter"]({"requested_formats": [
                    {"filesize": media_files.max_bytes()}, {"filesize": 1}]})

    def test_fragment_limit_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            hook = media_files.download_options(directory)["progress_hooks"][0]
            with self.assertRaises(WorkerError):
                hook({"downloaded_bytes": media_files.max_bytes() + 1})

    def test_truncated_conversion_never_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.webm"
            source.write_bytes(b"test")
            def convert(*args, **kwargs):
                source.with_name("telegram_ready.mp4").write_bytes(b"test")
            with patch.object(media_files, "probe", side_effect=[
                {"format": {"format_name": "webm", "duration": "100"}},
                {"format": {"format_name": "mp4", "duration": "10"}, "streams": [
                    {"codec_type": "video", "codec_name": "h264"}]}]), \
                 patch.object(media_files.subprocess, "run", side_effect=convert):
                with self.assertRaises(WorkerError) as caught:
                    media_files.prepare_media(source)
                self.assertEqual(caught.exception.code, "size_limit")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools")
    def test_real_local_video_and_audio_conversion(self):
        # Synthetic lavfi sources only: no URL, device or user media.
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "synthetic.avi"
            audio = Path(directory) / "synthetic.m4a"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=64x64:r=10", "-t", "0.5", "-c:v", "mpeg4", str(video)],
                           check=True, timeout=20, capture_output=True)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440", "-t", "0.5", "-c:a", "aac", str(audio)],
                           check=True, timeout=20, capture_output=True)
            prepared_video = media_files.prepare_media(video)
            prepared_audio = media_files.prepare_media(audio, audio=True)
            self.assertTrue(media_files.compatible(media_files.probe(prepared_video), False))
            self.assertTrue(media_files.compatible(media_files.probe(prepared_audio), True))


if __name__ == "__main__":
    unittest.main()
