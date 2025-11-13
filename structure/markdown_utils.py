from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message

from structure.formatter import escape_md


async def safe_answer(message: Message, text: str, **kwargs):
    """Отправляет безопасное сообщение с экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    return await message.answer(escape_md(text), **kwargs)


async def safe_edit(message: Message, text: str, **kwargs):
    """Редактирует сообщение с предварительным экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    return await message.edit_text(escape_md(text), **kwargs)


async def safe_edit_message(bot: Bot, chat_id: int, message_id: int, text: str, **kwargs):
    """Редактирует сообщение по идентификатору с безопасным экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    return await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=escape_md(text),
        **kwargs,
    )
