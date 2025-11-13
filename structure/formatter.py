"""Утилиты для безопасной работы с MarkdownV2."""

import re

_MARKDOWN_SPECIALS = "_*[]()~>#+-=|{}.!`"
_ESCAPE_PATTERN = re.compile(f"([{re.escape(_MARKDOWN_SPECIALS)}])")
_CODE_PATTERN = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")


def _escape_segment(segment: str) -> str:
    """Экранирует маркдаун-символы в переданном фрагменте текста."""

    return _ESCAPE_PATTERN.sub(r"\\\1", segment)


def escape_md(text: str) -> str:
    """Экранирует все зарезервированные символы MarkdownV2 вне кодовых блоков."""

    if not text:
        return text

    escaped_parts = []
    last_index = 0

    for match in _CODE_PATTERN.finditer(text):
        escaped_parts.append(_escape_segment(text[last_index:match.start()]))
        escaped_parts.append(match.group(0))
        last_index = match.end()

    escaped_parts.append(_escape_segment(text[last_index:]))

    return "".join(escaped_parts)
