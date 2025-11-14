"""Хелперы для работы с MarkdownV2."""

from __future__ import annotations

import re
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


def escape_user(text: str | None) -> str:
    """Экранирует произвольный пользовательский ввод под MarkdownV2."""

    if not text:
        return ""
    normalized = str(text).replace("\r", "").replace("\t", "    ")
    normalized = normalized.replace("\\", "\\\\")
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}\.!])", r"\\\\\\1", normalized)


def escape_full(text: str) -> str:
    """Полностью экранирует текст на случай некорректной разметки."""

    if not text:
        return ""
    safe = text.replace("\\", "\\\\")
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}\.!])", r"\\\\\\1", safe)


def strip_markdown(text: str) -> str:
    """Удаляет Markdown-разметку, оставляя только обычный текст."""

    if not text:
        return ""
    stripped = re.sub(r"\*\*(.*?)\*\*|\*(.*?)\*", r"\1\2", text)
    stripped = re.sub(r"__(.*?)__|_(.*?)_", r"\1\2", stripped)
    stripped = re.sub(r"`{1,3}(.*?)`{1,3}", r"\1", stripped, flags=re.S)
    stripped = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1: \2", stripped)
    return stripped.replace("\\", "")


async def send_md_safe(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
    *,
    disable_web_page_preview: bool | None = None,
):
    """Отправляет MarkdownV2-сообщение с защитой от ошибок разметки."""

    async def _answer(msg: Message, payload: str, parse_mode: ParseMode | None):
        kwargs: dict[str, object] = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        return await msg.answer(payload, **kwargs)

    destination = target if isinstance(target, Message) else target.message

    try:
        return await _answer(destination, text, None)
    except TelegramBadRequest:
        pass

    try:
        return await _answer(destination, escape_full(text), ParseMode.MARKDOWN_V2)
    except TelegramBadRequest:
        pass

    return await _answer(destination, strip_markdown(text), None)


async def edit_md_safe(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
):
    """Редактирует сообщение с MarkdownV2, перехватывая ошибки разметки."""

    async def _edit(msg: Message, payload: str, parse_mode: ParseMode | None):
        kwargs: dict[str, object] = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        return await msg.edit_text(payload, **kwargs)

    destination = target if isinstance(target, Message) else target.message

    try:
        return await _edit(destination, text, None)
    except TelegramBadRequest:
        pass

    try:
        return await _edit(destination, escape_full(text), ParseMode.MARKDOWN_V2)
    except TelegramBadRequest:
        pass

    return await _edit(destination, strip_markdown(text), None)
