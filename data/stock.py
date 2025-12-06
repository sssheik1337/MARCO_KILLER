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

    return StockItemCity(city=city, section=section, items=items)

