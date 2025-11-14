"""Утилиты для управления пользовательскими фильтрами отображения."""

from __future__ import annotations

from typing import Set

# Храним идентификаторы пользователей с активированным фильтром «В наличии».
_IN_STOCK_USERS: Set[int] = set()


def is_in_stock(user_id: int) -> bool:
    """Проверяет, включён ли у пользователя фильтр товаров в наличии."""

    return user_id in _IN_STOCK_USERS


def set_in_stock(user_id: int, enabled: bool) -> None:
    """Включает или отключает фильтр «В наличии» для пользователя."""

    if enabled:
        _IN_STOCK_USERS.add(user_id)
    else:
        _IN_STOCK_USERS.discard(user_id)


def toggle_in_stock(user_id: int) -> bool:
    """Переключает фильтр «В наличии» и возвращает его новое состояние."""

    enabled = not is_in_stock(user_id)
    set_in_stock(user_id, enabled)
    return enabled
