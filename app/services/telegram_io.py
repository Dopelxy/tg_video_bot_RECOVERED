"""Status edits may fail without changing the outcome of a delivered file."""
import logging
import time

from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramNetworkError, TelegramRetryAfter)

logger = logging.getLogger(__name__)


class StatusEditor:
    def __init__(self, message):
        self.message = message
        self.retry_at = 0.0
        self.disabled = False
        self.failures = 0

    async def edit(self, text, **kwargs):
        if self.disabled or time.monotonic() < self.retry_at:
            return False
        try:
            await self.message.edit_text(text, request_timeout=15, **kwargs)
            self.failures = 0
            return True
        except TelegramRetryAfter as error:
            self.retry_at = time.monotonic() + max(1, error.retry_after)
            logger.warning("Обновление статуса отложено: RetryAfter")
        except TelegramBadRequest as error:
            if "message is not modified" in error.message.lower():
                self.failures = 0
                return True
            self.disabled = True
            logger.warning("Обновление статуса отключено: сообщение недоступно")
        except TelegramForbiddenError:
            # Includes deleted/inaccessible messages. Do not keep editing forever.
            self.disabled = True
            logger.warning("Обновление статуса отключено: сообщение недоступно")
        except Exception as error:
            self.failures += 1
            self.retry_at = time.monotonic() + min(60, 2 ** min(self.failures, 6))
            logger.warning("Ошибка обновления статуса: %s", type(error).__name__)
        return False


async def edit_status(message, text, **kwargs):
    return await StatusEditor(message).edit(text, **kwargs)


def delivery_error(error):
    if isinstance(error, TelegramRetryAfter):
        return "Telegram ограничил частоту отправки. Попробуй позже."
    if isinstance(error, TelegramNetworkError):
        return ("Не удалось подтвердить отправку в Telegram. Проверь чат перед повтором: "
                "файл мог быть доставлен.")
    return "Telegram не принял файл. Попробуй повторить запрос позже."
