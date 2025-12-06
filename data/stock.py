"""Работа с остатками из таблицы stock_items."""

import logging

import aiosqlite

from config import DB_PATH
from data.stock_models import StockItemCity, StockItemRow


logger = logging.getLogger(__name__)


async def load_city_stock(city: str, section: str) -> StockItemCity:
    """Загружает остатки для города и раздела из таблицы stock_items."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT
                id,
                city,
                section,
                kind,
                item_type,
                code,
                article,
                name,
                quantity,
                free_quantity,
                unit,
                extra_info,
                date_in
            FROM stock_items
            WHERE city = ? AND section = ?
            ORDER BY name
            """,
            (city, section),
        )
        rows = await cur.fetchall()

    items: list[StockItemRow] = []
    for (
        row_id,
        row_city,
        row_section,
        kind,
        item_type,
        code,
        article,
        name,
        quantity,
        free_quantity,
        unit,
        extra_info,
        date_in,
    ) in rows:
        if city == "spb" and section == "fabrics":
            qty = quantity
            free_qty = free_quantity
        else:
            try:
                qty = float(quantity) if quantity is not None else None
            except (TypeError, ValueError):
                qty = quantity

            try:
                free_qty = float(free_quantity) if free_quantity is not None else None
            except (TypeError, ValueError):
                free_qty = free_quantity
        items.append(
            StockItemRow(
                id=row_id,
                city=row_city,
                section=row_section,
                kind=kind,
                item_type=item_type,
                collection=None,
                code=code,
                article=article,
                name=name,
                quantity=qty,
                free_quantity=free_qty,
                unit=unit,
                extra_info=extra_info,
                date_in=date_in,
            )
        )

    logger.info(
        "load_city_stock: city=%s section=%s, items=%s", city, section, len(items)
    )

    if city == "spb" and section == "fabrics":
        _assign_collections_spb(items)

    return StockItemCity(city=city, section=section, items=items)


def _assign_collections_spb(items: list[StockItemRow]) -> None:
    """Назначает коллекции для СПБ по общему префиксу названия."""

    tokens_cache: list[list[str]] = []
    prefix_counts: dict[tuple[str, ...], int] = {}
    prefix_original: dict[tuple[str, ...], str] = {}

    for item in items:
        tokens = [part for part in str(item.name or "").split() if part]
        tokens_cache.append(tokens)
        for length in range(1, len(tokens) + 1):
            key = tuple(token.lower() for token in tokens[:length])
            prefix_counts[key] = prefix_counts.get(key, 0) + 1
            prefix_original.setdefault(key, " ".join(tokens[:length]))

    for item, tokens in zip(items, tokens_cache):
        if not tokens:
            item.collection = None
            item.kind = None
            continue

        chosen: str | None = None
        for length in range(len(tokens), 0, -1):
            key = tuple(token.lower() for token in tokens[:length])
            if prefix_counts.get(key, 0) >= 2:
                chosen = prefix_original[key]
                break

        if chosen is None:
            if len(tokens) == 1:
                chosen = tokens[0]
            else:
                chosen = tokens[0]

        item.collection = chosen
        item.kind = chosen

