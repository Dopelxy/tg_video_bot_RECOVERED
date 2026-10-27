"""Bounded local media validation and conversion, called inside an owned worker."""
import json
from pathlib import Path
import shutil
import subprocess

from app.config.app_settings import settings
from app.services.worker_errors import WorkerError


def max_bytes():
    return settings.max_file_size_mb * 1024 * 1024


def check_budget(directory, downloaded=0, estimated=None):
    limit = max_bytes()
    if downloaded > limit or (estimated and estimated > limit):
        raise WorkerError("size_limit")
    # Includes separate streams, parts and conversion output. Bound transient use.
    total = sum(p.stat().st_size for p in Path(directory).iterdir() if p.is_file())
    if total > limit * 3:
        raise WorkerError("disk_limit")
    if shutil.disk_usage(directory).free < max(32 * 1024 * 1024, limit):
        raise WorkerError("disk_limit")


def download_options(directory):
    def budget_hook(data):
        check_budget(directory, data.get("downloaded_bytes") or 0,
                     data.get("total_bytes") or data.get("total_bytes_estimate"))

    def size_filter(info, *, incomplete=False):
        streams = info.get("requested_formats") or [info]
        sizes = [f.get("filesize") or f.get("filesize_approx") for f in streams]
        if all(isinstance(v, (int, float)) for v in sizes) and sum(sizes) > max_bytes():
            raise WorkerError("size_limit")
        return None

    check_budget(directory)
    return {"socket_timeout": 20, "retries": 2, "fragment_retries": 2,
            "max_filesize": max_bytes(), "match_filter": size_filter,
            "progress_hooks": [budget_hook]}


def probe(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name", "-of", "json", str(path)],
            capture_output=True, timeout=30, check=True,
        )
        return json.loads(result.stdout)
    except FileNotFoundError:
        raise WorkerError("ffmpeg_missing") from None
    except (subprocess.SubprocessError, ValueError):
        raise WorkerError("media_invalid") from None


def compatible(info, audio):
    streams = info.get("streams", [])
    if audio:
        return ("mp3" in info.get("format", {}).get("format_name", "").split(",")
                and any(s.get("codec_type") == "audio" and s.get("codec_name") == "mp3"
                        for s in streams))
    return ("mp4" in info.get("format", {}).get("format_name", "").split(",")
            and any(s.get("codec_type") == "video" and s.get("codec_name") == "h264" for s in streams)
            and all(s.get("codec_name") == "aac" for s in streams if s.get("codec_type") == "audio"))


def prepare_media(path, *, audio=False):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise WorkerError("media_invalid")
    if path.stat().st_size > max_bytes():
        raise WorkerError("size_limit")
    info = probe(path)
    if compatible(info, audio):
        return path
    output = path.with_name("telegram_ready.mp3" if audio else "telegram_ready.mp4")
    check_budget(path.parent)
    codecs = (["-vn", "-c:a", "libmp3lame", "-b:a", "192k"] if audio else
              ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "fast",
               "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"])
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                        *codecs, "-fs", str(max_bytes() + 1), str(output)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True)
    except FileNotFoundError:
        raise WorkerError("ffmpeg_missing") from None
    except subprocess.TimeoutExpired:
        raise WorkerError("timeout") from None
    except subprocess.SubprocessError:
        raise WorkerError("media_invalid") from None
    if output.stat().st_size > max_bytes():
        raise WorkerError("size_limit")
    prepared = probe(output)
    # -fs bounds conversion output but may stop early with exit code 0.
    # Never deliver such a truncated result as a successful full conversion.
    try:
        original_duration = float(info["format"]["duration"])
        output_duration = float(prepared["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise WorkerError("media_invalid") from None
    if output_duration < original_duration - 0.1:
        raise WorkerError("size_limit")
    if not compatible(prepared, audio):
        raise WorkerError("media_invalid")
    return output
