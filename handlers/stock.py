"""Обработчики выбора города и раздела для остатков."""
from collections import defaultdict

from aiogram import Router, F
from aiogram.types import CallbackQuery

from data.stock_interface import load_city_stock
from structure.keyboards import kb_stock_sections
from structure.markdown import send_md_safe

router = Router()

# Выбор города и раздела наличия по пользователям
_STOCK_SELECTIONS: dict[int, dict[str, str]] = defaultdict(dict)


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
    """Фиксирует выбор раздела остатков и выводит заглушку с подсчётом позиций."""

    _, city, section = cb.data.split(":")
    user_selection = _STOCK_SELECTIONS[cb.from_user.id]
    user_selection["city"] = city
    user_selection["section"] = section
    city_label = "Москва" if city == "msk" else "Санкт-Петербург"
    section_label = "Ткани" if section == "fabrics" else "Фурнитура"
    await send_md_safe(
        cb.message,
        (
            f"Вы выбрали: {city_label}, раздел: {section_label}.\n"
            "Логика загрузки остатков будет добавлена позже."
        ),
    )
    items = await load_city_stock(city, section)
    await cb.message.answer(f"Загружено позиций: {len(items)}")
    await cb.answer()
