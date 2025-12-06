"""Обработчики выбора города и раздела для остатков."""

import re
from collections import defaultdict

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from data.stock_interface import load_city_stock
from data.stock_models import StockItemCity
from services.pagination import slice_page
from structure.keyboards import (
    build_stock_list_keyboard,
    build_types_keyboard,
    kb_stock_kinds,
    kb_stock_sections,
)
from structure.markdown import MarkdownV2Escaper, edit_md_safe, send_md_safe

router = Router()

CITY_TITLES = {"msk": "Москва", "spb": "Санкт-Петербург"}
SECTION_TITLES = {"fabrics": "Ткани", "hardware": "Фурнитура"}

TYPE_PAGE_SIZE = 10
ITEM_PAGE_SIZE = 5

_STOCK_SELECTIONS: dict[int, dict] = defaultdict(dict)


def escape_md(text: str | None) -> str:
    """Экранирует текст для MarkdownV2."""

    return MarkdownV2Escaper.escape_plain(text or "")


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


def _parse_max_roll(extra_info: str | None) -> str | None:
    """Выделяет значение максимального рулона из строки."""

    if not extra_info:
        return None

    normalized = extra_info.replace(",", ".")
    match = re.search(r"(?::\s*|\s)(\d+(?:\.\d+)?)", normalized)
    if match:
        return match.group(1)

    fallback = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if fallback:
        return fallback.group(1)

    return None


async def send_stock_page(message: Message, stock: StockItemCity, page: int) -> None:
    """Отображает страницу остатков с пагинацией."""

    if not stock.items:
        markup = build_stock_list_keyboard(
            city=stock.city,
            section=stock.section,
            kind_slug=stock.kind_slug,
            type_slug=stock.type_slug,
            page=1,
            total_pages=1,
            back_callback=stock.back_callback,
            flat=True,
        )
        await send_md_safe(message, "Данные об остатках пока отсутствуют.", reply_markup=markup)
        return

    page_items, page, total_pages = slice_page(stock.items, page, ITEM_PAGE_SIZE)
    start_index = (page - 1) * ITEM_PAGE_SIZE + 1
    lines: list[str] = []

    for offset, item in enumerate(page_items, start=start_index):
        item_lines: list[str] = [f"{offset}) *{escape_md(item.name)}*"]

        code_value = (
            f"`{escape_md(item.code)}`" if item.code else escape_md("отсутствует")
        )
        item_lines.append(f"Код: {code_value}")

        if item.quantity is not None and item.unit:
            item_lines.append(f"Наличие: {item.quantity} {item.unit}")

        max_roll = _parse_max_roll(item.extra_info)
        if max_roll is not None:
            item_lines.append(f"Макс.рулон: {max_roll}")

        lines.append("\n".join(item_lines))

    city_label = escape_md(CITY_TITLES.get(stock.city, stock.city))
    section_label = escape_md(SECTION_TITLES.get(stock.section, stock.section))

    header: list[str] = [f"{section_label} • {city_label}"]
    if stock.kind:
        header.append(f"Вид: {escape_md(stock.kind)}")
    if stock.item_type:
        header.append(f"Тип: {escape_md(stock.item_type)}")
    header.append(f"Страница {page}/{total_pages}")

    text = "\n\n".join(["\n".join(header), *lines])
    markup = build_stock_list_keyboard(
        city=stock.city,
        section=stock.section,
        kind_slug=stock.kind_slug,
        type_slug=stock.type_slug,
        page=page,
        total_pages=total_pages,
        back_callback=stock.back_callback,
        flat=not stock.kind_slug or not stock.type_slug,
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
        stock.kind_slug = None
        stock.type_slug = None
        await send_stock_page(message, stock, 1)
        return

    if not kinds:
        stock.back_callback = f"stock_section:{city}:{section}"
        stock.kind_slug = None
        stock.type_slug = None
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


@router.callback_query(F.data.regexp(r"^stock:types:(msk|spb):(fabrics|hardware):.+"))
async def on_stock_types(cb: CallbackQuery):
    """Показывает типы номенклатуры с пагинацией."""

    parts = cb.data.split(":")
    _, _, city, section, kind_slug, page_str = parts
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
    for item_type in types:
        slug = _slugify(item_type, used)
        type_rows.append((item_type, slug))

    page_items, page, total_pages = slice_page(type_rows, int(page_str), TYPE_PAGE_SIZE)
    selection.setdefault("type_map", {})[kind_slug] = {slug: title for title, slug in type_rows}

    city_label = CITY_TITLES.get(city, city)
    text = (
        f"{escape_md(selected_kind)} — {escape_md(city_label)}\n"
        f"Страница {page}/{total_pages}"
    )

    await send_md_safe(
        cb.message,
        text,
        reply_markup=build_types_keyboard(city, section, kind_slug, page_items, page, total_pages),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:kindlist:(msk|spb):(fabrics|hardware)$"))
async def on_stock_kind_list(cb: CallbackQuery):
    """Возврат к списку видов."""

    _, _, city, section = cb.data.split(":")
    await _show_kinds(cb.message, cb.from_user.id, city, section)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:list:(msk|spb):(fabrics|hardware):.+"))
async def on_stock_list(cb: CallbackQuery):
    """Отображает товары выбранного типа с пагинацией."""

    parts = cb.data.split(":")
    if len(parts) < 7:
        await cb.answer()
        return

    _, _, city, section, kind_slug, type_slug, page_str = parts
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section
    stock = await load_city_stock(city, section)

    kind_title = None if kind_slug == "all" else selection.get("kind_map", {}).get(kind_slug)
    if kind_title is None and kind_slug != "all":
        kind_title = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)

    type_title = None if type_slug == "all" else selection.get("type_map", {}).get(kind_slug, {}).get(type_slug)
    if type_title is None and type_slug != "all":
        type_title = next((item.item_type for item in stock.items if _match_slug(item.item_type, type_slug)), None)

    filtered_items = [
        item
        for item in stock.items
        if (kind_title is None or item.kind == kind_title)
        and (type_title is None or item.item_type == type_title)
    ]

    if not filtered_items:
        markup = build_stock_list_keyboard(
            city=city,
            section=section,
            kind_slug=None if kind_slug == "all" else kind_slug,
            type_slug=None if type_slug == "all" else type_slug,
            page=1,
            total_pages=1,
            back_callback=f"stock:types:{city}:{section}:{kind_slug}:1" if kind_slug != "all" else f"stock_section:{city}:{section}",
            flat=kind_slug == "all",
        )
        await send_md_safe(cb.message, "В выбранной категории пока нет остатков.", reply_markup=markup)
        await cb.answer()
        return

    filtered_stock = StockItemCity(
        city=city,
        section=section,
        items=filtered_items,
        kind=kind_title,
        item_type=type_title,
        kind_slug=None if kind_slug == "all" else kind_slug,
        type_slug=None if type_slug == "all" else type_slug,
        back_callback=f"stock:types:{city}:{section}:{kind_slug}:1" if kind_slug != "all" else f"stock_section:{city}:{section}",
    )

    await send_stock_page(cb.message, filtered_stock, int(page_str))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:flat:(msk|spb):(fabrics|hardware):\d+$"))
async def on_stock_flat(cb: CallbackQuery):
    """Пагинация по плоскому списку остатков без иерархии."""

    _, _, city, section, page_str = cb.data.split(":")
    stock = await load_city_stock(city, section)
    stock.back_callback = f"stock_section:{city}:{section}"
    stock.kind_slug = None
    stock.type_slug = None
    await send_stock_page(cb.message, stock, int(page_str))
    await cb.answer()

