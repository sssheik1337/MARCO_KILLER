"""Обработчики пользовательского меню."""
import logging
from collections import defaultdict
from typing import Any

import aiosqlite
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from config import PAGE_SIZE, ADMINS, DEFAULT_CITY, DB_PATH
from structure.keyboards import (
    catalog_menu,
    main_menu_with_link,
    pager,
    product_controls,
    stock_product_controls,
    empty_catalog_keyboard,
    city_selector,
    kb_stock_select_city,
)
from structure.markdown import (
    escape_user,
    send_md_safe,
    send_md_safe_to_chat,
)
from structure.states import SupportRequestState
from services.pagination import slice_page
from services import profiles
from data import db_utils
from services.exchange import current_range, range_label
from services.product_render import (
    as_float as _as_float,
    build_product_caption,
    format_money as _format_money,
    format_money_with_currency as _format_money_with_currency,
)

router = Router()
logger = logging.getLogger(__name__)

# Контекст карточек товаров: message_id → данные для возврата в список
_PRODUCT_CONTEXT: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
# Контекст карточек наличия: message_id → данные для возврата
_STOCK_CONTEXT: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)


# --- утилиты ---

def _is_admin(user_id: int) -> bool:
    return user_id in ADMINS


async def _main_menu(user_id: int) -> InlineKeyboardMarkup:
    """Возвращает главное меню с учётом ссылки на каталог готовых изделий."""

    return await main_menu_with_link(_is_admin(user_id))


def _user_city(user_id: int) -> str:
    """Возвращает выбранный пользователем город или значение по умолчанию."""

    return profiles.get_city_or_default(user_id, DEFAULT_CITY)


async def _ask_city(target: Message, action: str) -> None:
    """Отправляет предложение выбрать город для указанного раздела."""

    await send_md_safe(target, "Выберите город:", reply_markup=city_selector(action))


async def _catalog_items_count(table: str) -> int | None:
    """Возвращает количество позиций в каталоге или None, если таблицы нет."""

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cur.fetchone()
            return int(row[0]) if row else 0
    except aiosqlite.Error as exc:
        if "no such table" in str(exc).lower():
            return None
        logger.exception("Ошибка при чтении каталога %s: %s", table, exc)
        return None


async def _show_catalog_status(
    target: Message, user_id: int, table: str, title: str
) -> None:
    """Показывает пользователю статус выбранного каталога."""

    count = await _catalog_items_count(table)
    if not count:
        await send_md_safe(
            target,
            (
                "Каталог ещё не загружен. Пожалуйста, импортируйте "
                "прайс-листы в админ-панели."
            ),
            reply_markup=await _main_menu(user_id),
        )
        return

    await send_md_safe(
        target,
        f"В каталоге {title} доступно позиций: {count}.",
        reply_markup=await _main_menu(user_id),
    )


# --- настройки обращений ---

_REQUEST_TYPES = {
    "menu:callback": "callback",
    "menu:question": "question",
    "menu:boss": "boss",
    "menu:bug": "bug",
}

_REQUEST_PROMPTS = {
    "callback": "Оставьте номер телефона и удобное время для звонка.",
    "question": "Опишите ваш вопрос, и мы постараемся ответить как можно быстрее.",
    "boss": "Напишите сообщение для руководителя.",
    "bug": "Расскажите, с какой ошибкой вы столкнулись.",
}

_REQUEST_CONFIRMATIONS = {
    "callback": "Спасибо! Менеджер скоро свяжется с вами.",
    "question": "Спасибо! Мы подготовим ответ и вернёмся к вам.",
    "boss": "Спасибо! Руководитель получит ваше сообщение.",
    "bug": "Спасибо за обратную связь! Мы уже разбираемся.",
}

_REQUEST_TITLES = {
    "callback": "Заявка на звонок",
    "question": "Вопрос от клиента",
    "boss": "Сообщение для руководителя",
    "bug": "Сообщение об ошибке",
}


# --- утилиты каталога ---

def _label_sections(sections: list[str]) -> list[tuple[str, str]]:
    """Возвращает пары «заголовок → идентификатор» для разделов."""

    titles = {
        "fabrics": "🧵 Ткани",
        "hardware": "🔩 Фурнитура",
    }
    return [(titles.get(section, section.title()), section) for section in sections]


# --- главное меню ---

@router.callback_query(F.data == "home")
async def on_home(cb: CallbackQuery):
    menu_markup = await _main_menu(cb.from_user.id)
    await send_md_safe(
        cb.message,
        "Главное меню:",
        reply_markup=menu_markup,
    )
    await cb.answer()


async def _show_catalog_menu(target: Message) -> None:
    """Отображает меню выбора раздела каталога."""

    await send_md_safe(target, "Выберите раздел каталога:", reply_markup=catalog_menu())


@router.callback_query(F.data == "catalog")
async def on_catalog(cb: CallbackQuery):
    """Показывает выбор раздела каталога."""

    await _show_catalog_menu(cb.message)
    await cb.answer()


@router.callback_query(F.data == "catalog:fabrics")
async def on_catalog_fabrics(cb: CallbackQuery):
    """Открывает каталог тканей из общего прайс-листа."""

    await _show_catalog_status(cb.message, cb.from_user.id, "fabrics_catalog", "тканей")
    await cb.answer()


@router.callback_query(F.data == "catalog:hardware")
async def on_catalog_hardware(cb: CallbackQuery):
    """Открывает каталог фурнитуры из общего прайс-листа."""

    await _show_catalog_status(
        cb.message, cb.from_user.id, "hardware_catalog", "фурнитуры"
    )
    await cb.answer()


@router.callback_query(F.data == "stock")
async def on_stock(cb: CallbackQuery):
    """Показывает выбор города для раздела наличия."""

    await send_md_safe(
        cb.message,
        "Выберите город:",
        reply_markup=kb_stock_select_city(),
    )
    await cb.answer()



# --- каталог: разделы → категории → товары ---
CAT_SEC_PREFIX = "csec"
CAT_CAT_PREFIX = "ccat"
CAT_PROD_PREFIX = "cprodlist"

STOCK_SEC_PREFIX = "ssec"
STOCK_CAT_PREFIX = "scat"
STOCK_PROD_PREFIX = "sprodlist"


async def _send_catalog_sections(target: Message, user_id: int, page: int = 1) -> bool:
    """Показывает разделы каталога и возвращает успех отображения."""

    city = _user_city(user_id)
    try:
        sections = await db_utils.fetch_sections(city)
    except aiosqlite.Error as exc:
        if "no such table" in str(exc).lower():
            await send_md_safe(
                target,
                "Каталог ещё не загружен. Пожалуйста, импортируйте прайс-листы в админ-панели.",
                reply_markup=await _main_menu(user_id),
            )
            logger.warning("Таблица products недоступна: %s", exc)
            return False
        raise
    if not sections:
        await send_md_safe(
            target,
            "Каталог пуст: загрузите XLSX тканей и фурнитуры",
            reply_markup=empty_catalog_keyboard(_is_admin(user_id)),
        )
        return False

    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)

    rng, usd = await current_range()
    label = range_label(rng, usd)

    await send_md_safe(
        target,
        label,
        reply_markup=pager(CAT_SEC_PREFIX, page_items, page, total),
    )
    return True


async def _send_stock_sections(target: Message, user_id: int, page: int = 1) -> bool:
    """Показывает разделы наличия."""

    city = _user_city(user_id)
    sections = await db_utils.fetch_stock_sections(city)
    if not sections:
        await send_md_safe(
            target,
            "Наличие пока не загружено: импортируйте XLSX с остатками.",
            reply_markup=await _main_menu(user_id),
        )
        return False

    labeled = [(section.title(), section) for section in sections]
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)

    await send_md_safe(
        target,
        "Остатки по разделам:",
        reply_markup=pager(STOCK_SEC_PREFIX, page_items, page, total),
    )
    return True


def _format_quantity_value(qty: float | None, unit: str | None) -> str:
    """Форматирует остаток для карточки наличия."""

    if qty is None:
        return "—"
    if qty.is_integer():
        base = f"{int(qty)}"
    else:
        base = f"{qty:.2f}"
    if unit:
        return f"{base} {unit}"
    return base


@router.callback_query(F.data == "menu:catalog")
async def catalog_root(cb: CallbackQuery):
    await _show_catalog_menu(cb.message)
    await cb.answer()


@router.callback_query(F.data == "menu:stock")
async def stock_root(cb: CallbackQuery):
    if profiles.get_city(cb.from_user.id) is None:
        await _ask_city(cb.message, "stock")
        await cb.answer()
        return

    await _send_stock_sections(cb.message, cb.from_user.id, 1)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^city:(catalog|stock):(msk|spb)$"))
async def choose_city(cb: CallbackQuery):
    """Сохраняет выбранный город и открывает нужный раздел."""

    _, action, city = cb.data.split(":")
    profiles.set_city(cb.from_user.id, city)
    if action == "catalog":
        await _show_catalog_menu(cb.message)
    else:
        await _send_stock_sections(cb.message, cb.from_user.id, 1)
    await cb.answer("Город обновлён")


@router.callback_query(F.data.regexp(rf"^{CAT_SEC_PREFIX}:page:"))
async def catalog_sections_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[-1])
    city = _user_city(cb.from_user.id)
    sections = await db_utils.fetch_sections(city)
    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(CAT_SEC_PREFIX, page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{CAT_SEC_PREFIX}:open:"))
async def open_catalog_section(cb: CallbackQuery):
    section = cb.data.split(":")[-1]
    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_categories(section, city)
    if not cats:
        await send_md_safe(cb.message, "Здесь пока пусто.")
        await cb.answer()
        return
    enumerated = [(name, str(idx)) for idx, name in enumerate(cats)]
    page_items, page, total = slice_page(enumerated, 1, PAGE_SIZE)
    await send_md_safe(
        cb.message,
        "Категории:",
        reply_markup=pager(f"{CAT_CAT_PREFIX}:{section}", page_items, page, total),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{CAT_CAT_PREFIX}:[^:]+:page:"))
async def open_category_page(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    page = int(parts[-1])
    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_categories(section, city)
    enumerated = [(name, str(idx)) for idx, name in enumerate(cats)]
    page_items, page, total = slice_page(enumerated, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(f"{CAT_CAT_PREFIX}:{section}", page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{CAT_CAT_PREFIX}:[^:]+:open:"))
async def open_category(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    category_idx_raw = parts[-1]
    try:
        category_idx = int(category_idx_raw)
    except ValueError:
        logger.warning("Некорректный индекс категории: %s", category_idx_raw)
        await cb.answer("Категория недоступна", show_alert=True)
        return

    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_categories(section, city)
    if category_idx < 0 or category_idx >= len(cats):
        logger.warning(
            "Категория с индексом %s не найдена для раздела %s", category_idx, section
        )
        await cb.answer("Категория недоступна", show_alert=True)
        return

    category = cats[category_idx]

    prods = await db_utils.fetch_products_by_category(section, category, city)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    await send_md_safe(
        cb.message,
        category,
        reply_markup=pager(
            f"{CAT_PROD_PREFIX}:{section}:{category}", page_items, page, total
        ),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{CAT_PROD_PREFIX}:[^:]+:[^:]+:page:"))
async def product_list_page(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    category = parts[2]
    page = int(parts[-1])
    city = _user_city(cb.from_user.id)
    prods = await db_utils.fetch_products_by_category(section, category, city)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(
            f"{CAT_PROD_PREFIX}:{section}:{category}", page_items, page, total
        )
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{CAT_PROD_PREFIX}:.+:open:"))
async def product_card(cb: CallbackQuery):
    """Показывает карточку товара и запоминает, как вернуться назад."""

    parts = cb.data.split(":")
    pid = int(parts[-1])
    section = parts[1] if len(parts) > 1 else ""
    category = ":".join(parts[2:-2]) if len(parts) > 3 else ""

    city = _user_city(cb.from_user.id)
    p = await db_utils.fetch_product(pid)

    rng, usd = await current_range()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Карточка товара %s, диапазон %s, данные: %s", pid, rng, p)

    caption = build_product_caption(p, rng, usd)

    products = await db_utils.fetch_products_by_category(section, category, city)
    product_ids = [prod_id for prod_id, _ in products]
    try:
        index = product_ids.index(pid)
    except ValueError:
        index = 0
    page = index // PAGE_SIZE + 1 if product_ids else 1

    list_prefix = f"{CAT_PROD_PREFIX}:{section}:{category}"

    if p.get("image_url"):
        msg = await cb.message.answer_photo(
            p["image_url"], caption=caption,
            reply_markup=product_controls(pid)
        )
    else:
        msg = await send_md_safe(
            cb.message,
            caption,
            reply_markup=product_controls(pid),
        )

    _PRODUCT_CONTEXT[cb.from_user.id][msg.message_id] = {
        "section": section,
        "category": category,
        "prefix": list_prefix,
        "page": page,
        "product_id": pid,
        "city": city,
    }

    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_SEC_PREFIX}:page:"))
async def stock_sections_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[-1])
    city = _user_city(cb.from_user.id)
    sections = await db_utils.fetch_stock_sections(city)
    labeled = [(section.title(), section) for section in sections]
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(STOCK_SEC_PREFIX, page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_SEC_PREFIX}:open:"))
async def open_stock_section(cb: CallbackQuery):
    section = cb.data.split(":")[-1]
    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_stock_categories(section, city)
    if not cats:
        await send_md_safe(cb.message, "Здесь пока нет остатков.")
        await cb.answer()
        return
    enumerated = [(name, str(idx)) for idx, name in enumerate(cats)]
    page_items, page, total = slice_page(enumerated, 1, PAGE_SIZE)
    await send_md_safe(
        cb.message,
        "Категории остатков:",
        reply_markup=pager(f"{STOCK_CAT_PREFIX}:{section}", page_items, page, total),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_CAT_PREFIX}:[^:]+:page:"))
async def stock_category_page(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    page = int(parts[-1])
    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_stock_categories(section, city)
    enumerated = [(name, str(idx)) for idx, name in enumerate(cats)]
    page_items, page, total = slice_page(enumerated, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(f"{STOCK_CAT_PREFIX}:{section}", page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_CAT_PREFIX}:[^:]+:open:"))
async def open_stock_category(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    category_idx_raw = parts[-1]
    try:
        category_idx = int(category_idx_raw)
    except ValueError:
        logger.warning("Некорректный индекс категории в остатках: %s", category_idx_raw)
        await cb.answer("Категория недоступна", show_alert=True)
        return

    city = _user_city(cb.from_user.id)
    cats = await db_utils.fetch_stock_categories(section, city)
    if category_idx < 0 or category_idx >= len(cats):
        logger.warning(
            "Категория наличия с индексом %s не найдена для раздела %s", category_idx, section
        )
        await cb.answer("Категория недоступна", show_alert=True)
        return

    category = cats[category_idx]
    prods = await db_utils.fetch_stock_products_by_category(section, category, city)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    await send_md_safe(
        cb.message,
        category,
        reply_markup=pager(
            f"{STOCK_PROD_PREFIX}:{section}:{category}", page_items, page, total
        ),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_PROD_PREFIX}:[^:]+:[^:]+:page:"))
async def stock_product_page(cb: CallbackQuery):
    parts = cb.data.split(":")
    section = parts[1]
    category = parts[2]
    page = int(parts[-1])
    city = _user_city(cb.from_user.id)
    prods = await db_utils.fetch_stock_products_by_category(section, category, city)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(
            f"{STOCK_PROD_PREFIX}:{section}:{category}", page_items, page, total
        )
    )
    await cb.answer()


@router.callback_query(F.data.regexp(rf"^{STOCK_PROD_PREFIX}:.+:open:"))
async def stock_product_card(cb: CallbackQuery):
    """Показывает карточку остатка и запоминает контекст возврата."""

    parts = cb.data.split(":")
    pid = int(parts[-1])
    section = parts[1] if len(parts) > 1 else ""
    category = ":".join(parts[2:-2]) if len(parts) > 3 else ""

    city = _user_city(cb.from_user.id)
    item = await db_utils.fetch_stock_item(pid)

    lines = [f"*{escape_user(item.get('name'))}*"]

    def _line(label: str, value: object) -> str:
        text = value if value not in (None, "") else "-"
        return escape_user(f"{label}: {text}")

    lines.append(_line("Артикул", item.get("article")))
    lines.append(_line("Категория", item.get("category")))
    lines.append(_line("Статус", item.get("status")))
    qty_text = _format_quantity_value(
        _as_float(item.get("quantity")), item.get("unit") if isinstance(item.get("unit"), str) else None
    )
    lines.append(_line("Наличие", qty_text))

    caption = "\n".join(lines)

    products = await db_utils.fetch_stock_products_by_category(section, category, city)
    product_ids = [prod_id for prod_id, _ in products]
    try:
        index = product_ids.index(pid)
    except ValueError:
        index = 0
    page = index // PAGE_SIZE + 1 if product_ids else 1

    list_prefix = f"{STOCK_PROD_PREFIX}:{section}:{category}"

    msg = await send_md_safe(
        cb.message,
        caption,
        reply_markup=stock_product_controls(pid),
    )

    _STOCK_CONTEXT[cb.from_user.id][msg.message_id] = {
        "section": section,
        "category": category,
        "prefix": list_prefix,
        "page": page,
        "product_id": pid,
        "city": city,
    }

    await cb.answer()


# --- карточка: возврат и заглушки ---

@router.callback_query(F.data == "back")
async def prod_back(cb: CallbackQuery):
    """Возвращает пользователя к списку товаров и удаляет карточку."""

    user_id = cb.from_user.id
    context_source = "catalog"
    context_map = _PRODUCT_CONTEXT.get(user_id)
    context = context_map.pop(cb.message.message_id, None) if context_map else None
    if context_map is not None and not context_map:
        _PRODUCT_CONTEXT.pop(user_id, None)

    if context is None:
        context_source = "stock"
        context_map = _STOCK_CONTEXT.get(user_id)
        context = context_map.pop(cb.message.message_id, None) if context_map else None
        if context_map is not None and not context_map:
            _STOCK_CONTEXT.pop(user_id, None)

    if context:
        if context_source == "catalog":
            city = context.get("city") or _user_city(user_id)
            products = await db_utils.fetch_products_by_category(
                context["section"],
                context["category"],
                city,
            )
        else:
            city = context.get("city") or _user_city(user_id)
            products = await db_utils.fetch_stock_products_by_category(
                context["section"],
                context["category"],
                city,
            )

        items = [(name, str(pid)) for pid, name in products]
        page_items, page, total = slice_page(
            items, context.get("page", 1), PAGE_SIZE
        )
        reply_markup = pager(context.get("prefix", ""), page_items, page, total)
        title = context.get("category") or "Товары"
        await send_md_safe(cb.message, title, reply_markup=reply_markup)
# --- информационные страницы ---

async def _send_setting_text(target: Message, user_id: int, key: str, empty_text: str) -> None:
    """Отправляет пользователю текст из настроек или запасной вариант."""

    stored = await db_utils.get_setting(key, "")
    reply_markup = await _main_menu(user_id)
    if stored:
        await send_md_safe(target, stored, reply_markup=reply_markup)
    else:
        await send_md_safe(
            target,
            empty_text,
            reply_markup=reply_markup,
        )


_INFO_COMMANDS = {
    "📇 Контакты": ("contacts", "Контакты пока не заполнены."),
    "🗺️ Как проехать": ("address", "Адрес пока не указан."),
    "📄 Реквизиты": ("requisites", "Реквизиты пока не добавлены."),
}


@router.callback_query(F.data == "menu:contacts")
async def show_contacts(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "contacts",
            "Контакты пока не заполнены.",
        )
    await cb.answer()


@router.callback_query(F.data == "menu:route")
async def show_route(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "address",
            "Адрес пока не указан.",
        )
    await cb.answer()


@router.callback_query(F.data == "menu:requisites")
async def show_requisites(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "requisites",
            "Реквизиты пока не добавлены.",
        )
    await cb.answer()


@router.message(F.text.in_(tuple(_INFO_COMMANDS.keys())))
async def show_info_message(msg: Message):
    """Обрабатывает текстовые запросы на контакты, адрес и реквизиты."""

    if not msg.from_user:
        return

    key, fallback = _INFO_COMMANDS[msg.text]
    await _send_setting_text(msg, msg.from_user.id, key, fallback)



# --- обращения пользователей ---

async def _start_request(cb: CallbackQuery, state: FSMContext, request_key: str) -> None:
    """Подготавливает сбор данных для выбранного обращения."""

    await state.set_state(SupportRequestState.waiting_text)
    await state.update_data(request_type=request_key)
    await send_md_safe(
        cb.message,
        _REQUEST_PROMPTS[request_key],
    )
    await cb.answer()


async def _notify_admins(msg: Message, request_key: str, user_text: str) -> None:
    """Отправляет уведомление администраторам о новом обращении."""

    if not ADMINS:
        return

    user = msg.from_user
    if not user:
        return

    full_name = user.full_name or "Без имени"
    lines = [
        f"🔔 {escape_user(_REQUEST_TITLES[request_key])}",
        f"Имя: {escape_user(full_name)}",
    ]
    if user.username:
        lines.append(f"Юзернейм: @{escape_user(user.username)}")
    lines.extend(
        [
            "Сообщение:",
            escape_user(user_text),
        ]
    )
    admin_message = "\n".join(lines)

    for admin_id in ADMINS:
        try:
            await msg.bot.send_message(
                admin_id,
                admin_message,
            )
        except Exception as exc:
            logger.warning("Не удалось уведомить администратора %s: %s", admin_id, exc)


def _extract_user_input(msg: Message) -> str:
    """Формирует текст обращения из сообщения пользователя."""

    if msg.text and msg.text.strip():
        return msg.text.strip()

    if msg.contact:
        parts: list[str] = []
        if msg.contact.phone_number:
            if msg.from_user:
                profiles.set_phone(msg.from_user.id, msg.contact.phone_number)
            parts.append(f"Телефон: {msg.contact.phone_number}")
        name_bits = [msg.contact.first_name or "", msg.contact.last_name or ""]
        name = " ".join(part for part in name_bits if part).strip()
        if name:
            parts.append(f"Имя: {name}")
        if msg.contact.vcard:
            parts.append(f"VCard: {msg.contact.vcard}")
        return "\n".join(parts)

    if msg.caption and msg.caption.strip():
        return msg.caption.strip()

    return ""


@router.callback_query(F.data.in_(tuple(_REQUEST_TYPES.keys())))
async def start_support_request(cb: CallbackQuery, state: FSMContext):
    request_key = _REQUEST_TYPES[cb.data]
    await _start_request(cb, state, request_key)


@router.message(SupportRequestState.waiting_text)
async def handle_support_request(msg: Message, state: FSMContext):
    data = await state.get_data()
    request_key = data.get("request_type")
    if not request_key:
        await state.clear()
        return

    user_text = _extract_user_input(msg)
    if not user_text:
        await send_md_safe(
            msg,
            "Пожалуйста, отправьте текстовое сообщение или контакт.",
        )
        return

    await _notify_admins(msg, request_key, user_text)

    user_id = msg.from_user.id if msg.from_user else 0
    await send_md_safe(
        msg,
        _REQUEST_CONFIRMATIONS[request_key],
        reply_markup=await _main_menu(user_id),
    )

    await state.clear()
