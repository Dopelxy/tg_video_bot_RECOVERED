"""Own and stop the exact process tree started for a local bot runtime.

This module contains no Qt code and does not import the bot token. A persistent
agent can keep one instance alive independently of the desktop window.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO


class BotProcess:
    def __init__(self, project_dir: Path, *, python_executable: str | None = None) -> None:
        self.project_dir = project_dir.resolve()
        self.python_executable = python_executable or sys.executable
        self.process: subprocess.Popen[bytes] | None = None
        self._log_file: BinaryIO | None = None

    @property
    def pid(self) -> int | None:
        process = self.process
        return process.pid if process is not None and process.poll() is None else None

    def start(self) -> int:
        if self.pid is not None:
            return self.pid
        if self.process is not None:
            self.process.wait()
            self.process = None
            self._close_log()

        launcher = self.project_dir / "launcher.py"
        if not launcher.is_file():
            raise FileNotFoundError(launcher)

        log_dir = self.project_dir / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = (log_dir / "runtime.log").open("ab", buffering=0)

        options: dict = {}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True

        try:
            self.process = subprocess.Popen(
                [self.python_executable, "-u", str(launcher)],
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                **options,
            )
        except BaseException:
            self._close_log()
            raise
        return self.process.pid

    def stop(self, *, timeout: float = 10.0) -> bool:
        process = self.process
        if process is None:
            return True

        if process.poll() is None:
            if sys.platform == "win32":
                try:
                    result = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return False
                if result.returncode != 0 and process.poll() is None:
                    return False
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    return False

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return False
            else:
                return False

        self.process = None
        self._close_log()
        return True

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
