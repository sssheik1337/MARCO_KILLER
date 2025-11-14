from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import PAGE_SIZE

def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📚 Каталог", callback_data="menu:catalog"),
         InlineKeyboardButton(text="💵 Прайс", callback_data="menu:price")],
        [InlineKeyboardButton(text="🧺 Корзина", callback_data="menu:cart"),
         InlineKeyboardButton(text="📦 Наличие", callback_data="menu:stock")],
        [InlineKeyboardButton(text="📇 Контакты", callback_data="menu:contacts"),
         InlineKeyboardButton(text="🗺️ Как проехать", callback_data="menu:route")],
        [InlineKeyboardButton(text="📄 Реквизиты", callback_data="menu:requisites")],
        [InlineKeyboardButton(text="📞 Заявка на звонок", callback_data="menu:callback"),
         InlineKeyboardButton(text="❓ Задать вопрос", callback_data="menu:question")],
        [InlineKeyboardButton(text="👨‍💼 Связь с руководителем", callback_data="menu:boss"),
         InlineKeyboardButton(text="🐞 Сообщить об ошибке", callback_data="menu:bug")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def empty_catalog_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    """Клавиатура для пустого каталога до первичного импорта."""

    if is_admin:
        rows = [
            [
                InlineKeyboardButton(
                    text="📤 Импорт тканей (XLSX)",
                    callback_data="admin:import:fabrics",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Импорт фурнитуры (XLSX)",
                    callback_data="admin:import:hardware",
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="Связаться", callback_data="menu:contacts")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def pager(prefix: str, items: list[tuple[str, str]], page: int, total: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"{prefix}:open:{item_id}")]
            for title, item_id in items]
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:page:{page-1}"))
    nav_row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"))
    if page < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:page:{page+1}"))
    rows.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def product_controls(product_id: int, qty: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➖", callback_data=f"prod:dec:{product_id}"),
         InlineKeyboardButton(text=str(qty), callback_data="noop"),
         InlineKeyboardButton(text="➕", callback_data=f"prod:inc:{product_id}")],
        [InlineKeyboardButton(text="🧺 В корзину", callback_data=f"prod:add:{product_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
         InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
    ])


def cart_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    """Клавиатура управления корзиной."""

    rows: list[list[InlineKeyboardButton]] = []
    if has_items:
        rows.append(
            [
                InlineKeyboardButton(text="🧹 Очистить", callback_data="cart:clear"),
                InlineKeyboardButton(text="✅ Оформить", callback_data="cart:checkout"),
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def usd_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления экраном курса USD."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:usd:refresh")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )
