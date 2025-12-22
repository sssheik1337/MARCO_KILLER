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


async def add_ready_catalog(title: str, file_id: str) -> int:
    """Создаёт новый каталог готовых изделий и возвращает его id."""

    filename = f"{title}.xlsx"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO ready_catalogs (title, file_id, filename) VALUES (?, ?, ?)",
            (title, file_id, filename),
        )
        await db.commit()
        return int(cur.lastrowid)


async def update_ready_catalog_title(catalog_id: int, new_title: str) -> None:
    """Обновляет название и итоговое имя файла каталога."""

    filename = f"{new_title}.xlsx"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ready_catalogs SET title = ?, filename = ? WHERE id = ?",
            (new_title, filename, catalog_id),
        )
        await db.commit()


async def update_ready_catalog_file(catalog_id: int, file_id: str) -> None:
    """Обновляет файл каталога, сохраняя текущее имя файла."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ready_catalogs SET file_id = ? WHERE id = ?",
            (file_id, catalog_id),
        )
        await db.commit()
