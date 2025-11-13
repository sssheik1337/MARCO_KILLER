import re


def escape_md(text: str) -> str:
    """Экранирует все зарезервированные символы MarkdownV2."""
    return re.sub(r'([_*[\\]()~`>#+\-=|{}.!])', r'\\\1', text)
