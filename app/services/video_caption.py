"""Platform-specific links and bounded Telegram HTML captions; no network lookup."""
from html import escape
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlsplit

CAPTION_LIMIT = 1024
_YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_INSTAGRAM = {"instagram.com", "www.instagram.com"}
_IG_RESERVED = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct",
                "about", "developer", "developers", "legal", "privacy", "terms", "web"}


def platform_url(value, platform, *, author=False):
    """Only recognize explicit profile/video routes. Never derive a user from a name."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    try:
        decoded = unquote(value, errors="strict")
        if any(c.isspace() or unicodedata.category(c).startswith("C") or c == "\\" for c in decoded):
            return None
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 80, 443}):
            return None
        host = parsed.hostname
        path = unquote(parsed.path, errors="strict").rstrip("/")
        if platform == "youtube":
            if author:
                if host not in _YOUTUBE:
                    return None
                if (not re.fullmatch(r"/(?:channel/UC[A-Za-z0-9_-]+|(?:user|c)/[^/\s<>\"'?#]+|@[^/\s<>\"'?#]+)", path)
                        or path.rsplit("/", 1)[-1] in {".", ".."}):
                    return None
                return "https://www.youtube.com" + path
            if host == "youtu.be":
                video_id = path[1:] if re.fullmatch(r"/[A-Za-z0-9_-]{11}", path) else ""
            elif host in _YOUTUBE and path == "/watch":
                ids = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
                video_id = ids[0] if len(ids) == 1 else ""
            elif host in _YOUTUBE and re.fullmatch(r"/(?:shorts|live|embed)/[^/]+", path):
                video_id = path.rsplit("/", 1)[1]
            else:
                return None
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return "https://www.youtube.com/watch?v=" + video_id
        elif platform == "instagram" and host in _INSTAGRAM:
            if author:
                name = path[1:]
                if (re.fullmatch(r"/[A-Za-z0-9._]{1,30}", path)
                        and name.lower() not in _IG_RESERVED and name not in {".", ".."}):
                    return "https://www.instagram.com/" + name + "/"
            elif re.fullmatch(r"/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+", path):
                return "https://www.instagram.com" + path + "/"
    except (ValueError, UnicodeError):
        pass
    return None


def text(value, default=""):
    value = value if isinstance(value, str) else default
    value = "".join(" " if unicodedata.category(c) in {"Cc", "Cs"} else c for c in value)
    return " ".join(value.split()) or default


def utf16_length(value):
    return len(value.encode("utf-16-le")) // 2


def shorten(value, limit):
    if utf16_length(value) <= limit:
        return value
    used = 0
    result = []
    for char in value:
        size = utf16_length(char)
        if used + size > limit - 1:
            break
        result.append(char)
        used += size
    return "".join(result) + "…"


def video_caption(*, platform, title, author, bot_name, bot_username, quality=None,
                  channel_url=None, uploader_url=None, webpage_url=None, source_url=None):
    if platform not in {"youtube", "instagram"}:
        raise ValueError("Unsupported caption platform")
    author = shorten(text(author, "неизвестен"), 160)
    bot_name = shorten(text(bot_name, "Telegram Bot"), 128)
    bot_username = shorten(text(bot_username, "telegram_bot").lstrip("@"), 64)
    # YouTube's channel_url is an ID-based channel; uploader_url is a handle.
    # Instagram may omit both; channel/uploader display names are never URL input.
    candidates = (channel_url, uploader_url) if platform == "youtube" else (uploader_url, channel_url)
    author_link = next((url for candidate in candidates
                        if (url := platform_url(candidate, platform, author=True))), None)
    original = platform_url(webpage_url, platform) or platform_url(source_url, platform)

    def link(label, url):
        return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if url else escape(label)

    tail_text = "\n👤 Автор: " + author
    tail_html = "\n👤 Автор: " + link(author, author_link)
    if quality:
        quality = shorten(text(quality), 48)
        tail_text += "\n📺 Качество: " + quality
        tail_html += "\n📺 Качество: " + escape(quality)
    if original:
        tail_text += "\n🔗 Оригинал"
        tail_html += "\n🔗 " + link("Оригинал", original)
    signature = f"\n\n◆ {bot_name}\n@{bot_username}"
    prefix = "🎬 " if platform == "youtube" else "📸 Instagram\n🎬 "
    budget = CAPTION_LIMIT - utf16_length(prefix + tail_text + signature)
    title = shorten(text(title, "Без названия"), budget)
    return escape(prefix + title) + tail_html + escape(signature)
