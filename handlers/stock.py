"""Обработчики выбора города и раздела для остатков."""

from collections import defaultdict

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import PAGE_SIZE
from data.stock_interface import load_city_stock
from data.stock_models import StockItemCity
from services.pagination import slice_page
from structure.keyboards import kb_stock_sections, stock_pagination_keyboard
from structure.markdown import edit_md_safe, send_md_safe

router = Router()

CITY_TITLES = {"msk": "Москва", "spb": "Санкт-Петербург"}
SECTION_TITLES = {"fabrics": "Ткани", "hardware": "Фурнитура"}

# Выбор города и раздела наличия по пользователям
_STOCK_SELECTIONS: dict[int, dict[str, str]] = defaultdict(dict)


async def send_stock_page(message: Message, stock: StockItemCity, page: int) -> None:
    """Отображает страницу остатков с пагинацией."""

    if not stock.items:
        await send_md_safe(
            message,
            "Данные об остатках пока отсутствуют.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
                ]
            ),
        )
        return

    page_items, page, total_pages = slice_page(stock.items, page, PAGE_SIZE)
    start_index = (page - 1) * PAGE_SIZE + 1
    lines: list[str] = []

    for offset, item in enumerate(page_items, start=start_index):
        qty_text = f"{item.quantity:g}"
        unit_text = f" {item.unit}" if item.unit else ""
        lines.append(f"{offset}) {item.name} — {qty_text}{unit_text}")

    city_label = CITY_TITLES.get(stock.city, stock.city)
    section_label = SECTION_TITLES.get(stock.section, stock.section)

    text_lines = [
        f"{section_label} · {city_label}",
        f"Страница {page}/{total_pages}",
        "",
        *lines,
    ]
    text = "\n".join(text_lines)
    markup = stock_pagination_keyboard(stock.city, stock.section, page, total_pages)

    try:
        await edit_md_safe(message, text, reply_markup=markup)
    except Exception:
        await send_md_safe(message, text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^stock_city:(msk|spb)$"))
async def on_stock_city_selected(cb: CallbackQuery):
    """Сохраняет выбранный город и предлагает выбрать раздел остатков."""

    city = cb.data.split(":")[-1]
    _STOCK_SELECTIONS[cb.from_user.id]["city"] = city
    await send_md_safe(
        cb.message,
        "Выберите раздел остатков:",
        reply_markup=kb_stock_sections(city),
    )
    await cb.answer("Город выбран")


@router.callback_query(F.data.regexp(r"^stock_section:(msk|spb):(fabrics|hardware)$"))
async def on_stock_select_section(cb: CallbackQuery):
    """Фиксирует выбор раздела остатков и выводит результат загрузки."""

    _, city, section = cb.data.split(":")
    user_selection = _STOCK_SELECTIONS[cb.from_user.id]
    user_selection["city"] = city
    user_selection["section"] = section
    stock = await load_city_stock(city, section)
    await send_stock_page(cb.message, stock, 1)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^stock:(msk|spb):(fabrics|hardware):\d+$"))
async def on_stock_page(cb: CallbackQuery):
    """Обрабатывает пагинацию по списку остатков."""

    _, city, section, page = cb.data.split(":")
    stock = await load_city_stock(city, section)
    await send_stock_page(cb.message, stock, int(page))
    await cb.answer()
