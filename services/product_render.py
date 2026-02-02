"""Формирование текстов карточек товаров для MarkdownV2."""

from __future__ import annotations

from typing import Any

from structure.markdown import escape_user, inline_code

_CITY_LABELS = {
    "msk": "Москва",
    "spb": "Санкт-Петербург",
}


def as_float(value: Any) -> float | None:
    """Аккуратно приводит значение к числу с плавающей точкой."""

    if value in (None, "", "—"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_money(value: float | None) -> str:
    """Возвращает стоимость в рублях с форматированием."""

    if value is None:
        return "—"
    return f"{value:.2f} ₽"


def format_money_with_currency(value: float | None, currency: str | None) -> str:
    """Форматирует стоимость с учётом валюты."""

    if value is None:
        return "—"
    code = (currency or "").strip()
    if not code or code.upper() == "RUB":
        return f"{value:.2f} ₽"
    return f"{value:.2f} {code}"


def _line(label: str, value: object, *, raw: bool = False) -> str:
    """Формирует строку с экранированием или готовым фрагментом."""

    text = value if value not in (None, "") else "-"
    label_text = escape_user(label)
    if raw:
        return f"{label_text}: {text}"
    return escape_user(f"{label}: {text}")


def _city_label(city: str | None) -> str:
    if not city:
        return ""
    key = city.strip().lower()
    return _CITY_LABELS.get(key, city)


def build_product_caption(
    product: dict,
    *,
    include_city: bool = False,
    prefix: str | None = None,
) -> str:
    """Собирает описание товара для отправки в MarkdownV2."""

    if product.get("section") == "fabrics":
        roll = product.get("wholesale_roll") or "—"
        piece = product.get("wholesale_piece") or "—"
        price_line = f"Опт от ролика: {roll} · Опт в отрез: {piece}"
        article_value = inline_code(product.get("article"))
    else:
        currency = product.get("currency") or ""
        rrc = format_money_with_currency(as_float(product.get("price_rrc")), currency)
        opt = format_money_with_currency(as_float(product.get("price_opt")), currency)
        price_line = f"РРЦ: {rrc} · Опт: {opt}"
        article_value = inline_code(product.get("article"))

    lines: list[str] = []
    if prefix:
        lines.append(escape_user(prefix))
    lines.append(inline_code(product.get("name")))

    if include_city:
        city_label = _city_label(product.get("city"))
        if city_label:
            lines.append(escape_user(f"Город: {city_label}"))

    lines.append(_line("Артикул", article_value or "-", raw=True))

    if product.get("section") == "fabrics":
        lines.extend(
            [
                _line("Страна", product.get("country")),
                _line("Тип ткани", product.get("fabric_type")),
                _line("Сегмент", product.get("segment")),
            ]
        )
    else:
        lines.extend(
            [
                _line("Коллекция", product.get("collection")),
                _line("Бренд/страна", product.get("brand_country")),
                _line("Кратность", product.get("multiplicity")),
                _line("Ед.", product.get("unit")),
            ]
        )

    lines.append(escape_user(price_line))
    in_stock = product.get("in_stock")
    if in_stock is not None:
        lines.append(_line("Наличие", in_stock))

    special_flag = (
        product.get("special") if product.get("section") == "fabrics" else product.get("status")
    )
    if special_flag:
        lines.append(_line("Статус", special_flag))

    return "\n".join(lines)
