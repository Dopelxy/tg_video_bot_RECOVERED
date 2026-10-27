"""Private job directories with live leases; never sweep legacy/unmarked data."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
from pathlib import Path
import shutil
import sys
import time
import uuid

from app.paths import TEMP_ROOT

logger = logging.getLogger(__name__)


@contextmanager
def lease(path, *, blocking=False):
    handle = Path(path).open("a+b")
    locked = False
    try:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        locked = True
        yield
    finally:
        if locked:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def sweep(root=TEMP_ROOT, *, max_age=86400):
    root = Path(root).resolve()
    jobs = root / "managed"
    if not jobs.exists() or jobs.is_symlink():
        return
    for folder in jobs.iterdir():
        if (not folder.is_dir() or folder.is_symlink() or folder.resolve().parent != jobs.resolve()
                or len(folder.name) != 32 or any(c not in "0123456789abcdef" for c in folder.name)):
            continue
        marker = folder / ".lease"
        try:
            if marker.is_symlink() or not marker.is_file() or time.time() - marker.stat().st_mtime < max_age:
                continue
            with lease(marker):
                pass
            shutil.rmtree(folder)
        except OSError:
            logger.warning("Не удалось очистить неактивное задание %s", folder.name)


@contextmanager
def managed_job(*, root=TEMP_ROOT):
    root = Path(root).resolve()
    jobs = root / "managed"
    jobs.mkdir(parents=True, exist_ok=True)
    if jobs.is_symlink() or jobs.resolve().parent != root:
        raise RuntimeError("Недопустимый каталог заданий")
    sweep(root)
    folder = jobs / uuid.uuid4().hex
    folder.mkdir()
    try:
        with lease(folder / ".lease"):
            yield folder
    finally:
        try:
            shutil.rmtree(folder)
        except OSError:
            logger.warning("Не удалось удалить временные файлы задания %s", folder.name)


current_job = ContextVar("current_job")


def with_job(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with managed_job() as folder:
            token = current_job.set(folder)
            try:
                return await function(*args, **kwargs)
            finally:
                current_job.reset(token)
    return wrapped
