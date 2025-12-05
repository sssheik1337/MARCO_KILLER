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
            SELECT id, code, article, name, quantity, unit, extra_info, date_in
            FROM stock_items
            WHERE city = ? AND section = ?
            ORDER BY name
            """,
            (city, section),
        )
        rows = await cur.fetchall()

    items: list[StockItemRow] = []
    for (row_id, code, article, name, quantity, unit, extra_info, date_in) in rows:
        qty = float(quantity) if quantity is not None else 0.0
        items.append(
            StockItemRow(
                id=row_id,
                code=code,
                article=article,
                name=name,
                quantity=qty,
                unit=unit or "",
                extra_info=extra_info or "",
                date_in=date_in,
            )
        )

    logger.info(
        "load_city_stock: city=%s section=%s, items=%s", city, section, len(items)
    )

    return StockItemCity(city=city, section=section, items=items)

