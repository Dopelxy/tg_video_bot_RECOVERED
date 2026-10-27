import offline_support
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yt_dlp
from app.downloaders import worker
from app.downloaders.youtube import YouTubeDownloader, video_format_selector, selected_height
from app.handlers.youtube import build_quality_keyboard
from app.services.worker_errors import WorkerError, classify


def video(height, *, codec="avc1.640028", audio="none", ext="mp4", suffix=""):
    return {"format_id": f"video-{height}{suffix}", "height": height, "vcodec": codec,
            "acodec": audio, "ext": ext, "url": "https://example.invalid/video"}


def audio():
    return {"format_id": "audio", "vcodec": "none", "acodec": "mp4a.40.2",
            "ext": "m4a", "url": "https://example.invalid/audio"}


class QualityPipelineTests(unittest.TestCase):
    def pipeline(self, formats):
        info = {"title": "Offline test", "duration": 10, "formats": formats}
        capture = io.StringIO()
        request = {"action": "youtube_metadata", "url": "https://youtu.be/test", "output_dir": "."}
        with patch.object(YouTubeDownloader, "_extract_info_sync", return_value=info), \
             patch.object(worker.sys, "stdin", io.StringIO(json.dumps(request))), \
             patch.object(worker.sys, "__stdout__", capture):
            worker.main()
        event = json.loads(capture.getvalue())
        self.assertEqual(event["kind"], "result")
        received = event["data"]
        parsed = YouTubeDownloader()._formats_from_info(received)
        keyboard = build_quality_keyboard({f.height for f in parsed}, "card")
        buttons = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        return received, buttons

    def test_full_set_float_heights_survive_worker_and_keyboard(self):
        received, buttons = self.pipeline([video(360.0), video(720.0), video(1080), audio()])
        self.assertIsInstance(received["formats"][0]["height"], float)
        self.assertEqual(buttons, ["ytq:card:360", "ytq:card:720", "ytq:card:1080", "yta:card"])

    def test_full_set_integer_heights(self):
        _, buttons = self.pipeline([video(h) for h in (360, 720, 1080)] + [audio()])
        self.assertEqual(buttons, ["ytq:card:360", "ytq:card:720", "ytq:card:1080", "yta:card"])

    def test_partial_set_has_no_invented_quality(self):
        for heights in [(360, 1080), (720,), (1080,), (360, 720)]:
            with self.subTest(heights=heights):
                _, buttons = self.pipeline([video(h) for h in heights] + [audio()])
                self.assertEqual(buttons, [f"ytq:card:{h}" for h in heights] + ["yta:card"])

    def test_missing_formats_keep_audio_button(self):
        for formats in (None, [], [audio()]):
            with self.subTest(formats=formats):
                _, buttons = self.pipeline(formats)
                self.assertEqual(buttons, ["yta:card"])

    def test_worker_does_not_silently_truncate_formats(self):
        formats = [dict(audio(), format_id=f"audio-{i}") for i in range(501)]
        formats += [video(h) for h in (360, 720, 1080)]
        received, buttons = self.pipeline(formats)
        self.assertEqual(len(received["formats"]), len(formats))
        self.assertEqual(buttons, ["ytq:card:360", "ytq:card:720", "ytq:card:1080", "yta:card"])

    def test_invalid_height_and_non_video_are_not_qualities(self):
        formats = [video(h, suffix=str(i)) for i, h in enumerate(
            [None, True, 359.9, "720p", float("nan"), float("inf"), -360, 0])]
        formats += [dict(video(720), vcodec="none"), dict(video(360), format_id="")]
        formats += [video("360"), video("720.0"), video(1080.0)]
        _, buttons = self.pipeline(formats)
        self.assertEqual(buttons, ["ytq:card:360", "ytq:card:720", "ytq:card:1080", "yta:card"])


class ExactSelectionTests(unittest.TestCase):
    def select(self, formats, height):
        # Run the installed yt-dlp selector on fixtures, without invoking extractors.
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}, auto_init=False) as ydl:
            return ydl._select_formats(formats, ydl.build_format_selector(video_format_selector(height)))

    def test_full_set_selects_exact_resolution_for_every_button(self):
        formats = [audio()] + [video(h) for h in (360.0, 720.0, 1080)]
        for height in (360, 720, 1080):
            with self.subTest(height=height):
                chosen = self.select(formats, height)
                self.assertEqual(len(chosen), 1)
                self.assertEqual(selected_height(chosen[0]), height)

    def test_codec_fallback_does_not_choose_lower_avc_quality(self):
        formats = [audio(), video(360), video(720, codec="vp9", ext="webm")]
        chosen = self.select(formats, 720)
        self.assertEqual(selected_height(chosen[0]), 720)
        self.assertEqual(chosen[0]["vcodec"], "vp9")

    def test_progressive_container_fallback_keeps_exact_quality(self):
        formats = [video(360, audio="mp4a.40.2"), video(720, audio="mp4a.40.2")]
        self.assertEqual(selected_height(self.select(formats, 720)[0]), 720)

    def test_1080_keeps_preferred_avc_and_aac(self):
        formats = [audio(), video(1080), video(1080, codec="vp9", ext="webm", suffix="-vp9")]
        selected = self.select(formats, 1080)[0]
        self.assertEqual(selected["vcodec"], "avc1.640028")
        self.assertEqual(selected["acodec"], "mp4a.40.2")

    def test_missing_quality_never_uses_another_resolution(self):
        for formats, requested in [([audio(), video(360)], 720), ([audio(), video(1080)], 360),
                                   ([audio()], 1080), ([], 720)]:
            with self.subTest(requested=requested, formats=formats):
                self.assertEqual(self.select(formats, requested), [])

    def test_guard_rejects_changed_extractor_selection_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            ydl = Mock()
            ydl.__enter__ = Mock(return_value=ydl)
            ydl.__exit__ = Mock(return_value=None)
            ydl.extract_info.return_value = {"height": 360, "duration": 10}
            with patch("app.downloaders.youtube.yt_dlp.YoutubeDL", return_value=ydl):
                with self.assertRaises(WorkerError) as caught:
                    YouTubeDownloader()._download_video_sync("https://youtu.be/test", 720,
                                                            Path(directory), None)
            self.assertEqual(caught.exception.code, "quality_unavailable")
            self.assertEqual(ydl.extract_info.call_count, 1)
            self.assertFalse(ydl.extract_info.call_args.kwargs["download"])

    def test_unavailable_selector_error_has_actionable_safe_code(self):
        error = yt_dlp.utils.DownloadError("Requested format is not available PRIVATE")
        self.assertEqual(classify(error).code, "quality_unavailable")
        self.assertNotIn("PRIVATE", str(classify(error)))


if __name__ == "__main__":
    unittest.main()
