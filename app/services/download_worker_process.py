"""Run a yt-dlp job in an owned process, with progress over a small JSON pipe."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


WORKER_MODULE = "app.downloaders.worker"
DOWNLOAD_TIMEOUT_SECONDS = 1800


async def _stop_process_tree(process: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32" and process.returncode is not None:
        return
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await asyncio.wait_for(killer.wait(), timeout=10)
            if killer.returncode != 0 and process.returncode is None:
                process.kill()
        except (OSError, asyncio.TimeoutError):
            if process.returncode is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if process.returncode is not None:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        if sys.platform == "win32":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await process.wait()


async def run_download_worker(
    action: str, *, url: str, output_dir: Path, max_height: int | None,
    progress: object | None,
) -> Path:
    options = {"stdin": asyncio.subprocess.PIPE, "stdout": asyncio.subprocess.PIPE,
               "stderr": subprocess.DEVNULL, "cwd": str(Path(__file__).resolve().parents[2])}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True

    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", WORKER_MODULE, **options,
    )
    try:
        request = {"action": action, "url": url, "output_dir": str(output_dir),
                   "max_height": max_height}
        process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        async def read_result() -> Path:
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise RuntimeError("Процесс загрузки завершился без результата")
                event = json.loads(line)
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
                        raise RuntimeError("Процесс загрузки завершился с ошибкой")
                    return Path(event["path"])
                elif event.get("kind") == "error":
                    raise WorkerError(event.get("error_type", "RuntimeError"))

        try:
            return await asyncio.wait_for(read_result(), timeout=DOWNLOAD_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Превышено время загрузки") from exc
    finally:
        # Also runs when the Telegram handler is cancelled.
        await asyncio.shield(_stop_process_tree(process))


class WorkerError(RuntimeError):
    """A typed, deliberately non-secret error returned by the child."""
