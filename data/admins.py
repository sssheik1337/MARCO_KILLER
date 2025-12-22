"""Утилиты для проверки прав администраторов."""

import aiosqlite

from config import ADMINS, DB_PATH


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
