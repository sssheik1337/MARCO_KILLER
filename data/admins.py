"""Утилиты для проверки прав администраторов."""

import logging

import aiosqlite

from config import ADMINS, DB_PATH

logger = logging.getLogger(__name__)


def is_superadmin(user_id: int) -> bool:
    """Возвращает True, если пользователь — суперадмин из списка ADMINS."""

    return user_id in ADMINS


async def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом (суперадмин или записан в БД)."""

    if is_superadmin(user_id):
        return True

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admin_users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row is not None


async def add_admin_user(user_id: int) -> None:
    """Добавляет пользователя в список администраторов в БД."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admin_users (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def get_admin_ids() -> list[int]:
    """Возвращает список всех администраторов (суперадмины + admin_users)."""

    admin_ids = {int(admin_id) for admin_id in ADMINS}

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM admin_users")
            rows = await cur.fetchall()
    except aiosqlite.Error as exc:
        if "no such table" in str(exc).lower():
            logger.warning("Таблица admin_users недоступна: %s", exc)
            return sorted(admin_ids)
        logger.exception("Ошибка при чтении списка администраторов: %s", exc)
        return sorted(admin_ids)

    for row in rows:
        if row and row[0] is not None:
            admin_ids.add(int(row[0]))

    return sorted(admin_ids)
