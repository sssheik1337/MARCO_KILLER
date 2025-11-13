from aiogram.types import Message

from structure.formatter import escape_md


async def safe_answer(message: Message, text: str, **kwargs):
    """Отправляет безопасное сообщение с экранированием MarkdownV2."""
    return await message.answer(escape_md(text), **kwargs)


async def safe_edit(message: Message, text: str, **kwargs):
    """Редактирует сообщение с предварительным экранированием MarkdownV2."""
    return await message.edit_text(escape_md(text), **kwargs)
