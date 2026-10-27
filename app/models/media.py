from dataclasses import dataclass


@dataclass(slots=True)
class MediaMetadata:
    title: str
    uploader: str | None
    duration: int | None
    webpage_url: str
    channel_url: str | None = None
    uploader_url: str | None = None


@dataclass(slots=True)
class MediaFormat:
    format_id: str
    height: int
    ext: str
    filesize: int | None
