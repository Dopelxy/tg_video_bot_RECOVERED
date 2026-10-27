import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from app.paths import PROJECT_DIR
from app.services.process_tree import entry_command, popen_owned, stop_owned
from app.services.worker_errors import WorkerError, classify
from app.services.instance_lock import token_instance, InstanceBusy


class ProcessTests(unittest.TestCase):
    def test_token_lock_between_processes_and_after_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            marker = folder / "locked"
            script = folder / "lock_owner.py"
            script.write_text(
                f"import sys\nsys.path.insert(0,{str(PROJECT_DIR)!r})\n"
                "from pathlib import Path\nimport time\n"
                "from app.services.instance_lock import token_instance\n"
                f"with token_instance('synthetic-process-test',directory={str(folder)!r}):\n"
                f"    Path({str(marker)!r}).touch()\n    time.sleep(60)\n", encoding="utf-8")
            process, job = popen_owned(entry_command(path=script), cwd=PROJECT_DIR,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists())
                with self.assertRaises(InstanceBusy):
                    with token_instance("synthetic-process-test", directory=folder):
                        self.fail("second owner")
            finally:
                stop_owned(process, job)
            with token_instance("synthetic-process-test", directory=folder):
                pass

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
    def test_owner_crash_closes_job_automatically(self):
        from ctypes import wintypes as w
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        api.OpenProcess.restype = w.HANDLE
        api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        api.CloseHandle.argtypes = [w.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            child = folder / "child.py"
            marker = folder / "pid"
            child.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
            owner = folder / "owner.py"
            owner.write_text(
                f"import sys\nsys.path.insert(0,{str(PROJECT_DIR)!r})\n"
                "import time\nfrom pathlib import Path\n"
                "from app.services.process_tree import entry_command,popen_owned\n"
                f"p,job=popen_owned(entry_command(path={str(child)!r}),cwd={str(PROJECT_DIR)!r})\n"
                f"Path({str(marker)!r}).write_text(str(p.pid))\n"
                "time.sleep(60)\n", encoding="utf-8")
            process, outer_job = popen_owned(entry_command(path=owner), cwd=PROJECT_DIR,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            handle = None
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists())
                handle = api.OpenProcess(0x100000, False, int(marker.read_text()))
                self.assertTrue(handle)
                process.kill()  # only the synthetic owner created by this test
                process.wait(timeout=5)
                self.assertEqual(api.WaitForSingleObject(handle, 5000), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                outer_job.close()
                if handle:
                    api.CloseHandle(handle)

    def test_diagnostic_does_not_copy_secrets(self):
        class DownloadError(Exception):
            pass
        error = classify(DownloadError("https://user:PRIVATE@example.invalid TOKEN=PRIVATE"))
        self.assertEqual(error.code, "extractor")
        self.assertNotIn("PRIVATE", str(error))
        self.assertEqual(classify(TimeoutError()).code, "timeout")
        self.assertEqual(classify(DownloadError("ffmpeg not found PRIVATE")).code, "ffmpeg_missing")
        self.assertEqual(classify(PermissionError(errno.EACCES, "PRIVATE")).code, "filesystem")
        self.assertEqual(classify(ConnectionRefusedError(errno.ECONNREFUSED, "PRIVATE")).code, "network")

    def test_wrapped_budget_error_retains_code(self):
        class DownloadError(Exception):
            pass
        inner = WorkerError("size_limit")
        outer = DownloadError("PRIVATE")
        outer.exc_info = (WorkerError, inner, None)
        wrapper = RuntimeError("PRIVATE")
        wrapper.__cause__ = outer
        self.assertEqual(classify(wrapper).code, "size_limit")

    def test_gate_does_not_execute_without_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            script = Path(directory) / "target.py"
            script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()", encoding="utf-8")
            result = subprocess.run(entry_command(path=script), input=b"", capture_output=True,
                                    cwd=PROJECT_DIR, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
    def test_job_kills_grandchild_after_root_exit(self):
        from ctypes import wintypes as w
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        api.OpenProcess.restype = w.HANDLE
        api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        api.CloseHandle.argtypes = [w.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pid.json"
            script = Path(directory) / "parent.py"
            script.write_text(
                "import subprocess,sys,time,json\nfrom pathlib import Path\n"
                "p=subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)'])\n"
                f"Path({str(marker)!r}).write_text(json.dumps(p.pid))\n"
                "time.sleep(60)\n", encoding="utf-8")
            process, job = popen_owned(entry_command(path=script), cwd=PROJECT_DIR,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            handle = None
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists())
                pid = json.loads(marker.read_text())
                handle = api.OpenProcess(0x100000, False, pid)
                self.assertTrue(handle)
                process.kill()  # only this test's owned root
                process.wait(timeout=5)
                self.assertEqual(api.WaitForSingleObject(handle, 0), 258)
                stop_owned(process, job)
                self.assertEqual(api.WaitForSingleObject(handle, 5000), 0)
            finally:
                stop_owned(process, job)
                if handle:
                    api.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
