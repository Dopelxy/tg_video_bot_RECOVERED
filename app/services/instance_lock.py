"""An OS-held per-token local lock, released automatically on process death."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

from app.services.job_files import lease


class InstanceBusy(RuntimeError):
    pass


@contextmanager
def token_instance(token, *, directory=None):
    root = Path(directory) if directory is not None else Path(tempfile.gettempdir()) / "tg-media-bot-locks"
    root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(token.encode("utf-8")).hexdigest() + ".lock"
    manager = lease(root / name)
    try:
        manager.__enter__()
    except OSError:
        raise InstanceBusy("Бот с этим токеном уже запущен локально или блокировка недоступна") from None
    try:
        yield
    finally:
        manager.__exit__(None, None, None)
