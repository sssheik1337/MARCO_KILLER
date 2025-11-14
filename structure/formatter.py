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


def _is_line_start(text: str, index: int) -> bool:
    """Проверяет, что позиция находится в начале строки (игнорируя пробелы)."""

    if index <= 0:
        return True

    probe = index - 1
    while probe >= 0:
        previous = text[probe]
        if previous == "\n":
            return True
        if previous not in {" ", "\t"}:
            return False
        probe -= 1
    return True


def _collect_ordered_prefix(text: str, index: int) -> Optional[int]:
    """Находит конец нумерованного маркера "1." в начале строки."""

    if not text[index].isdigit() or not _is_line_start(text, index):
        return None

    probe = index
    length = len(text)
    while probe < length and text[probe].isdigit():
        probe += 1

    if probe < length - 1 and text[probe] == "." and text[probe + 1] == " ":
        return probe

    return None


def _escape_plain(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2 в произвольной строке."""

    if not text:
        return text

    return "".join(f"\\{char}" if char in _MARKDOWN_SPECIALS else char for char in text)


def _is_escaped(text: str, position: int) -> bool:
    """Определяет, экранирован ли символ в заданной позиции."""

    backslashes = 0
    probe = position - 1
    while probe >= 0 and text[probe] == "\\":
        backslashes += 1
        probe -= 1
    return backslashes % 2 == 1


def _find_delimiter(text: str, start: int, delimiter: str) -> Optional[int]:
    """Находит позицию закрывающего разделителя, учитывая экранирование."""

    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == delimiter and not _is_escaped(text, index):
            return index
        index += 1
    return None


def _find_sequence(text: str, start: int, token: str) -> Optional[int]:
    """Находит позицию закрывающей последовательности (например, '__' или '||')."""

    index = start
    length = len(text)
    token_len = len(token)
    while index < length:
        position = text.find(token, index)
        if position == -1:
            return None
        if not _is_escaped(text, position):
            return position
        index = position + token_len
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

        if char in {"-", "+", "*"} and _is_line_start(text, index):
            next_char = text[index + 1] if index + 1 < length else ""
            if next_char == " ":
                flush_buffer()
                result.append(char)
                index += 1
                continue

        ordered_prefix_end = _collect_ordered_prefix(text, index)
        if ordered_prefix_end is not None:
            flush_buffer()
            result.append(text[index : ordered_prefix_end + 1])
            index = ordered_prefix_end + 1
            continue

        if char == "#" and _is_line_start(text, index):
            probe = index
            while probe < length and text[probe] == "#":
                probe += 1
            if probe < length and text[probe] == " ":
                flush_buffer()
                result.append(text[index:probe])
                index = probe
                continue

        if char == ">" and _is_line_start(text, index):
            next_char = text[index + 1] if index + 1 < length else ""
            if next_char == " ":
                flush_buffer()
                result.append(char)
                index += 1
                continue

        if text.startswith("||", index):
            closing = _find_sequence(text, index + 2, "||")
            if closing is None:
                buffer.append(char)
                index += 1
                continue
            flush_buffer()
            inner = text[index + 2 : closing]
            result.append("||")
            result.append(_escape_markup_segment(inner))
            result.append("||")
            index = closing + 2
            continue

        if text.startswith("__", index):
            closing = _find_sequence(text, index + 2, "__")
            if closing is None:
                buffer.append(char)
                index += 1
                continue
            flush_buffer()
            inner = text[index + 2 : closing]
            result.append("__")
            result.append(_escape_markup_segment(inner))
            result.append("__")
            index = closing + 2
            continue

        if char in {"*", "_", "~"}:
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
