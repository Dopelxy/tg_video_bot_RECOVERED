import offline_support
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.downloaders import worker
from app.downloaders.youtube import YouTubeDownloader
from app.downloaders.instagram import InstagramDownloader
from app.handlers import youtube, instagram
from app.models.bot_identity import BotIdentity
from app.models.media import MediaMetadata
from app.services import job_files
from app.services.video_caption import video_caption, platform_url, utf16_length

VIDEO = "https://www.youtube.com/watch?v=AbCdEf12345"
CHANNEL = "https://www.youtube.com/channel/UCOfflineTest"
REEL = "https://www.instagram.com/reel/ABC_123/"
PROFILE = "https://www.instagram.com/real.account/"


class ParsedCaption(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.tags = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs)["href"])

    def handle_data(self, value):
        self.parts.append(value)

    @property
    def text(self):
        return "".join(self.parts)


def caption(**kwargs):
    return video_caption(**dict({"platform": "youtube", "title": "Test title", "author": "Author",
                                 "bot_name": "Media Bot", "bot_username": "media_bot", "quality": "720p"},
                                **kwargs))


class CaptionTests(unittest.TestCase):
    def test_youtube_channel_priority_and_original_video(self):
        result = ParsedCaption(caption(channel_url=CHANNEL, uploader_url="https://youtube.com/@handle",
                                       webpage_url=VIDEO))
        self.assertEqual(result.links, [CHANNEL, VIDEO])
        for part in ["Test title", "Автор: Author", "720p", "Оригинал", "◆ Media Bot", "@media_bot"]:
            self.assertIn(part, result.text)

    def test_instagram_profile_is_distinct_from_reel(self):
        result = ParsedCaption(caption(platform="instagram", quality=None, uploader_url=PROFILE,
                                       webpage_url=REEL, title="Reel title"))
        self.assertEqual(result.links, [PROFILE, REEL])
        self.assertIn("Reel title", result.text)
        self.assertIn("Instagram", result.text)

    def test_missing_author_link_never_guesses_from_name(self):
        result = ParsedCaption(caption(platform="instagram", author="Display name", webpage_url=REEL))
        self.assertEqual(result.links, [REEL])
        self.assertIn("Автор: Display name", result.text)

    def test_uploader_handle_fallback(self):
        result = ParsedCaption(caption(channel_url="https://youtube.com/watch?v=AbCdEf12345",
            uploader_url="https://youtube.com/@real_handle", webpage_url=VIDEO))
        self.assertEqual(result.links, ["https://www.youtube.com/@real_handle", VIDEO])

    def test_special_characters_cannot_add_markup_or_links(self):
        title = '<b>A & B</b> "quote"'
        author = '<a href="https://evil.invalid">Name & Co</a>'
        result = ParsedCaption(caption(title=title, author=author, channel_url=CHANNEL,
            webpage_url=VIDEO, bot_name="Bot <&>", bot_username="bot<&>"))
        self.assertEqual(result.links, [CHANNEL, VIDEO])
        self.assertEqual(result.tags, ["a", "a"])
        self.assertIn(title, result.text)
        self.assertIn(author, result.text)
        self.assertIn("Bot <&>", result.text)

    def test_long_title_keeps_links_quality_signature_with_utf16_limit(self):
        result = ParsedCaption(caption(title="🎬<&>" * 3000, channel_url=CHANNEL, webpage_url=VIDEO))
        self.assertLessEqual(utf16_length(result.text), 1024)
        self.assertEqual(result.links, [CHANNEL, VIDEO])
        self.assertIn("…", result.text)
        self.assertIn("720p", result.text)
        self.assertTrue(result.text.endswith("◆ Media Bot\n@media_bot"))

    def test_invalid_author_and_original_urls_are_omitted(self):
        invalid = ["javascript:alert(1)", "data:text/html,test", "tg://user?id=1", "//youtube.com/@test",
                   "https://user:password@youtube.com/@test", "https://youtube.com:8443/@test",
                   "https://youtube.com.evil.invalid/@test", "https://evil.invalid/test",
                   "https://youtube.com/@test%0A", "https://youtube.com\\@evil.invalid/test",
                   "https://youtube.com/redirect?q=https://evil.invalid"]
        for url in invalid:
            with self.subTest(url=url):
                result = ParsedCaption(caption(channel_url=url, uploader_url=url, webpage_url=url))
                self.assertEqual(result.links, [])
                self.assertNotIn("Оригинал", result.text)

    def test_platform_and_link_roles_are_enforced(self):
        for url, platform, author in [(REEL, "instagram", True), (PROFILE, "instagram", False),
                                      (VIDEO, "youtube", True), (CHANNEL, "youtube", False),
                                      (CHANNEL, "instagram", True), (PROFILE, "youtube", True),
                                      ("https://instagram.com/../", "instagram", True)]:
            with self.subTest(url=url):
                self.assertIsNone(platform_url(url, platform, author=author))

    def test_original_uses_trusted_input_fallback_not_profile(self):
        result = ParsedCaption(caption(webpage_url=CHANNEL, source_url="https://youtu.be/AbCdEf12345?t=5"))
        self.assertEqual(result.links, [VIDEO])

    def test_tracking_removed_and_credentials_rejected_on_instagram(self):
        self.assertEqual(platform_url(PROFILE + "?igsh=test", "instagram", author=True), PROFILE)
        self.assertIsNone(platform_url("https://user@instagram.com/reel/ABC/", "instagram"))


class MetadataCaptionTests(unittest.TestCase):
    def extract(self, platform, info):
        cls = YouTubeDownloader if platform == "youtube" else InstagramDownloader
        stream = io.StringIO()
        with patch.object(cls, "_extract_info_sync", return_value=info), \
             patch.object(worker.sys, "stdin", io.StringIO(json.dumps({
                 "action": platform + "_metadata", "url": VIDEO if platform == "youtube" else REEL,
                 "output_dir": "."}))), patch.object(worker.sys, "__stdout__", stream):
            worker.main()
        data = json.loads(stream.getvalue())["data"]
        if platform == "youtube":
            return cls()._metadata_from_info(data, VIDEO)
        return cls()._build_metadata(info=data, original_url=REEL)

    def test_worker_and_metadata_retain_both_platform_links(self):
        for platform, account, original in [("youtube", CHANNEL, VIDEO), ("instagram", PROFILE, REEL)]:
            with self.subTest(platform=platform):
                metadata = self.extract(platform, {"title": "Test", "uploader": "Real name", "duration": 10,
                    "channel_url": account, "uploader_url": account, "webpage_url": original, "vcodec": "h264"})
                self.assertEqual(metadata.channel_url, account)
                self.assertEqual(metadata.uploader_url, account)
                result = ParsedCaption(caption(platform=platform, title=metadata.title, author=metadata.uploader,
                    channel_url=metadata.channel_url, uploader_url=metadata.uploader_url,
                    webpage_url=metadata.webpage_url))
                self.assertEqual(result.links, [account, original])

    def test_missing_optional_fields_are_compatible(self):
        legacy = MediaMetadata("Test", "Author", 10, VIDEO)
        self.assertIsNone(legacy.channel_url)
        self.assertIsNone(legacy.uploader_url)
        for platform in ("youtube", "instagram"):
            metadata = self.extract(platform, {"title": "Test", "uploader": "Author"})
            self.assertIsNone(metadata.channel_url)
            self.assertIsNone(metadata.uploader_url)


class CaptionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_handlers_pass_html_links_and_retain_signature(self):
        for platform in ("youtube", "instagram"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                original, account = (VIDEO, CHANNEL) if platform == "youtube" else (REEL, PROFILE)
                info = {"title": "Title <&>", "uploader": "Author <&>", "duration": 10,
                        "channel_url": account, "uploader_url": account, "webpage_url": original,
                        "vcodec": "h264", "formats": []}
                status = SimpleNamespace(edit_text=AsyncMock())
                message = SimpleNamespace(text=original, from_user=SimpleNamespace(id=456), bot=object(),
                                          answer=AsyncMock(return_value=status), answer_video=AsyncMock())
                module = youtube if platform == "youtube" else instagram
                downloader = module.youtube_downloader if platform == "youtube" else module.instagram_downloader
                async def download(*args, **kwargs):
                    path = kwargs["output_dir"] / "video.mp4"
                    path.write_bytes(b"offline")
                    return path
                manager = job_files.managed_job
                with patch.object(job_files, "managed_job", side_effect=lambda: manager(root=Path(directory))), \
                     patch.object(module, "load_bot_identity", AsyncMock(return_value=BotIdentity("Test Bot", "test_bot"))), \
                     patch.object(module, "record_safely", AsyncMock(return_value=True)), \
                     patch.object(downloader, "download_video", side_effect=download):
                    if platform == "youtube":
                        with patch("app.downloaders.youtube.run_download_worker", AsyncMock(return_value=info)), \
                             patch.object(youtube, "create_request_id", return_value="caption-card"):
                            await youtube.youtube_link_handler(message)
                        callback = SimpleNamespace(message=message, from_user=message.from_user, bot=message.bot,
                                                   data="ytq:caption-card:720", answer=AsyncMock())
                        await youtube.youtube_quality_handler(callback)
                    else:
                        with patch("app.downloaders.instagram.run_download_worker", AsyncMock(return_value=info)):
                            await instagram.instagram_link_handler(message)
                sent = message.answer_video.call_args.kwargs
                self.assertEqual(sent["parse_mode"], "HTML")
                parsed = ParsedCaption(sent["caption"])
                self.assertEqual(parsed.links, [account, original])
                self.assertIn("Title <&>", parsed.text)
                self.assertIn("Author <&>", parsed.text)
                self.assertTrue(parsed.text.endswith("◆ Test Bot\n@test_bot"))
                if platform == "youtube":
                    self.assertIn("720p", parsed.text)


if __name__ == "__main__":
    unittest.main()
