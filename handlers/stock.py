"""Обработчики выбора города и раздела для остатков."""

import re
from collections import defaultdict

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, FSInputFile
from pathlib import Path

from data.stock_interface import load_city_stock
from data.stock_models import StockItemCity
from services.pagination import slice_page
from structure.keyboards import (
    build_hardware_items_keyboard,
    build_hardware_kinds_keyboard,
    build_hardware_types_keyboard,
    build_stock_list_keyboard,
    build_spb_collections_keyboard,
    build_types_keyboard,
    kb_stock_kinds,
    kb_stock_sections,
)
from structure.markdown import MarkdownV2Escaper, edit_md_safe, escape_md, inline_code, send_md_safe

router = Router()

CITY_TITLES = {"msk": "Москва", "spb": "Санкт-Петербург"}
SECTION_TITLES = {"fabrics": "Ткани", "hardware": "Фурнитура"}

TYPE_PAGE_SIZE = 10
ITEM_PAGE_SIZE = 5
HARDWARE_ITEM_PAGE_SIZE = 5

_STOCK_SELECTIONS: dict[int, dict] = defaultdict(dict)

def _plain_title(section: str, city: str) -> str:
    """Возвращает заголовок раздела без Markdown-экранирования."""

    section_title = SECTION_TITLES.get(section, section)
    city_title = CITY_TITLES.get(city, city)
    return f"{section_title} • {city_title}"


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
        if stock.section == "hardware" and stock.city == "msk":
            markup = build_hardware_items_keyboard(
                city=stock.city,
                kind_slug=stock.kind_slug or "all",
                type_slug=stock.type_slug or "all",
                page=1,
                total_pages=1,
                back_callback=stock.back_callback,
            )
        else:
            markup = build_stock_list_keyboard(
                city=stock.city,
                section=stock.section,
                kind_slug=stock.kind_slug,
                type_slug=stock.type_slug,
                page=1,
                total_pages=1,
                back_callback=stock.back_callback,
                flat=not (stock.kind_slug or stock.type_slug),
            )
        empty_text = "Данные об остатках пока отсутствуют."
        if (
            message.from_user
            and message.from_user.is_bot
            and (message.text or message.caption or "") == empty_text
        ):
            current_keyboard = getattr(message.reply_markup, "inline_keyboard", None)
            if current_keyboard == getattr(markup, "inline_keyboard", None):
                return

        await send_md_safe(message, empty_text, reply_markup=markup)
        return

    page_size = (
        HARDWARE_ITEM_PAGE_SIZE
        if stock.section == "hardware" and stock.city == "msk"
        else ITEM_PAGE_SIZE
    )

    page_items, page, total_pages = slice_page(stock.items, page, page_size)
    start_index = (page - 1) * page_size + 1
    lines: list[str] = []

    for offset, item in enumerate(page_items, start=start_index):
        item_lines: list[str] = []

        if stock.city == "spb" and stock.section == "fabrics":
            item_lines.append(f"{offset}) {inline_code(item.name)}")
            qty_text = "" if item.quantity is None else str(item.quantity)
            free_text = "" if getattr(item, "free_quantity", None) is None else str(item.free_quantity)
            item_lines.append(f"Остаток: {qty_text} {item.unit or ''}".rstrip())
            item_lines.append(f"Свободный: {free_text} {item.unit or ''}".rstrip())
        elif stock.section == "hardware" and stock.city == "msk":
            item_lines.append(f"{offset}) {inline_code(item.name)}")
            if item.code:
                item_lines.append(f"Код: {inline_code(item.code)}")
            else:
                item_lines.append("Код: отсутствует")

            if item.article:
                item_lines.append(f"Артикул: {inline_code(item.article)}")
            else:
                item_lines.append("Артикул: отсутствует")

            qty_value = "" if item.quantity is None else item.quantity
            item_lines.append(f"Наличие: {qty_value}")
            unit_value = item.unit or ""
            item_lines.append(f"Ед.: {unit_value}")
        else:
            item_lines.append(f"{offset}) {inline_code(item.name)}")
            if item.quantity is not None and item.unit:
                item_lines.append(f"Наличие: {item.quantity} {item.unit}")

            max_roll = _parse_max_roll(item.extra_info)
            if max_roll is not None:
                item_lines.append(f"Макс.рулон: {max_roll}")

        lines.append("\n".join(item_lines))

    header: list[str] = [_plain_title(stock.section, stock.city)]
    if stock.kind:
        if stock.city == "spb" and stock.section == "fabrics":
            header.append(f"Коллекция: {stock.kind}")
        else:
            header.append(f"Вид: {stock.kind}")
    if stock.item_type:
        header.append(f"Тип: {stock.item_type}")
    header.append(f"Страница {page}/{total_pages}")

    text = "\n\n".join(["\n".join(header), *lines])
    if stock.section == "hardware" and stock.city == "msk":
        markup = build_hardware_items_keyboard(
            city=stock.city,
            kind_slug=stock.kind_slug or "all",
            type_slug=stock.type_slug or "all",
            page=page,
            total_pages=total_pages,
            back_callback=stock.back_callback,
        )
    else:
        markup = build_stock_list_keyboard(
            city=stock.city,
            section=stock.section,
            kind_slug=stock.kind_slug,
            type_slug=stock.type_slug,
            page=page,
            total_pages=total_pages,
            back_callback=stock.back_callback,
            flat=not (stock.kind_slug or stock.type_slug),
        )

    try:
        await edit_md_safe(message, text, reply_markup=markup)
    except Exception:
        await send_md_safe(message, text, reply_markup=markup)


async def _show_hardware_kinds(message: Message, user_id: int, city: str, page: int) -> None:
    """Показывает список видов номенклатуры фурнитуры с пагинацией."""

    section = "hardware"
    stock = await load_city_stock(city, section)
    selection = _STOCK_SELECTIONS[user_id]
    selection["city"] = city
    selection["section"] = section
    selection.pop("hw_type_map", None)

    kinds = sorted({item.kind for item in stock.items if item.kind})

    stock.back_callback = f"stock_section:{city}:{section}"
    stock.kind_slug = None
    stock.type_slug = None

    if not stock.items:
        await send_stock_page(message, stock, 1)
        return

    if not kinds:
        await send_stock_page(message, stock, 1)
        return

    used: set[str] = set()
    selection["hw_kind_map"] = {}
    selection["hw_kind_page"] = page
    kind_rows: list[tuple[str, str]] = []
    for kind in kinds:
        slug = _slugify(kind, used)
        selection["hw_kind_map"][slug] = kind
        kind_rows.append((kind, slug))

    page_rows, current_page, total_pages = slice_page(kind_rows, page, TYPE_PAGE_SIZE)

    text = (
        f"{escape_md(SECTION_TITLES.get(section, section))} • {escape_md(CITY_TITLES.get(city, city))}\n"
        f"Выберите вид номенклатуры.\nСтраница {current_page}/{total_pages}"
    )

    await send_md_safe(
        message,
        text,
        reply_markup=build_hardware_kinds_keyboard(
            city=city,
            kinds=page_rows,
            page=current_page,
            total_pages=total_pages,
        ),
    )


async def _show_spb_collections(
    message: Message, user_id: int, city: str, section: str, page: int
) -> None:
    """Показывает коллекции остатков СПБ с пагинацией."""

    stock = await load_city_stock(city, section)
    selection = _STOCK_SELECTIONS[user_id]
    selection["city"] = city
    selection["section"] = section
    selection.pop("type_map", None)

    collections = sorted(
        {item.kind for item in stock.items if item.kind}, key=lambda value: value.lower()
    )

    if not stock.items:
        stock.back_callback = f"stock_section:{city}:{section}"
        stock.kind_slug = None
        stock.type_slug = None
        await send_stock_page(message, stock, 1)
        return

    if not collections:
        stock.back_callback = f"stock_section:{city}:{section}"
        stock.kind_slug = None
        stock.type_slug = None
        await send_stock_page(message, stock, 1)
        return

    used: set[str] = set()
    selection["kind_map"] = {}
    selection["collection_page"] = page
    collection_rows: list[tuple[str, str]] = []
    for collection in collections:
        slug = _slugify(collection, used)
        selection["kind_map"][slug] = collection
        collection_rows.append((collection, slug))

    page_rows, current_page, total_pages = slice_page(
        collection_rows, page, TYPE_PAGE_SIZE
    )

    text = (
        f"{_plain_title(section, city)}\n"
        f"Выберите коллекцию.\nСтраница {current_page}/{total_pages}"
    )

    await send_md_safe(
        message,
        text,
        reply_markup=build_spb_collections_keyboard(
            city, section, page_rows, current_page, total_pages
        ),
    )


async def _show_kinds(message: Message, user_id: int, city: str, section: str) -> None:
    """Показывает список видов номенклатуры или плоский список, если видов нет."""

    if city == "spb" and section == "hardware":
        file_path = Path("data/stocks/spb/hardware/hardware_stock_spb.xlsx")
        if file_path.exists():
            await message.answer_document(
                FSInputFile(file_path),
                caption="Остатки фурнитуры СПБ",
                reply_markup=kb_stock_sections(city),
            )
            return

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
    if city == "spb" and section == "fabrics":
        await _show_spb_collections(cb.message, cb.from_user.id, city, section, 1)
    elif city == "msk" and section == "hardware":
        await _show_hardware_kinds(cb.message, cb.from_user.id, city, 1)
    else:
        await _show_kinds(cb.message, cb.from_user.id, city, section)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:msk:hardware:kinds:\d+$"))
async def on_stock_kinds_hardware(cb: CallbackQuery):
    """Показывает виды номенклатуры фурнитуры с пагинацией."""

    parts = cb.data.split(":")
    page_str = parts[-1]
    await _show_hardware_kinds(cb.message, cb.from_user.id, "msk", int(page_str))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:msk:hardware:types:.+"))
async def on_stock_types_hardware(cb: CallbackQuery):
    """Показывает типы номенклатуры для выбранного вида фурнитуры."""

    parts = cb.data.split(":")
    if len(parts) < 6:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    _, city, section, _, kind_slug, page_str = parts
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section
    selection["hw_kind_slug"] = kind_slug

    stock = await load_city_stock(city, section)
    kind_map = selection.get("hw_kind_map", {})
    selected_kind = kind_map.get(kind_slug)
    if not selected_kind:
        selected_kind = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)

    if not selected_kind:
        await send_md_safe(cb.message, "Данные об остатках пока отсутствуют.", reply_markup=kb_stock_sections(city))
        await cb.answer()
        return

    types = sorted({item.item_type for item in stock.items if item.kind == selected_kind and item.item_type})
    if not types:
        kinds = [(title, slug) for slug, title in kind_map.items()]
        page_rows, current_kind_page, total_kind_pages = slice_page(
            kinds, selection.get("hw_kind_page", 1), TYPE_PAGE_SIZE
        )
        await send_md_safe(
            cb.message,
            "Нет остатков в выбранной группе.",
            reply_markup=build_hardware_kinds_keyboard(
                city, page_rows, current_kind_page, total_kind_pages
            ),
        )
        await cb.answer()
        return

    used: set[str] = set()
    selection.setdefault("hw_type_map", {})
    selection["hw_type_map"][kind_slug] = {}
    selection["hw_type_page"] = int(page_str)
    type_rows: list[tuple[str, str]] = []
    for item_type in types:
        slug = _slugify(item_type, used)
        selection["hw_type_map"][kind_slug][slug] = item_type
        type_rows.append((item_type, slug))

    page_rows, current_page, total_pages = slice_page(type_rows, int(page_str), TYPE_PAGE_SIZE)

    text = (
        f"{_plain_title(section, city)}\n"
        f"Вид: {selected_kind}\n"
        f"Выберите тип номенклатуры.\nСтраница {current_page}/{total_pages}"
    )

    await send_md_safe(
        cb.message,
        text,
        reply_markup=build_hardware_types_keyboard(
            city=city,
            kind_slug=kind_slug,
            types=page_rows,
            page=current_page,
            total_pages=total_pages,
        ),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:msk:hardware:items:.+"))
async def on_stock_items_hardware(cb: CallbackQuery):
    """Отображает товары выбранного типа фурнитуры с пагинацией."""

    parts = cb.data.split(":")
    if len(parts) < 7:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    _, city, section, _, kind_slug, type_slug, page_str = parts
    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section

    stock = await load_city_stock(city, section)
    kind_title = selection.get("hw_kind_map", {}).get(kind_slug)
    if kind_title is None:
        kind_title = next((item.kind for item in stock.items if _match_slug(item.kind, kind_slug)), None)

    type_title = selection.get("hw_type_map", {}).get(kind_slug, {}).get(type_slug)
    if type_title is None:
        type_title = next((item.item_type for item in stock.items if _match_slug(item.item_type, type_slug)), None)

    filtered_items = [
        item
        for item in stock.items
        if (kind_title is None or item.kind == kind_title)
        and (type_title is None or item.item_type == type_title)
    ]

    back_callback = f"stock:msk:hardware:types:{kind_slug}:{selection.get('hw_type_page', 1)}"

    if not filtered_items:
        await send_md_safe(
            cb.message,
            "В выбранной категории пока нет остатков.",
            reply_markup=build_hardware_items_keyboard(
                city=city,
                kind_slug=kind_slug,
                type_slug=type_slug,
                page=1,
                total_pages=1,
                back_callback=back_callback,
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
        back_callback=back_callback,
    )

    await send_stock_page(cb.message, filtered_stock, int(page_str))
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


@router.callback_query(F.data.regexp(r"^stock:collections:(msk|spb):(fabrics|hardware):\d+$"))
async def on_stock_collections(cb: CallbackQuery):
    """Пагинация по коллекциям СПБ для раздела тканей."""

    parts = cb.data.split(":")

    # Ожидаем формат stock:collections:<city>:<section>:<page>
    if len(parts) != 5:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    # Первые два сегмента соответствуют префиксу "stock" и типу действия "collections"
    _, _, city, section, page_str = parts
    if city == "spb" and section == "fabrics":
        await _show_spb_collections(cb.message, cb.from_user.id, city, section, int(page_str))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^scol:"))
async def on_stock_collections_with_colon(cb: CallbackQuery) -> None:
    """Обработка колбэков коллекций с именами, содержащими двоеточия."""

    parts = cb.data.split(":")

    # Ожидаем минимум: scol:city:section:collection
    if len(parts) < 4:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    city = parts[1]
    section = parts[2]

    # collection может содержать двоеточия, поэтому собираем всё между section и page/open
    # ищем позицию маркеров page или open
    try:
        idx = next(i for i, p in enumerate(parts) if p in ("page", "open"))
    except StopIteration:
        await cb.answer("Некорректный формат callback data", show_alert=True)
        return

    collection = ":".join(parts[3:idx])
    action = parts[idx]

    page = 1
    if action == "page":
        try:
            page = int(parts[idx + 1])
        except (ValueError, IndexError):
            page = 1

    selection = _STOCK_SELECTIONS[cb.from_user.id]
    selection["city"] = city
    selection["section"] = section
    selection.setdefault("kind_map", {})
    selection.setdefault("collection_page", page)

    used = set(selection["kind_map"].keys())
    slug = _slugify(collection, used)
    selection["kind_map"][slug] = collection

    if action == "page":
        await _show_spb_collections(cb.message, cb.from_user.id, city, section, page)
        await cb.answer()
        return

    stock = await load_city_stock(city, section)
    filtered_items = [item for item in stock.items if item.collection == collection]

    back_callback = f"stock:collections:{city}:{section}:{selection.get('collection_page', 1)}"

    if not filtered_items:
        markup = build_stock_list_keyboard(
            city=city,
            section=section,
            kind_slug=slug,
            type_slug=None,
            page=1,
            total_pages=1,
            back_callback=back_callback,
            flat=True,
        )
        await send_md_safe(cb.message, "В выбранной категории пока нет остатков.", reply_markup=markup)
        await cb.answer()
        return

    filtered_stock = StockItemCity(
        city=city,
        section=section,
        items=filtered_items,
        kind=collection,
        item_type=None,
        kind_slug=slug,
        type_slug="all",
        back_callback=back_callback,
    )

    await send_stock_page(cb.message, filtered_stock, page)
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
        back_callback = (
            f"stock:collections:{city}:{section}:{selection.get('collection_page', 1)}"
            if city == "spb" and section == "fabrics"
            else (
                f"stock:types:{city}:{section}:{kind_slug}:1"
                if kind_slug != "all"
                else f"stock_section:{city}:{section}"
            )
        )

        markup = build_stock_list_keyboard(
            city=city,
            section=section,
            kind_slug=None if kind_slug == "all" else kind_slug,
            type_slug=None if type_slug == "all" else type_slug,
            page=1,
            total_pages=1,
            back_callback=back_callback,
            flat=kind_slug == "all" and type_slug == "all",
        )
        await send_md_safe(cb.message, "В выбранной категории пока нет остатков.", reply_markup=markup)
        await cb.answer()
        return

    back_callback = (
        f"stock:collections:{city}:{section}:{_STOCK_SELECTIONS[cb.from_user.id].get('collection_page', 1)}"
        if city == "spb" and section == "fabrics"
        else (
            f"stock:types:{city}:{section}:{kind_slug}:1"
            if kind_slug != "all"
            else f"stock_section:{city}:{section}"
        )
    )

    filtered_stock = StockItemCity(
        city=city,
        section=section,
        items=filtered_items,
        kind=kind_title,
        item_type=type_title,
        kind_slug=None if kind_slug == "all" else kind_slug,
        type_slug=None if type_slug == "all" else type_slug,
        back_callback=back_callback,
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
