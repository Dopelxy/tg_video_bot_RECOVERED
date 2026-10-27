"""Own and stop the exact process tree started for a local bot runtime.

This module contains no Qt code and does not import the bot token. A persistent
agent can keep one instance alive independently of the desktop window.
"""

import subprocess
import sys
from pathlib import Path
from typing import BinaryIO
from app.services.process_tree import entry_command, popen_owned, stop_owned


class BotProcess:
    def __init__(self, project_dir: Path, *, python_executable: str | None = None) -> None:
        self.project_dir = project_dir.resolve()
        self.python_executable = python_executable or sys.executable
        self.process: subprocess.Popen[bytes] | None = None
        self._log_file: BinaryIO | None = None
        self._job = None

    @property
    def pid(self) -> int | None:
        process = self.process
        if process is not None and process.poll() is None:
            return process.pid
        if process is not None:
            stop_owned(process, self._job)
            self.process = None
            self._close_log()
        return None

    def start(self) -> int:
        if self.pid is not None:
            return self.pid
        if self.process is not None:
            stop_owned(self.process, self._job)
            self.process = None
            self._close_log()

        launcher = self.project_dir / "launcher.py"
        if not launcher.is_file():
            raise FileNotFoundError(launcher)

        log_dir = self.project_dir / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = (log_dir / "runtime.log").open("ab", buffering=0)

        try:
            self.process, self._job = popen_owned(
                entry_command(path=launcher, executable=self.python_executable), cwd=self.project_dir,
                stdout=self._log_file, stderr=subprocess.STDOUT,
            )
        except BaseException:
            self._close_log()
            raise
        return self.process.pid

    def stop(self, *, timeout: float = 10.0) -> bool:
        process = self.process
        if process is None:
            return True

        try:
            stop_owned(process, self._job, timeout)
        except (OSError, subprocess.TimeoutExpired):
            return False
        self.process = None
        self._close_log()
        return True

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
