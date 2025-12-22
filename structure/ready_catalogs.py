"""Клавиатуры для управления и просмотра каталогов готовых изделий."""

from aiogram.types import InlineKeyboardMarkup

from structure.keyboards import InlineKeyboardButton


def ready_catalogs_manage_keyboard(catalogs: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки выбора каталога для управления в админ-панели."""

    rows = [
        [InlineKeyboardButton(text=cat["title"], callback_data=f"admin:ready:item:{cat['id']}")]
        for cat in catalogs
    ]
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ready_catalog_item_keyboard(catalog_id: int) -> InlineKeyboardMarkup:
    """Действия над выбранным каталогом в админ-панели."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"admin:ready:rename:{catalog_id}")],
            [InlineKeyboardButton(text="🔁 Заменить файл", callback_data=f"admin:ready:replace:{catalog_id}")],
            [InlineKeyboardButton(text="🗑 Удалить каталог", callback_data=f"admin:ready:delete:{catalog_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:ready:manage")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def ready_catalogs_user_keyboard(catalogs: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура выбора каталога для пользователей."""

    rows = [
        [InlineKeyboardButton(text=cat["title"], callback_data=f"ready_catalog:open:{cat['id']}")]
        for cat in catalogs
    ]
    rows.append(
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="ready_catalog:back"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ready_catalog_file_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для сообщения с файлом каталога."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="ready_catalog:back"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"),
            ]
        ]
    )
