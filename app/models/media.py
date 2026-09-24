from dataclasses import dataclass


@dataclass(slots=True)
class MediaMetadata:
    title: str
    uploader: str | None
    duration: int | None
    webpage_url: str


@dataclass(slots=True)
class MediaFormat:
    format_id: str
    height: int
    ext: str
    filesize: int | None