"""Утилиты безопасной отправки сообщений в MarkdownV2."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from structure.formatter import escape_mdv2


def _is_entity_error(error: TelegramBadRequest) -> bool:
    """Проверяет, что ошибка связана с парсингом MarkdownV2."""

    return "can't parse entities" in str(error).lower()


async def safe_send(message: Message, text: str, **kwargs):
    """Отправляет сообщение в MarkdownV2 с повтором при ошибке разметки."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as error:
        if not _is_entity_error(error):
            raise
        escaped = escape_mdv2(text)
        if escaped == text:
            raise
        return await message.answer(escaped, **kwargs)


async def safe_edit(message: Message, text: str, **kwargs):
    """Редактирует сообщение, перехватывая ошибки разметки MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as error:
        if not _is_entity_error(error):
            raise
        escaped = escape_mdv2(text)
        if escaped == text:
            raise
        return await message.edit_text(escaped, **kwargs)


async def safe_edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    **kwargs,
):
    """Редактирует сообщение по идентификатору с защитой от ошибок MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            **kwargs,
        )
    except TelegramBadRequest as error:
        if not _is_entity_error(error):
            raise
        escaped = escape_mdv2(text)
        if escaped == text:
            raise
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=escaped,
            **kwargs,
        )


# Обратная совместимость со старыми импортами.
safe_answer = safe_send
