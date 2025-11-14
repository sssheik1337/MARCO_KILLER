from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message

from structure.formatter import escape_md


async def safe_answer(message: Message, text: str, *, escape: bool = True, **kwargs):
    """Отправляет безопасное сообщение с экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    payload = escape_md(text) if escape else text
    return await message.answer(payload, **kwargs)


async def safe_edit(message: Message, text: str, *, escape: bool = True, **kwargs):
    """Редактирует сообщение с предварительным экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    payload = escape_md(text) if escape else text
    return await message.edit_text(payload, **kwargs)


async def safe_edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    escape: bool = True,
    **kwargs,
):
    """Редактирует сообщение по идентификатору с безопасным экранированием MarkdownV2."""

    kwargs.setdefault("parse_mode", ParseMode.MARKDOWN_V2)
    payload = escape_md(text) if escape else text
    return await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=payload,
        **kwargs,
    )
