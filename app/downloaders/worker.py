"""Child process for YouTube downloads. Receives its job on stdin."""

import json
import os
import signal
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path


def emit(event: dict) -> None:
    sys.__stdout__.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


class PipeProgress:
    def update_download(self, *, downloaded_bytes, total_bytes,
                        speed_bytes_per_second, eta_seconds) -> None:
        emit({"kind": "progress", "phase": "download",
              "downloaded_bytes": downloaded_bytes, "total_bytes": total_bytes,
              "speed": speed_bytes_per_second, "eta": eta_seconds})

    def set_processing(self, detail: str) -> None:
        emit({"kind": "progress", "phase": "processing", "detail": detail})


def watch_parent(parent_pid: int) -> None:
    """On Linux, clean up FFmpeg if the bot process disappears abruptly."""
    while True:
        time.sleep(1)
        if os.getppid() != parent_pid:
            os.killpg(os.getpgrp(), signal.SIGTERM)
            return


def main() -> None:
    parent_pid = os.getppid()
    if sys.platform != "win32":
        threading.Thread(target=watch_parent, args=(parent_pid,), daemon=True).start()
    try:
        request = json.loads(sys.stdin.readline())
        from app.downloaders.youtube import YouTubeDownloader

        downloader = YouTubeDownloader()
        url = request["url"]
        output_dir = Path(request["output_dir"])
        progress = PipeProgress()
        # yt-dlp prints diagnostics; reserve stdout for protocol messages.
        with redirect_stdout(sys.stderr):
            if request["action"] == "youtube_video":
                result = downloader._download_video_sync(
                    url, int(request["max_height"]), output_dir, progress,
                )
            elif request["action"] == "youtube_audio":
                result = downloader._download_audio_sync(url, output_dir, progress)
            else:
                raise ValueError("Неизвестная задача загрузки")
        emit({"kind": "result", "path": str(result)})
    except Exception as exc:
        # Never send exception text: extractors may include URL credentials.
        emit({"kind": "error", "error_type": type(exc).__name__})


if __name__ == "__main__":
    main()
