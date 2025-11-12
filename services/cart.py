from collections import defaultdict

# Простейшая in-memory корзина по пользователю. При реальном запуске лучше хранить в БД.
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

def as_lines(user_id: int) -> list[str]:
    return [f"ID {pid} — {qty} шт." for pid, qty in CART[user_id].items()]