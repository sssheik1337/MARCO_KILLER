"""Простейшее in-memory хранилище корзины по пользователю.

При реальном запуске данные стоит хранить в БД.
"""

from collections import defaultdict

CART: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

def get_qty(user_id: int, product_id: int) -> int:
    return CART[user_id][product_id]

def inc(user_id: int, product_id: int, step: int = 1) -> int:
    CART[user_id][product_id] += step
    return CART[user_id][product_id]

def dec(user_id: int, product_id: int, step: int = 1) -> int:
    CART[user_id][product_id] = max(0, CART[user_id][product_id] - step)
    if CART[user_id][product_id] == 0:
        CART[user_id].pop(product_id, None)
    return CART[user_id].get(product_id, 0)

def clear(user_id: int) -> None:
    CART.pop(user_id, None)

def items(user_id: int) -> dict[int, int]:
    """Возвращает копию позиций корзины пользователя."""

    return dict(CART[user_id])


def as_lines(user_id: int) -> list[str]:
    """Совместимость со старым API: простое представление позиций."""

    return [f"ID {pid} — {qty} шт." for pid, qty in CART[user_id].items()]
