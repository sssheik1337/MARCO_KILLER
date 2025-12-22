"""Утилиты для работы с каталогами готовых изделий (файлы)."""

from __future__ import annotations

import aiosqlite
from typing import Any

from config import DB_PATH


async def get_ready_catalogs() -> list[dict[str, Any]]:
    """Возвращает все сохранённые каталоги готовых изделий."""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, title, file_id, filename, created_at FROM ready_catalogs ORDER BY id DESC"
        )
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def get_ready_catalog_by_id(catalog_id: int) -> dict[str, Any] | None:
    """Возвращает один каталог по идентификатору."""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, title, file_id, filename, created_at FROM ready_catalogs WHERE id = ?",
            (catalog_id,),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_ready_catalog(catalog_id: int) -> None:
    """Удаляет каталог готовых изделий по идентификатору."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM ready_catalogs WHERE id = ?", (catalog_id,))
        await db.commit()

