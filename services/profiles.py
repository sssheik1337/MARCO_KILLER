"""Простейшее хранилище пользовательских контактов."""

from __future__ import annotations

from typing import Optional


_PHONE_BOOK: dict[int, str] = {}


def set_phone(user_id: int, phone: str) -> None:
    """Запоминает номер телефона пользователя."""

    if not phone:
        return
    _PHONE_BOOK[user_id] = phone.strip()


def get_phone(user_id: int) -> Optional[str]:
    """Возвращает сохранённый номер телефона пользователя."""

    return _PHONE_BOOK.get(user_id)
