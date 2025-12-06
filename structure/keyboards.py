from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from data import db_utils


def main_menu(is_admin: bool, ready_catalog_url: str | None = None) -> InlineKeyboardMarkup:
    """Формирует главное меню с разделами и ссылкой на готовые изделия."""

    ready_url = ready_catalog_url or "https://example.com"

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📚 Каталог", callback_data="catalog"),
            InlineKeyboardButton(text="📦 Наличие", callback_data="stock"),
        ],
        [
            InlineKeyboardButton(text="📇 Контакты", callback_data="menu:contacts"),
            InlineKeyboardButton(text="🧭 Как проехать", callback_data="menu:route"),
        ],
        [
            InlineKeyboardButton(text="📄 Реквизиты", callback_data="menu:requisites"),
            InlineKeyboardButton(text="📞 Заявка на звонок", callback_data="menu:callback"),
        ],
        [
            InlineKeyboardButton(text="❓ Задать вопрос", callback_data="menu:question"),
            InlineKeyboardButton(
                text="👤 Связь с руководителем", callback_data="menu:boss"
            ),
        ],
        [
            InlineKeyboardButton(text="🐞 Сообщить об ошибке", callback_data="menu:bug"),
        ],
        [
            InlineKeyboardButton(
                text="📸 Каталог готовых изделий", url=ready_url
            ),
        ],
    ]

    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin:open")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def main_menu_with_link(is_admin: bool) -> InlineKeyboardMarkup:
    """Возвращает главное меню с учётом ссылки на каталог готовых изделий."""

    ready_link = await db_utils.get_setting("ready_catalog_url", "")
    return main_menu(is_admin, ready_link or None)


def catalog_menu() -> InlineKeyboardMarkup:
    """Клавиатура выбора раздела каталога."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧵 Ткани", callback_data="catalog:fabrics")],
            [InlineKeyboardButton(text="🔩 Фурнитура", callback_data="catalog:hardware")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def stock_city_menu() -> InlineKeyboardMarkup:
    """Клавиатура выбора города для раздела наличия."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Москва", callback_data="stock:city:msk")],
            [InlineKeyboardButton(text="Санкт-Петербург", callback_data="stock:city:spb")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def stock_section_menu(city: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора раздела наличия для выбранного города."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧵 Ткани", callback_data=f"stock:{city}:fabrics"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔩 Фурнитура", callback_data=f"stock:{city}:hardware"
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def kb_stock_select_city() -> InlineKeyboardMarkup:
    """Клавиатура выбора города для раздела наличия."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Москва", callback_data="stock_city:msk")],
            [InlineKeyboardButton(text="Санкт-Петербург", callback_data="stock_city:spb")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def kb_stock_sections(city: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора раздела наличия для выбранного города."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧵 Ткани", callback_data=f"stock_section:{city}:fabrics"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔩 Фурнитура", callback_data=f"stock_section:{city}:hardware"
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def kb_stock_kinds(city: str, section: str, kinds: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Клавиатура выбора вида номенклатуры."""

    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"stock:types:{city}:{section}:{slug}:1")]
        for title, slug in kinds
    ]
    rows.append(
        [
            InlineKeyboardButton(text="⬅ Назад", callback_data=f"stock_section:{city}:{section}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_types_keyboard(
    city: str,
    section: str,
    kind_slug: str,
    types: list[tuple[str, str]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора типа номенклатуры с пагинацией."""

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=title,
                callback_data=f"stock:list:{city}:{section}:{kind_slug}:{slug}:1",
            )
        ]
        for title, slug in types
    ]

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="◀ Назад",
                callback_data=f"stock:types:{city}:{section}:{kind_slug}:{page - 1}",
            )
        )

    nav_row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"))

    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Вперёд ▶",
                callback_data=f"stock:types:{city}:{section}:{kind_slug}:{page + 1}",
            )
        )

    rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data=f"stock:kindlist:{city}:{section}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_stock_list_keyboard(
    city: str,
    section: str,
    kind_slug: str | None,
    type_slug: str | None,
    page: int,
    total_pages: int,
    back_callback: str | None,
    *,
    flat: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура пагинации списка остатков."""

    def _page_callback(target_page: int) -> str:
        if flat:
            return f"stock:flat:{city}:{section}:{target_page}"
        return f"stock:list:{city}:{section}:{kind_slug or 'all'}:{type_slug or 'all'}:{target_page}"

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀ Назад", callback_data=_page_callback(page - 1)))

    nav_row.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"))

    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=_page_callback(page + 1)))

    rows: list[list[InlineKeyboardButton]] = [nav_row]
    if back_callback:
        rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data=back_callback)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def empty_catalog_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    """Клавиатура для пустого каталога до первичного импорта."""

    home_button = InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")

    if is_admin:
        rows = [
            [
                InlineKeyboardButton(
                    text="📤 Ткани Москва (XLSX)",
                    callback_data="admin:import:fabrics_msk",
                ),
                InlineKeyboardButton(
                    text="📤 Ткани СПБ (XLSX)",
                    callback_data="admin:import:fabrics_spb",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📤 Фурнитура Москва (XLSX)",
                    callback_data="admin:import:hardware_msk",
                ),
                InlineKeyboardButton(
                    text="📤 Фурнитура СПБ (XLSX)",
                    callback_data="admin:import:hardware_spb",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Наличие Москва (XLSX)",
                    callback_data="admin:import:stock_msk",
                ),
                InlineKeyboardButton(
                    text="📦 Наличие СПБ (XLSX)",
                    callback_data="admin:import:stock_spb",
                ),
            ],
            [home_button],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton(text="Связаться", callback_data="menu:contacts"),
                home_button,
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены для сценариев с состояниями."""

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")]]
    )

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

def product_controls(product_id: int) -> InlineKeyboardMarkup:
    """Клавиатура карточки товара без корзины."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def stock_product_controls(product_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для карточки остатка без корзины."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def usd_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления экраном курса USD."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:usd:refresh")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")],
        ]
    )


def import_result_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после успешного импорта с быстрым переходом в каталог."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Открыть каталог", callback_data="menu:catalog")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def city_selector(action: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора города для указанного раздела."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Москва",
                    callback_data=f"city:{action}:msk",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Санкт-Петербург",
                    callback_data=f"city:{action}:spb",
                )
            ],
        ]
    )
