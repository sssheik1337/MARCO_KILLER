import re
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

_SPECIAL = r"_*\[\]()~`>#+-=|{}.!\\"


def escape_md(text: str) -> str:
    """Экранирует строку для MarkdownV2."""

    if not text:
        return ""
    return re.sub(f"([{_SPECIAL}])", r"\\\1", str(text))


async def send_md_safe(target, text: str, **kwargs):
    """Отправляет сообщение с безопасным экранированием MarkdownV2."""

    msg = target if hasattr(target, "answer") else target.message
    try:
        return await msg.answer(text, parse_mode=ParseMode.MARKDOWN_V2, **kwargs)
    except TelegramBadRequest:
        safe = escape_md(text)
        return await msg.answer(safe, parse_mode=ParseMode.MARKDOWN_V2, **kwargs)
