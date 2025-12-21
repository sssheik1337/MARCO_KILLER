"""Хелперы для работы с MarkdownV2."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


class MarkdownV2Escaper:
    """Утилиты экранирования MarkdownV2 с сохранением корректной разметки."""

    _SPECIAL_CHARS = r"\\_*[]()~`>#+-=|{}.!+"
    _ESCAPE_RE = re.compile(f"([{re.escape(_SPECIAL_CHARS)}])")
    _MARKDOWN_FRAGMENT_RE = re.compile(
        r"("  # группа для полезной разметки
        r"```[\s\S]*?```"  # блок кода
        r"|`[^`]*`"  # инлайн-код
        r"|\[[^\]\n]*?\]\([^\)\n]*?\)"  # ссылка
        r"|\*{1,2}[^*\r\n]+?\*{1,2}"  # курсив или жирный через *
        r"|_{1,2}[^_\r\n]+?_{1,2}"  # курсив или подчёркивание через _
        r"|~[^~\r\n]+?~"  # зачёркивание
        r"|\|\|[\s\S]*?\|\|"  # спойлер
        r")",
        re.DOTALL,
    )

    @classmethod
    def escape_plain(cls, chunk: str) -> str:
        """Экранирует обычный текст, не содержащий Markdown-разметки."""

        if not chunk:
            return ""

        escaped = chunk.replace("\\", "\\\\")
        return cls._ESCAPE_RE.sub(lambda match: "\\" + match.group(1), escaped)

    @classmethod
    def escape_preserving(cls, text: str) -> str:
        """Экранирует текст вне Markdown-фрагментов, сохраняя форматирование."""

        if not text:
            return ""

        result: list[str] = []
        last_index = 0

        for match in cls._MARKDOWN_FRAGMENT_RE.finditer(text):
            start, end = match.span()
            if start > last_index:
                result.append(cls.escape_plain(text[last_index:start]))
            result.append(match.group(0))
            last_index = end

        if last_index < len(text):
            result.append(cls.escape_plain(text[last_index:]))

        return "".join(result)


@dataclass(frozen=True)
class _EntityWrapper:
    """Содержит данные о маркерах Markdown для сущности Telegram."""

    start: int
    end: int
    start_token: str
    end_token: str
    length: int
    disable_escape: bool


def _entity_tokens(entity: MessageEntity, text: str) -> _EntityWrapper | None:
    """Подбирает маркеры MarkdownV2 для сущности Telegram."""

    start = entity.offset
    end = entity.offset + entity.length
    length = entity.length
    entity_type = entity.type

    if entity_type == "bold":
        return _EntityWrapper(start, end, "*", "*", length, False)
    if entity_type == "italic":
        return _EntityWrapper(start, end, "_", "_", length, False)
    if entity_type == "underline":
        return _EntityWrapper(start, end, "__", "__", length, False)
    if entity_type == "strikethrough":
        return _EntityWrapper(start, end, "~", "~", length, False)
    if entity_type == "spoiler":
        return _EntityWrapper(start, end, "||", "||", length, False)
    if entity_type == "code":
        return _EntityWrapper(start, end, "`", "`", length, True)
    if entity_type == "pre":
        language = entity.language or ""
        prefix = f"```{language}\n" if language else "```"
        snippet = text[start:end]
        suffix = "\n```" if not snippet.endswith("\n") else "```"
        return _EntityWrapper(start, end, prefix, suffix, length, True)
    if entity_type == "text_link" and entity.url:
        return _EntityWrapper(start, end, "[", f"]({entity.url})", length, False)
    if entity_type == "text_mention" and entity.user:
        return _EntityWrapper(
            start,
            end,
            "[",
            f"](tg://user?id={entity.user.id})",
            length,
            False,
        )
    return None


def _collect_wrappers(
    entities: Iterable[MessageEntity], text: str
) -> tuple[dict[int, list[_EntityWrapper]], dict[int, list[_EntityWrapper]]]:
    """Формирует словари открывающих и закрывающих маркеров."""

    starts: dict[int, list[_EntityWrapper]] = defaultdict(list)
    ends: dict[int, list[_EntityWrapper]] = defaultdict(list)

    for entity in entities:
        wrapper = _entity_tokens(entity, text)
        if not wrapper:
            continue
        starts[wrapper.start].append(wrapper)
        ends[wrapper.end].append(wrapper)

    return starts, ends


def message_to_markdown(message: Message) -> str:
    """Конвертирует текст сообщения и его сущности в строку MarkdownV2."""

    text = message.text or message.caption or ""
    if not text:
        return ""

    entities: Iterable[MessageEntity] = message.entities or message.caption_entities or []
    start_map, end_map = _collect_wrappers(entities, text)

    if not start_map and not end_map:
        return MarkdownV2Escaper.escape_plain(text)

    positions = sorted({0, len(text), *start_map.keys(), *end_map.keys()})
    result: list[str] = []
    active_code_blocks = 0

    for index, pos in enumerate(positions):
        for wrapper in sorted(
            end_map.get(pos, []),
            key=lambda item: (item.length, item.start_token),
        ):
            if wrapper.disable_escape:
                active_code_blocks = max(0, active_code_blocks - 1)
            result.append(wrapper.end_token)

        for wrapper in sorted(
            start_map.get(pos, []),
            key=lambda item: (-item.length, item.start_token),
        ):
            result.append(wrapper.start_token)
            if wrapper.disable_escape:
                active_code_blocks += 1

        if index == len(positions) - 1:
            continue

        next_pos = positions[index + 1]
        if next_pos <= pos:
            continue

        segment = text[pos:next_pos]
        if active_code_blocks > 0:
            result.append(segment)
        else:
            result.append(MarkdownV2Escaper.escape_plain(segment))

    return "".join(result)


def escape_user(text: str | None) -> str:
    """Экранирует произвольный пользовательский ввод под MarkdownV2."""

    if not text:
        return ""
    normalized = str(text).replace("\r", "").replace("\t", "    ")
    return MarkdownV2Escaper.escape_preserving(normalized)


def escape_md(text: str | None) -> str:
    """Единый метод экранирования строк под MarkdownV2."""

    return escape_user(text)


def inline_code(value: object | None) -> str:
    """Возвращает строку в моноширинном формате MarkdownV2 без экранирования внутри."""

    if value in (None, ""):
        return "`-`"
    return f"`{value}`"


def escape_full(text: str) -> str:
    """Полностью экранирует текст на случай некорректной разметки."""

    if not text:
        return ""
    return MarkdownV2Escaper.escape_plain(text)


def strip_markdown(text: str) -> str:
    """Удаляет Markdown-разметку, оставляя только обычный текст."""

    if not text:
        return ""
    stripped = re.sub(
        r"\*\*(.*?)\*\*|\*(.*?)\*",
        lambda match: (match.group(1) or match.group(2) or ""),
        text,
    )
    stripped = re.sub(
        r"__(.*?)__|_(.*?)_",
        lambda match: (match.group(1) or match.group(2) or ""),
        stripped,
    )
    stripped = re.sub(
        r"`{1,3}(.*?)`{1,3}",
        lambda match: match.group(1) or "",
        stripped,
        flags=re.S,
    )
    stripped = re.sub(
        r"\[(.*?)\]\((.*?)\)",
        lambda match: f"{match.group(1)}: {match.group(2)}",
        stripped,
    )
    return stripped.replace("\\", "")


async def send_md_safe(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
    *,
    disable_web_page_preview: bool | None = None,
):
    """Отправляет MarkdownV2-сообщение с защитой от ошибок разметки."""
    """
    Сначала пытаемся отправить текст «как есть». Если Telegram сообщает об ошибке
    парсинга, повторяем попытку с выборочным экранированием MarkdownV2, которое
    сохраняет исходные конструкции форматирования. В крайнем случае полностью
    экранируем текст или отправляем plain-версию.
    """

    destination = target if isinstance(target, Message) else target.message
    can_edit = bool(destination and destination.from_user and destination.from_user.is_bot)

    # Если редактировать нечего (сообщение без текста/подписи, например документ/фото),
    # удаляем его и отправляем новое, чтобы избежать ошибок Telegram.
    if can_edit and not (destination.text or destination.caption):
        try:
            await destination.delete()
        except TelegramBadRequest as exc:
            if "message to delete not found" not in str(exc).lower():
                raise
        kwargs: dict[str, object] = {"reply_markup": reply_markup, "parse_mode": ParseMode.MARKDOWN_V2}
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        return await destination.answer(text, **kwargs)

    if can_edit:
        current_text = destination.text or destination.caption or ""
        if current_text == text and destination.reply_markup == reply_markup:
            return destination

    async def _sender(payload: str, parse_mode: ParseMode | None):
        kwargs: dict[str, object] = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        if can_edit:
            if destination.text is not None:
                return await destination.edit_text(payload, **kwargs)
            if destination.caption is not None:
                return await destination.edit_caption(payload, **kwargs)
            return await destination.answer(payload, **kwargs)
        return await destination.answer(payload, **kwargs)

    return await _send_with_fallback(_sender, text, destination)


async def edit_md_safe(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
):
    """Редактирует сообщение с MarkdownV2, перехватывая ошибки разметки."""
    """
    Логика аналогична отправке: сперва используется оригинальный текст, затем
    версия с выборочным экранированием и, при необходимости, полностью
    экранированный либо «обезжиренный» вариант.
    """

    destination = target if isinstance(target, Message) else target.message

    current_text = destination.text or destination.caption or ""
    if current_text == text and destination.reply_markup == reply_markup:
        return destination

    async def _sender(payload: str, parse_mode: ParseMode | None):
        kwargs: dict[str, object] = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if destination.text is not None:
            return await destination.edit_text(payload, **kwargs)
        if destination.caption is not None:
            return await destination.edit_caption(payload, **kwargs)
        return await destination.answer(payload, **kwargs)

    return await _send_with_fallback(_sender, text, destination)


async def send_md_safe_to_chat(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
    *,
    disable_web_page_preview: bool | None = None,
):
    """Отправляет MarkdownV2-сообщение в указанный чат с обработкой ошибок."""

    async def _sender(payload: str, parse_mode: ParseMode | None):
        kwargs: dict[str, object] = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        return await bot.send_message(chat_id, payload, **kwargs)

    return await _send_with_fallback(_sender, text)


async def _send_with_fallback(
    sender: Callable[[str, ParseMode | None], Awaitable[Message]],
    text: str,
    destination: Message | None = None,
) -> Message:
    """Выполняет отправку с несколькими попытками для сохранения Markdown."""

    try:
        return await sender(text, ParseMode.MARKDOWN_V2)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower() and destination:
            return destination
        pass

    preserved = MarkdownV2Escaper.escape_preserving(text)
    if preserved and preserved != text:
        try:
            return await sender(preserved, ParseMode.MARKDOWN_V2)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower() and destination:
                return destination
            pass

    try:
        return await sender(escape_full(text), ParseMode.MARKDOWN_V2)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower() and destination:
            return destination
        pass

    plain_safe = MarkdownV2Escaper.escape_plain(strip_markdown(text))
    try:
        return await sender(plain_safe, ParseMode.MARKDOWN_V2)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower() and destination:
            return destination
        raise


async def edit_reply_markup_safe(
    message: Message,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None,
) -> Message:
    """Редактирует только клавиатуру, игнорируя попытку установить то же значение."""

    current_keyboard = getattr(message.reply_markup, "inline_keyboard", None)
    new_keyboard = getattr(reply_markup, "inline_keyboard", None)
    if current_keyboard == new_keyboard:
        return message
    try:
        return await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return message
        raise
