"""Process-local limits shared by YouTube and Instagram handlers.

Handlers run on the bot's single asyncio event loop. The synchronous claim has
no await between checking and adding a user, so two callbacks cannot claim the
same user in that event loop.
"""

import asyncio
from functools import wraps

from app.config.app_settings import settings


class DownloadCoordinator:
    def __init__(self, max_concurrent_downloads: int) -> None:
        if max_concurrent_downloads < 1:
            raise ValueError("MAX_CONCURRENT_DOWNLOADS должен быть не меньше 1")
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.metadata_semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.max_jobs = 32
        self._active_users: set[int] = set()

    def claim_user(self, user_id: int) -> bool:
        if user_id in self._active_users or len(self._active_users) >= self.max_jobs:
            return False
        self._active_users.add(user_id)
        return True

    def release_user(self, user_id: int) -> None:
        self._active_users.discard(user_id)


download_coordinator = DownloadCoordinator(settings.max_concurrent_downloads)


def metadata_request(function):
    @wraps(function)
    async def limited(message):
        if message.from_user is None:
            return
        user_id = message.from_user.id
        if not download_coordinator.claim_user(user_id):
            await message.answer("⏳ Уже есть активное задание или очередь заполнена. Попробуй позже.")
            return
        try:
            return await function(message)
        finally:
            download_coordinator.release_user(user_id)
    return limited
