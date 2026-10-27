import offline_support
import asyncio
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.handlers import youtube, instagram
from app.models.bot_identity import BotIdentity
from app.services import job_files
from app.services.worker_errors import WorkerError
from app.storage import stats


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_delivery_survives_statistics_failure_and_cleans_files(self):
        for action in ("video", "audio", "instagram"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                status = SimpleNamespace(edit_text=AsyncMock())
                message = SimpleNamespace(text="https://www.instagram.com/reel/test/",
                    from_user=SimpleNamespace(id=123), bot=object(),
                    answer=AsyncMock(return_value=status), answer_video=AsyncMock(), answer_audio=AsyncMock())
                callback = SimpleNamespace(message=message, from_user=message.from_user, bot=message.bot,
                    data="yta:card" if action == "audio" else "ytq:card:360", answer=AsyncMock())
                youtube.youtube_requests["card"] = {"user_id": 123, "url": "https://youtu.be/test",
                                                     "title": "Test", "uploader": "Author"}
                paths = []
                async def downloaded(*args, **kwargs):
                    path = kwargs["output_dir"] / ("ready.mp3" if action == "audio" else "ready.mp4")
                    path.write_bytes(b"test-file")
                    paths.append(path)
                    return path
                original_job = job_files.managed_job
                module = instagram if action == "instagram" else youtube
                downloader = instagram.instagram_downloader if action == "instagram" else youtube.youtube_downloader
                method = "download_audio" if action == "audio" else "download_video"
                record = "record_instagram_download" if action == "instagram" else "record_" + action + "_download"
                with patch.object(job_files, "managed_job", side_effect=lambda: original_job(root=Path(directory))), \
                     patch.object(module, "load_bot_identity", AsyncMock(return_value=BotIdentity("Test", "test_bot"))), \
                     patch.object(downloader, method, side_effect=downloaded), \
                     patch.object(stats.stats_storage, record, side_effect=OSError("synthetic DB failure")), \
                     patch.object(stats.stats_storage, "record_failure") as failure:
                    if action == "instagram":
                        with patch.object(downloader, "get_metadata", AsyncMock(return_value=SimpleNamespace(
                            media_type="video", uploader="Test"))):
                            await instagram.instagram_link_handler(message)
                    elif action == "video":
                        await youtube.youtube_quality_handler(callback)
                    else:
                        await youtube.youtube_audio_handler(callback)
                    failure.assert_not_called()
                sent = message.answer_audio if action == "audio" else message.answer_video
                sent.assert_awaited_once()
                self.assertEqual(sent.call_args.kwargs["request_timeout"], 600)
                self.assertTrue(paths)
                self.assertFalse(paths[0].parent.exists())
                self.assertNotIn(123, module.download_coordinator._active_users)
                edits = [call.args[0] for call in status.edit_text.call_args_list]
                self.assertFalse(any("Временные файлы очищены" in text for text in edits))
                self.assertFalse(any("внутренняя ошибка" in text.lower() for text in edits))

    async def test_metadata_one_extraction_per_card(self):
        info = {"title": "Test", "duration": 10, "formats": [
            {"format_id": "test", "height": 360, "vcodec": "h264", "ext": "mp4"}]}
        with patch("app.downloaders.youtube.run_download_worker", AsyncMock(return_value=info)) as worker:
            metadata, formats = await youtube.youtube_downloader.get_details("https://youtu.be/test")
        worker.assert_awaited_once()
        self.assertEqual(metadata.title, "Test")
        self.assertEqual(formats[0].height, 360)

    async def test_youtube_download_keeps_worker_code(self):
        with tempfile.TemporaryDirectory() as directory:
            for method in ("download_video", "download_audio"):
                with self.subTest(method=method), patch("app.downloaders.youtube.run_download_worker",
                    AsyncMock(side_effect=WorkerError("ffmpeg_missing"))):
                    kwargs = {"url": "https://youtu.be/test", "output_dir": Path(directory)}
                    if method == "download_video":
                        kwargs["max_height"] = 360
                    with self.assertRaises(WorkerError) as caught:
                        await getattr(youtube.youtube_downloader, method)(**kwargs)
                    self.assertEqual(caught.exception.code, "ffmpeg_missing")

    async def test_metadata_exception_releases_user(self):
        status = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(text="https://youtu.be/test", from_user=SimpleNamespace(id=321),
                                  answer=AsyncMock(return_value=status))
        with patch.object(youtube.youtube_downloader, "get_details", AsyncMock(side_effect=WorkerError("timeout"))):
            await youtube.youtube_link_handler(message)
        self.assertNotIn(321, youtube.download_coordinator._active_users)
        self.assertIn("время", status.edit_text.call_args.args[0].lower())


class GUIContractTests(unittest.TestCase):
    def test_supported_entry_modules_import_without_live_runtime(self):
        # Module import only: no QApplication, Listener or bot polling invocation.
        import importlib
        for module in ("main", "launcher", "gui_agent", "gui", "local_agent"):
            importlib.import_module(module)

    def test_widgets_never_call_ipc_request_directly(self):
        tree = ast.parse((offline_support.ROOT / "gui_agent.py").read_text(encoding="utf-8"))
        calls = []
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
                for node in ast.walk(method):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "request":
                        calls.append((cls.name, method.name))
        self.assertEqual(calls, [("CommandThread", "run")])


if __name__ == "__main__":
    unittest.main()
