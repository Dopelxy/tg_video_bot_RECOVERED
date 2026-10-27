"""Run a yt-dlp job in an owned process, with progress over a small JSON pipe."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
import logging

from app.paths import PROJECT_DIR
from app.services.process_tree import WindowsJob, entry_command
from app.services.worker_errors import WorkerError

logger = logging.getLogger(__name__)


WORKER_MODULE = "app.downloaders.worker"
DOWNLOAD_TIMEOUT_SECONDS = 1800


async def _stop_process_tree(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if process.returncode is not None:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def run_download_worker(
    action: str, *, url: str, output_dir: Path, max_height: int | None,
    progress: object | None, timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> Path | dict:
    output_dir = output_dir.resolve()
    job = WindowsJob()
    options = {"stdin": asyncio.subprocess.PIPE, "stdout": asyncio.subprocess.PIPE,
               "stderr": subprocess.DEVNULL, "cwd": str(PROJECT_DIR), "limit": 2 * 1024 * 1024}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | 0x00000004  # CREATE_SUSPENDED
    else:
        options["start_new_session"] = True

    try:
        process = await asyncio.create_subprocess_exec(
            *entry_command(module=WORKER_MODULE), **options,
        )
    except BaseException:
        job.close()
        raise
    assigned = False
    try:
        job.assign(process.pid)
        assigned = True
        job.resume(process.pid)
        request = {"action": action, "url": url, "output_dir": str(output_dir),
                   "max_height": max_height}
        process.stdin.write(("go\n" + json.dumps(request) + "\n").encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        async def read_result() -> Path:
            while True:
                try:
                    line = await process.stdout.readline()
                except ValueError:
                    raise WorkerError("protocol") from None
                if not line:
                    raise WorkerError("worker_exit")
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise WorkerError("protocol") from None
                if event.get("kind") == "progress":
                    if progress is not None:
                        if event.get("phase") == "download":
                            progress.update_download(
                                downloaded_bytes=event["downloaded_bytes"],
                                total_bytes=event.get("total_bytes"),
                                speed_bytes_per_second=event.get("speed"),
                                eta_seconds=event.get("eta"),
                            )
                        elif event.get("phase") == "processing":
                            progress.set_processing(event.get("detail", "Обрабатываю…"))
                elif event.get("kind") == "result":
                    await process.wait()
                    if process.returncode != 0:
                        raise WorkerError("worker_exit")
                    if action.endswith("metadata"):
                        if not isinstance(event.get("data"), dict):
                            raise WorkerError("protocol")
                        return event["data"]
                    path = Path(event.get("path", "")).resolve()
                    if path.parent != output_dir or not path.is_file():
                        raise WorkerError("protocol")
                    return path
                elif event.get("kind") == "error":
                    error = WorkerError(event.get("code", "internal"), event.get("error_type", "unknown"))
                    logger.warning("worker action=%s code=%s type=%s", action, error.code, error.error_type)
                    raise error
                else:
                    raise WorkerError("protocol")

        try:
            return await asyncio.wait_for(read_result(), timeout=timeout)
        except asyncio.TimeoutError:
            raise WorkerError("timeout") from None
    finally:
        # Also runs when the Telegram handler is cancelled.
        async def finish():
            if sys.platform == "win32":
                if not assigned and process.returncode is None:
                    process.kill()
                try:
                    await asyncio.to_thread(job.stop, 10)
                finally:
                    job.close()
                    await asyncio.wait_for(process.wait(), timeout=10)
            else:
                await _stop_process_tree(process)
        cleanup = asyncio.create_task(finish())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
