"""Простейшее in-memory хранилище корзины и выбранных количеств."""

from collections import defaultdict


# Фактическое содержимое корзины
CART: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

# Временный выбор количества в карточке товара
SELECTION: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))


def get_qty(user_id: int, product_id: int) -> int:
    """Возвращает сохранённое количество товара в корзине."""

    return CART[user_id].get(product_id, 0)


def set_qty(user_id: int, product_id: int, qty: int) -> int:
    """Устанавливает количество товара в корзине, удаляя запись при значении 0."""

    if qty <= 0:
        CART[user_id].pop(product_id, None)
        if not CART[user_id]:
            CART.pop(user_id, None)
        return 0

    CART[user_id][product_id] = qty
    return qty


def ensure_selection(user_id: int, product_id: int, default: int = 1) -> int:
    """Возвращает выбранное количество, создавая запись при необходимости."""

    if default < 1:
        default = 1

    selected_map = SELECTION.get(user_id)
    if selected_map:
        selected = selected_map.get(product_id)
        if selected:
            return selected

    current = get_qty(user_id, product_id)
    if current > 0:
        SELECTION[user_id][product_id] = current
        return current

    SELECTION[user_id][product_id] = default
    return default


def adjust_selection(user_id: int, product_id: int, delta: int, minimum: int = 1) -> tuple[int, int]:
    """Изменяет выбранное количество и возвращает (старое, новое) значения."""

    if minimum < 1:
        minimum = 1

    current = ensure_selection(user_id, product_id, minimum)
    new_value = current + delta
    if new_value < minimum:
        new_value = minimum

    SELECTION[user_id][product_id] = new_value
    return current, new_value


def get_selection(user_id: int, product_id: int) -> int:
    """Возвращает выбранное количество без автосоздания записи."""

    return SELECTION.get(user_id, {}).get(product_id, 0)


def clear_selection(user_id: int, product_id: int | None = None) -> None:
    """Очищает выбор количества полностью или для конкретного товара."""

    if product_id is None:
        SELECTION.pop(user_id, None)
        return

    user_map = SELECTION.get(user_id)
    if not user_map:
        return

    user_map.pop(product_id, None)
    if not user_map:
        SELECTION.pop(user_id, None)


def clear(user_id: int) -> None:
    """Полностью очищает корзину и выбранные количества пользователя."""

    CART.pop(user_id, None)
    clear_selection(user_id)


def items(user_id: int) -> dict[int, int]:
    """Возвращает копию позиций корзины пользователя."""

    return dict(CART[user_id])


def as_lines(user_id: int) -> list[str]:
    """Совместимость со старым API: простое представление позиций."""

    return [f"ID {pid} — {qty} шт." for pid, qty in CART[user_id].items()]
