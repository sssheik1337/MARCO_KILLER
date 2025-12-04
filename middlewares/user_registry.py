"""Мидлварь для регистрации пользователей в таблице рассылок."""

from __future__ import annotations

import logging
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from data import db_utils

logger = logging.getLogger(__name__)


class UserRegistry(BaseMiddleware):
    """Сохраняет сведения о пользователе при любом обновлении."""

    async def __call__(self, handler, event, data):  # type: ignore[override]
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            try:
                await db_utils.upsert_user(user.id)
            except Exception as exc:  # pragma: no cover - логирование ошибок сохранения
                logger.warning("Не удалось сохранить пользователя %s: %s", user.id, exc)

        return await handler(event, data)
