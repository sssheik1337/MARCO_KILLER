"""Простейшее хранилище пользовательских контактов и выбора города."""

from __future__ import annotations

from typing import Iterable, Optional

from config import DEFAULT_CITY

_PHONE_BOOK: dict[int, str] = {}
_CITY_BOOK: dict[int, str] = {}
_ALLOWED_CITIES = {"msk", "spb"}


def set_phone(user_id: int, phone: str) -> None:
    """Запоминает номер телефона пользователя."""

    if not phone:
        return
    _PHONE_BOOK[user_id] = phone.strip()


def get_phone(user_id: int) -> Optional[str]:
    """Возвращает сохранённый номер телефона пользователя."""

    return _PHONE_BOOK.get(user_id)


def set_city(user_id: int, city: str) -> None:
    """Сохраняет выбранный город для пользователя, если он поддерживается."""

    if not city:
        return
    normalized = city.strip().lower()
    if normalized not in _ALLOWED_CITIES:
        return
    _CITY_BOOK[user_id] = normalized


def _first_non_empty(values: Iterable[object]) -> Optional[object]:
    """Возвращает первый непустой элемент из переданной последовательности."""

    for item in values:
        if item is None:
            continue
        return item
    return None


def get_city(user_id: int) -> Optional[str]:
    """Возвращает выбранный город пользователя или ``None``, если его нет."""

    return _CITY_BOOK.get(user_id)


def get_city_or_default(user_id: int, default: str = DEFAULT_CITY) -> str:
    """Возвращает выбранный город или значение по умолчанию."""

    city = _first_non_empty((get_city(user_id), default))
    assert city is not None  # для корректной типизации
    normalized = str(city).strip().lower()
    if normalized in _ALLOWED_CITIES:
        return normalized
    return default
