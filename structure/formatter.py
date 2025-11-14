"""Утилиты для безопасной работы с MarkdownV2."""

from __future__ import annotations

import re
from typing import Optional

_MARKDOWN_SPECIALS = {
    "\\",
    "_",
    "*",
    "[",
    "]",
    "(",
    ")",
    "~",
    ">",
    "#",
    "+",
    "-",
    "=",
    "|",
    "{",
    "}",
    ".",
    "!",
}
_CODE_PATTERN = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")


def _escape_plain(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2 в произвольной строке."""

    if not text:
        return text

    return "".join(f"\\{char}" if char in _MARKDOWN_SPECIALS else char for char in text)


def _find_delimiter(text: str, start: int, delimiter: str) -> Optional[int]:
    """Находит позицию закрывающего разделителя, учитывая экранирование."""

    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == delimiter:
            return index
        index += 1
    return None


def _find_closing(text: str, start: int, closing: str, opening: Optional[str] = None) -> Optional[int]:
    """Ищет позицию закрывающего символа с поддержкой вложенности."""

    depth = 0
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if opening and char == opening:
            depth += 1
        elif char == closing:
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return None


def _escape_link_url(url: str) -> str:
    """Экранирует адрес ссылки согласно правилам MarkdownV2."""

    return _escape_plain(url)


def _escape_markup_segment(text: str) -> str:
    """Экранирует текст, сохраняя базовое форматирование MarkdownV2."""

    if not text:
        return text

    buffer: list[str] = []
    result: list[str] = []
    index = 0
    length = len(text)

    def flush_buffer() -> None:
        if buffer:
            result.append(_escape_plain("".join(buffer)))
            buffer.clear()

    while index < length:
        if text.startswith("```", index):
            closing = text.find("```", index + 3)
            if closing == -1:
                buffer.append(text[index])
                index += 1
                continue
            flush_buffer()
            closing += 3
            result.append(text[index:closing])
            index = closing
            continue

        char = text[index]

        if char == "`":
            closing = _find_delimiter(text, index + 1, "`")
            if closing is None:
                buffer.append(char)
                index += 1
                continue
            flush_buffer()
            result.append(text[index : closing + 1])
            index = closing + 1
            continue

        if char in {"*", "_"}:
            closing = _find_delimiter(text, index + 1, char)
            if closing is None:
                buffer.append(char)
                index += 1
                continue
            flush_buffer()
            inner = text[index + 1 : closing]
            result.append(char)
            result.append(_escape_markup_segment(inner))
            result.append(char)
            index = closing + 1
            continue

        if char == "[":
            closing_bracket = _find_closing(text, index + 1, "]")
            if (
                closing_bracket is not None
                and closing_bracket + 1 < length
                and text[closing_bracket + 1] == "("
            ):
                closing_paren = _find_closing(text, closing_bracket + 2, ")", "(")
                if closing_paren is not None:
                    flush_buffer()
                    label = text[index + 1 : closing_bracket]
                    url = text[closing_bracket + 2 : closing_paren]
                    result.append("[")
                    result.append(_escape_markup_segment(label))
                    result.append("](")
                    result.append(_escape_link_url(url))
                    result.append(")")
                    index = closing_paren + 1
                    continue

        buffer.append(char)
        index += 1

    flush_buffer()
    return "".join(result)


def escape_md(text: str) -> str:
    """Экранирует все спецсимволы MarkdownV2 вне кодовых блоков."""

    if not text:
        return text

    escaped_parts = []
    last_index = 0

    for match in _CODE_PATTERN.finditer(text):
        escaped_parts.append(_escape_plain(text[last_index:match.start()]))
        escaped_parts.append(match.group(0))
        last_index = match.end()

    escaped_parts.append(_escape_plain(text[last_index:]))

    return "".join(escaped_parts)


def escape_mdv2(text: str) -> str:
    """Экранирует строку, сохраняя базовое MarkdownV2-форматирование."""

    return _escape_markup_segment(text)
