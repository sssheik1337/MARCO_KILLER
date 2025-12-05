"""Обработчики выбора города и раздела для остатков."""

import re
from collections import defaultdict

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import PAGE_SIZE
from data.stock_interface import load_city_stock
from data.stock_models import StockItemCity
from services.pagination import slice_page
from structure.keyboards import (
    kb_stock_kinds,
    kb_stock_sections,
    kb_stock_types,
    stock_items_keyboard,
)
from structure.markdown import edit_md_safe, send_md_safe

router = Router()

CITY_TITLES = {"msk": "Москва", "spb": "Санкт-Петербург"}
SECTION_TITLES = {"fabrics": "Ткани", "hardware": "Фурнитура"}

_STOCK_SELECTIONS: dict[int, dict] = defaultdict(dict)


def _slugify(value: str, used: set[str]) -> str:
    """Создаёт компактный slug для callback-data."""

    base = re.sub(r"[^a-z0-9-]", "", (value or "").strip().lower().replace(" ", "-"))
    base = base or "item"
    slug = base
    counter = 2
    while slug in used:
        slug = f"{base}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def _match_slug(title: str | None, expected: str) -> bool:
    """Проверяет соответствие значения ожидаемому slug."""

    if not title:
        return False
    return _slugify(title, set()) == expected


async def send_stock_page(message: Message, stock: StockItemCity, page: int) -> None:
    """Отображает страницу остатков с пагинацией."""

    if not stock.items:
        markup = stock_items_keyboard(
            city=stock.city,
            section=stock.section,
            page=1,
            total_pages=1,
            back_callback=stock.back_callback,
            kind_slug=stock.kind_slug,
            type_slug=stock.type_slug,
            flat=True,
        )
        await send_md_safe(
            message,
            "Данные об остатках пока отсутствуют.",
            reply_markup=markup,
        )
        return

    page_items, page, total_pages = slice_page(stock.items, page, PAGE_SIZE)
    start_index = (page - 1) * PAGE_SIZE + 1
    lines: list[str] = []

    for offset, item in enumerate(page_items, start=start_index):
        line = f"{offset}) {item.name}"
        if item.quantity is not None and item.unit:
            line += f" — {item.quantity:g} {item.unit}"
        if item.extra_info:
            line += f" ({item.extra_info})"
        lines.append(line)

    city_label = CITY_TITLES.get(stock.city, stock.city)
    section_label = SECTION_TITLES.get(stock.section, stock.section)

    header: list[str] = [f"{section_label} · {city_label}"]
    if stock.kind:
        header.append(f"Вид: {stock.kind}")
    if stock.item_type:
        header.append(f"Тип: {stock.item_type}")
    header.append(f"Страница {page}/{total_pages}")

    text = "\n".join([*header, "", *lines])
    markup = stock_items_keyboard(
        city=stock.city,
        section=stock.section,
        page=page,
        total_pages=total_pages,
        kind_slug=stock.kind_slug,
        type_slug=stock.type_slug,
        back_callback=stock.back_callback,
        flat=not stock.kind_slug,
    )

    try:
        await edit_md_safe(message, text, reply_markup=markup)
    except Exception:
        await send_md_safe(message, text, reply_markup=markup)


async def _show_kinds(message: Message, user_id: int, city: str, section: str) -> None:
    """Показывает список видов номенклатуры или плоский список, если видов нет."""

    stock = await load_city_stock(city, section)
    selection = _STOCK_SELECTIONS[user_id]
    selection["city"] = city
    selection["section"] = section
    selection.pop("type_map", None)

    kinds = sorted({item.kind for item in stock.items if item.kind})
    if not stock.items:
        stock.back_callback = f"stock_section:{city}:{section}"
        await send_stock_page(message, stock, 1)
        return

    if not kinds:
        stock.back_callback = f"stock_section:{city}:{section}"
        await send_stock_page(message, stock, 1)
        return

    used: set[str] = set()
    selection["kind_map"] = {}
    kind_rows: list[tuple[str, str]] = []
    for kind in kinds:
        slug = _slugify(kind, used)
        selection["kind_map"][slug] = kind
        kind_rows.append((kind, slug))

    await send_md_safe(
        message,
        "Выберите вид номенклатуры:",
        reply_markup=kb_stock_kinds(city, section, kind_rows),
    )


@router.callback_query(F.data.regexp(r"^stock_city:(msk|spb)$"))
async def on_stock_city_selected(cb: CallbackQuery):
    """Сохраняет выбранный город и предлагает выбрать раздел остатков."""

    city = cb.data.split(":")[-1]
    _STOCK_SELECTIONS[cb.from_user.id].clear()
    _STOCK_SELECTIONS[cb.from_user.id]["city"] = city
    await send_md_safe(
        cb.message,
        "Выберите раздел остатков:",
        reply_markup=kb_stock_sections(city),
    )
    await cb.answer("Город выбран")


@router.callback_query(F.data.regexp(r"^stock_section:(msk|spb):(fabrics|hardware)$"))
async def on_stock_select_section(cb: CallbackQuery):
    """Фиксирует выбор раздела остатков и открывает список видов."""

    _, city, section = cb.data.split(":")
    await _show_kinds(cb.message, cb.from_user.id, city, section)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:kind:(msk|spb):(fabrics|hardware):.+"))
async def on_stock_kind(cb: CallbackQuery):
    """Показывает список типов выбранного вида номенклатуры."""

    parts = cb.data.split(":")
    _, _, city, section, kind_slug, *rest = parts
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section
    selection["kind_slug"] = kind_slug

    stock = await load_city_stock(city, section)
    kind_map = selection.get("kind_map", {})
    selected_kind = kind_map.get(kind_slug)
    if not selected_kind:
        selected_kind = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)

    if not selected_kind:
        await send_md_safe(
            cb.message,
            "Данные об остатках пока отсутствуют.",
            reply_markup=kb_stock_sections(city),
        )
        await cb.answer()
        return

    types = sorted({item.item_type for item in stock.items if item.kind == selected_kind and item.item_type})
    if not types:
        kind_rows = [(title, slug) for slug, title in kind_map.items()]
        await send_md_safe(
            cb.message,
            "Нет остатков в выбранной группе.",
            reply_markup=kb_stock_kinds(city, section, kind_rows),
        )
        await cb.answer()
        return

    used: set[str] = set()
    type_rows: list[tuple[str, str]] = []
    selection.setdefault("type_map", {})[kind_slug] = {}
    for item_type in types:
        slug = _slugify(item_type, used)
        selection["type_map"][kind_slug][slug] = item_type
        type_rows.append((item_type, slug))

    await send_md_safe(
        cb.message,
        "Выберите тип номенклатуры:",
        reply_markup=kb_stock_types(city, section, kind_slug, type_rows),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:kindlist:(msk|spb):(fabrics|hardware)$"))
async def on_stock_kind_list(cb: CallbackQuery):
    """Возврат к списку видов."""

    _, _, city, section = cb.data.split(":")
    await _show_kinds(cb.message, cb.from_user.id, city, section)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:typelist:(msk|spb):(fabrics|hardware):.+"))
async def on_stock_type_list(cb: CallbackQuery):
    """Возврат к списку типов выбранного вида."""

    _, _, city, section, kind_slug = cb.data.split(":")
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section
    selection["kind_slug"] = kind_slug

    stock = await load_city_stock(city, section)
    kind_title = selection.get("kind_map", {}).get(kind_slug)
    if not kind_title:
        kind_title = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)

    if not kind_title:
        await _show_kinds(cb.message, cb.from_user.id, city, section)
        await cb.answer()
        return

    types = sorted({item.item_type for item in stock.items if item.kind == kind_title and item.item_type})
    if not types:
        await send_md_safe(
            cb.message,
            "Нет остатков в выбранной группе.",
            reply_markup=kb_stock_kinds(
                city,
                section,
                [(title, slug) for slug, title in selection.get("kind_map", {}).items()],
            ),
        )
        await cb.answer()
        return

    stored_types = selection.get("type_map", {}).get(kind_slug)
    if stored_types:
        type_rows = [(title, slug) for slug, title in stored_types.items()]
    else:
        used: set[str] = set()
        selection.setdefault("type_map", {})[kind_slug] = {}
        type_rows = []
        for item_type in types:
            slug = _slugify(item_type, used)
            selection["type_map"][kind_slug][slug] = item_type
            type_rows.append((item_type, slug))

    await send_md_safe(
        cb.message,
        "Выберите тип номенклатуры:",
        reply_markup=kb_stock_types(city, section, kind_slug, type_rows),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:type:(msk|spb):(fabrics|hardware):.+"))
async def on_stock_type(cb: CallbackQuery):
    """Отображает товары выбранного типа номенклатуры с пагинацией."""

    parts = cb.data.split(":")
    if len(parts) < 7:
        await cb.answer()
        return

    _, _, city, section, kind_slug, type_slug, page_str = parts
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    kind_title = selection.get("kind_map", {}).get(kind_slug)
    type_title = selection.get("type_map", {}).get(kind_slug, {}).get(type_slug)

    stock = await load_city_stock(city, section)
    if not kind_title:
        kind_title = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)
    if not type_title:
        type_title = next((item.item_type for item in stock.items if _match_slug(item.item_type, type_slug)), None)

    filtered_items = [
        item
        for item in stock.items
        if item.kind == kind_title and item.item_type == type_title
    ]

    if not filtered_items:
        await send_md_safe(
            cb.message,
            "Нет позиций для выбранного типа номенклатуры.",
            reply_markup=kb_stock_types(
                city,
                section,
                kind_slug,
                [
                    (title, slug)
                    for slug, title in selection.get("type_map", {}).get(kind_slug, {}).items()
                ],
            ),
        )
        await cb.answer()
        return

    filtered_stock = StockItemCity(
        city=city,
        section=section,
        items=filtered_items,
        kind=kind_title,
        item_type=type_title,
        kind_slug=kind_slug,
        type_slug=type_slug,
        back_callback=f"stock:kind:{city}:{section}:{kind_slug}:1",
    )

    await send_stock_page(cb.message, filtered_stock, int(page_str))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:flat:(msk|spb):(fabrics|hardware):\d+$"))
async def on_stock_flat(cb: CallbackQuery):
    """Пагинация по плоскому списку остатков без иерархии."""

    _, _, city, section, page_str = cb.data.split(":")
    stock = await load_city_stock(city, section)
    stock.back_callback = f"stock_section:{city}:{section}"
    await send_stock_page(cb.message, stock, int(page_str))
    await cb.answer()

