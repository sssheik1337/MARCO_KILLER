import asyncio
import logging
import os
import sqlite3
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    ContentType,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from middlewares.admin_filter import AdminOnly
from data.db_utils import (
    add_stock_items,
    find_catalog_product_by_article,
    get_setting,
    set_setting,
)
from data import importer
from data.importer import ImportErrorFriendly, ParsedResult
import aiosqlite
from config import DB_PATH, LOGIN_ADMIN, PASSWORD_ADMIN
from formatter import escape_md, send_md_safe
from data.admins import is_superadmin
from structure.markdown import edit_md_safe, message_to_markdown, escape_user, send_md_safe_to_chat
from structure.keyboards import usd_keyboard, import_result_keyboard, cancel_keyboard
from services import profiles
from structure.ready_catalogs import ready_catalogs_manage_keyboard, ready_catalog_item_keyboard
from structure.states import AnnouncementState, PromoBroadcastState, ReadyCatalogState
from data.ready_catalogs import (
    add_ready_catalog,
    delete_ready_catalog,
    get_ready_catalog_by_id,
    get_ready_catalogs,
    update_ready_catalog_file,
    update_ready_catalog_title,
)
from services.exchange import current_range, refresh_range
from services.notifications import broadcast, build_product_card, send_bulk_message
from services.product_render import build_product_caption

router = Router()
router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())


_EDITABLE_SETTINGS = {
    "contacts": "Контакты",
    "address": "Адрес/маршрут",
    "worktime": "Режим работы",
    "requisites": "Реквизиты",
}


_IMPORT_TARGETS = {
    "fabrics_catalog": {
        "section": "fabrics",
        "city": "all",
        "prompt": "Пришлите XLSX или CSV с каталогом тканей.",
        "title": "каталог тканей",
        "parser": importer.parse_fabrics_catalog,
    },
    "hardware_catalog": {
        "section": "hardware",
        "city": "all",
        "prompt": "Пришлите XLSX или CSV с каталогом фурнитуры.",
        "title": "каталог фурнитуры",
        "parser": importer.parse_hardware_catalog,
    },
    "stock_fabrics_msk": {
        "section": "fabrics",
        "city": "msk",
        "prompt": "Пришлите XLSX или CSV с остатками тканей для Москвы.",
        "title": "остатки тканей (Москва)",
        "parser": importer.parse_fabrics_stock_msk,
    },
    "stock_fabrics_spb": {
        "section": "fabrics",
        "city": "spb",
        "prompt": "Пришлите XLSX или CSV с остатками тканей для Санкт-Петербурга.",
        "title": "остатки тканей (СПБ)",
        "parser": importer.parse_fabrics_stock_spb,
    },
    "stock_hardware_msk": {
        "section": "hardware",
        "city": "msk",
        "prompt": "Пришлите XLSX или CSV с остатками фурнитуры для Москвы.",
        "title": "остатки фурнитуры (Москва)",
        "parser": importer.parse_hardware_stock_msk,
    },
    "stock_hardware_spb": {
        "section": "hardware",
        "city": "spb",
        "prompt": "Пришлите XLSX или CSV с остатками фурнитуры для Санкт-Петербурга.",
        "title": "остатки фурнитуры (СПБ)",
        "parser": importer.parse_hardware_stock_spb,
    },
}

# Человекочитаемые названия для сообщений об импорте
HUMAN_NAME = {key: cfg["title"] for key, cfg in _IMPORT_TARGETS.items()}


_BROADCAST_TYPES = {
    "promo": {"label": "🔥Акция", "title": "акцию"},
    "new": {"label": "⭐Новинка", "title": "новинку"},
    "sale": {"label": "💥Распродажа", "title": "распродажу"},
}


@router.message(Command("notify"))
async def notify_admin(msg: Message, command: CommandObject | None):
    """Команда администратора для рассылки карточки по артикулу."""

    article = (command.args or "").strip() if command else ""
    if not article:
        await send_md_safe(msg, "Укажите артикул после команды /notify")
        return

    found = await find_catalog_product_by_article(article)
    if not found:
        await send_md_safe(msg, "Артикул не найден")
        return

    source, product = found
    card_text = build_product_card(source, product)

    sent, failed = await broadcast(msg.bot, card_text)
    await send_md_safe(
        msg,
        "\n".join(
            [
                "Уведомление отправлено.",
                card_text,
                f"Итог: доставлено {sent}, ошибок {failed}.",
            ]
        ),
    )


def admin_kb(show_credentials: bool = False):
    rows = [
        [InlineKeyboardButton(text="📇 Править контакты", callback_data="admin:edit:contacts"),
         InlineKeyboardButton(text="🗺️ Адрес/маршрут", callback_data="admin:edit:address")],
        [InlineKeyboardButton(text="🕘 Режим работы", callback_data="admin:edit:worktime"),
         InlineKeyboardButton(text="📄 Реквизиты", callback_data="admin:edit:requisites")],
        [InlineKeyboardButton(text="📤 Каталог тканей", callback_data="admin:import:fabrics_catalog"),
         InlineKeyboardButton(text="📤 Каталог фурнитуры", callback_data="admin:import:hardware_catalog")],
        [InlineKeyboardButton(text="📦 Остатки тканей Москва", callback_data="admin:import:stock_fabrics_msk"),
         InlineKeyboardButton(text="📦 Остатки тканей СПБ", callback_data="admin:import:stock_fabrics_spb")],
        [InlineKeyboardButton(text="📦 Остатки фурнитуры Москва", callback_data="admin:import:stock_hardware_msk"),
         InlineKeyboardButton(text="📦 Остатки фурнитуры СПБ", callback_data="admin:import:stock_hardware_spb")],
        [InlineKeyboardButton(text="➕ Добавить каталог готовых изделий", callback_data="admin:ready:add")],
        [InlineKeyboardButton(text="✏️ Управление каталогами готовых изделий", callback_data="admin:ready:manage")],
        [InlineKeyboardButton(text="📣 Промо по товару", callback_data="admin:promo:start")],
        [InlineKeyboardButton(text="📢 Объявление (без товара)", callback_data="admin:announce:start")],
        [InlineKeyboardButton(text="💵 Курс USD: авто/ручной", callback_data="admin:usd")],
    ]
    if show_credentials:
        rows.insert(0, [InlineKeyboardButton(text="🔐 Данные для входа администратора", callback_data="admin:creds")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_type_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа акции для промо-рассылки."""

    buttons = [
        InlineKeyboardButton(text=cfg["label"], callback_data=f"admin:promo:type:{key}")
        for key, cfg in _BROADCAST_TYPES.items()
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def announce_type_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа акции для объявления без товара."""

    buttons = [
        InlineKeyboardButton(text=cfg["label"], callback_data=f"admin:announce:type:{key}")
        for key, cfg in _BROADCAST_TYPES.items()
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def edit_prompt_kb(target: str) -> InlineKeyboardMarkup:
    """Формирует клавиатуру с кнопкой предпросмотра текущего текста."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Предпросмотр", callback_data=f"admin:preview:{target}")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def import_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для отмены ожидаемой загрузки файла."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:import:cancel")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def promo_city_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора города для промо-сценария остатков."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Москва", callback_data="admin:promo:city:msk"),
                InlineKeyboardButton(text="Санкт-Петербург", callback_data="admin:promo:city:spb"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def promo_section_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора раздела для промо-сценария."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧵 Ткани", callback_data="admin:promo:section:fabrics"),
                InlineKeyboardButton(text="🔩 Фурнитура", callback_data="admin:promo:section:hardware"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def promo_preview_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения отправки промо-рассылки."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить всем", callback_data="admin:promo:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin:promo:cancel"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def promo_source_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора источника товара для промо (каталог или наличие)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 Каталог", callback_data="admin:promo:source:catalog"),
                InlineKeyboardButton(text="📦 Наличие", callback_data="admin:promo:source:stock"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def _build_promo_preview(
    product: dict,
    promo_type: str,
    extra_text: str | None,
    rng: str,
    usd: float | None,
    *,
    source: str,
) -> str:
    """Собирает текст предпросмотра промо-рассылки."""

    label = _BROADCAST_TYPES[promo_type]["label"]
    header = f"*{escape_user(label)}*"

    include_city = source == "stock"
    caption = build_product_caption(product, rng, usd, include_city=include_city)

    blocks = [header, caption]
    if extra_text:
        blocks.append(escape_user(extra_text))
    return "\n\n".join(blocks)


def _build_announcement_preview(promo_type: str, text: str) -> str:
    """Собирает предпросмотр объявления без привязки к товару."""

    label = _BROADCAST_TYPES[promo_type]["label"]
    header = f"*{escape_user(label)}*"
    if text:
        return "\n\n".join([header, text])
    return header


@router.callback_query(F.data == "admin:open")
async def open_admin(cb: CallbackQuery):
    show_creds = is_superadmin(cb.from_user.id) if cb.from_user else False
    await send_md_safe(
        cb.message,
        "Админ-панель:",
        reply_markup=admin_kb(show_creds),
    )
    await cb.answer()


@router.callback_query(F.data == "admin:creds")
async def show_admin_creds(cb: CallbackQuery):
    """Показывает логин/пароль администратора только суперадминам."""

    if not (cb.from_user and is_superadmin(cb.from_user.id)):
        await cb.answer("Недостаточно прав", show_alert=True)
        return

    text = (
        "Логин администратора:\n"
        f"{LOGIN_ADMIN}\n\n"
        "Пароль администратора:\n"
        f"{PASSWORD_ADMIN}\n\n"
        "⚠️ Передавайте эти данные только доверенным лицам.\n\n"
        "Инструкция:\n"
        "1) Введите /getadmin\n"
        "2) Введите логин\n"
        "3) Введите пароль"
    )
    await send_md_safe(cb.message, text, reply_markup=admin_kb(show_credentials=True))
    await cb.answer()


@router.callback_query(F.data == "admin:ready:add")
async def ready_catalog_add(cb: CallbackQuery, state: FSMContext):
    """Запрашивает название нового каталога готовых изделий."""

    await state.clear()
    await state.set_state(ReadyCatalogState.waiting_title)
    await send_md_safe(cb.message, "Введите название каталога:", reply_markup=cancel_keyboard())
    await cb.answer()


@router.message(ReadyCatalogState.waiting_title)
async def ready_catalog_title(msg: Message, state: FSMContext):
    title = (msg.text or "").strip()
    if not title:
        await send_md_safe(msg, "Название не может быть пустым. Введите название каталога:")
        return

    await state.update_data(new_catalog_title=title)
    await state.set_state(ReadyCatalogState.waiting_file)
    await send_md_safe(
        msg,
        "Пришлите файл каталога (XLSX):",
        reply_markup=cancel_keyboard(),
    )


@router.message(ReadyCatalogState.waiting_file, F.content_type == ContentType.DOCUMENT)
async def ready_catalog_file(msg: Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("new_catalog_title", "Каталог")
    file_id = msg.document.file_id
    await add_ready_catalog(title, file_id)
    await state.clear()
    await send_md_safe(msg, f"Каталог «{escape_user(title)}» добавлен ✅", reply_markup=admin_kb())


@router.callback_query(F.data == "admin:ready:manage")
async def ready_catalog_manage(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    catalogs = await get_ready_catalogs()
    if not catalogs:
        await send_md_safe(cb.message, "Каталоги готовых изделий пока не добавлены.", reply_markup=admin_kb())
        await cb.answer()
        return

    await send_md_safe(
        cb.message,
        "Выберите каталог для управления:",
        reply_markup=ready_catalogs_manage_keyboard(catalogs),
    )
    await cb.answer()


@router.callback_query(F.data == "admin:promo:start")
async def promo_start(cb: CallbackQuery, state: FSMContext):
    """Запускает сценарий промо-рассылки по выбранному товару."""

    await state.clear()
    await state.set_state(PromoBroadcastState.waiting_source)
    await send_md_safe(
        cb.message,
        "Выберите источник товара для промо:",
        reply_markup=promo_source_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:promo:source:"))
async def promo_choose_source(cb: CallbackQuery, state: FSMContext):
    """Фиксирует источник (каталог или наличие) и предлагает следующий шаг."""

    source = cb.data.split(":")[-1]
    if source not in {"catalog", "stock"}:
        await cb.answer("Источник недоступен", show_alert=True)
        return

    await state.update_data(promo_source=source, promo_city=None)

    if source == "catalog":
        await state.set_state(PromoBroadcastState.waiting_section)
        await send_md_safe(
            cb.message,
            "Выберите тип из каталога:",
            reply_markup=promo_section_keyboard(),
        )
    else:
        await state.set_state(PromoBroadcastState.waiting_city)
        await send_md_safe(
            cb.message,
            "Выберите город для промо из наличия:",
            reply_markup=promo_city_keyboard(),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:promo:city:"))
async def promo_choose_city(cb: CallbackQuery, state: FSMContext):
    """Фиксирует город промо-рассылки для остатков и предлагает выбрать раздел."""

    city = cb.data.split(":")[-1]
    if city not in {"msk", "spb"}:
        await cb.answer("Город недоступен", show_alert=True)
        return

    data = await state.get_data()
    if data.get("promo_source") != "stock":
        await cb.answer("Сначала выберите источник «Наличие»", show_alert=True)
        return

    await state.update_data(promo_city=city)
    profiles.set_city(cb.from_user.id, city)
    await state.set_state(PromoBroadcastState.waiting_section)
    await send_md_safe(
        cb.message,
        "Выберите тип из наличия: ткани или фурнитура.",
        reply_markup=promo_section_keyboard(),
    )
    await cb.answer("Город установлен")


@router.callback_query(F.data.startswith("admin:promo:section:"))
async def promo_choose_section(cb: CallbackQuery, state: FSMContext):
    """Фиксирует раздел и запускает штатную навигацию каталога."""

    section = cb.data.split(":")[-1]
    if section not in {"fabrics", "hardware"}:
        await cb.answer("Раздел недоступен", show_alert=True)
        return

    data = await state.get_data()
    source = data.get("promo_source")
    if source not in {"catalog", "stock"}:
        await cb.answer("Сначала выберите источник", show_alert=True)
        return

    if source == "stock" and not data.get("promo_city"):
        await cb.answer("Сначала выберите город", show_alert=True)
        return

    await state.update_data(promo_section=section)
    await state.set_state(PromoBroadcastState.waiting_product)

    if source == "catalog":
        await send_md_safe(
            cb.message,
            "Выберите товар из каталога (город не требуется):",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть категории", callback_data=f"csec:open:{section}")],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
                ]
            ),
        )
    else:
        await send_md_safe(
            cb.message,
            "Выберите товар из наличия:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть категории", callback_data=f"ssec:open:{section}")],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
                ]
            ),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:ready:item:"))
async def ready_catalog_item(cb: CallbackQuery, state: FSMContext):
    catalog_id = cb.data.split(":")[-1]
    catalog = await get_ready_catalog_by_id(int(catalog_id))
    if not catalog:
        await send_md_safe(cb.message, "Каталог не найден.", reply_markup=admin_kb())
        await cb.answer()
        return

    await state.update_data(current_catalog_id=catalog["id"], current_catalog_title=catalog["title"])
    await send_md_safe(
        cb.message,
        f"Каталог: {escape_user(catalog['title'])}",
        reply_markup=ready_catalog_item_keyboard(catalog["id"]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:ready:rename:"))
async def ready_catalog_rename(cb: CallbackQuery, state: FSMContext):
    catalog_id = int(cb.data.split(":")[-1])
    catalog = await get_ready_catalog_by_id(catalog_id)
    if not catalog:
        await send_md_safe(cb.message, "Каталог не найден.", reply_markup=admin_kb())
        await cb.answer()
        return

    await state.update_data(current_catalog_id=catalog_id)
    await state.set_state(ReadyCatalogState.rename_title)
    await send_md_safe(cb.message, "Введите новое название каталога:", reply_markup=cancel_keyboard())
    await cb.answer()


@router.message(ReadyCatalogState.rename_title)
async def ready_catalog_rename_title(msg: Message, state: FSMContext):
    new_title = (msg.text or "").strip()
    if not new_title:
        await send_md_safe(msg, "Название не может быть пустым. Введите новое название:")
        return

    data = await state.get_data()
    catalog_id = data.get("current_catalog_id")
    if not catalog_id:
        await state.clear()
        await send_md_safe(msg, "Каталог не найден.", reply_markup=admin_kb())
        return

    await update_ready_catalog_title(int(catalog_id), new_title)
    await state.clear()
    await send_md_safe(msg, f"Каталог переименован в «{escape_user(new_title)}».", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("admin:ready:replace:"))
async def ready_catalog_replace(cb: CallbackQuery, state: FSMContext):
    catalog_id = int(cb.data.split(":")[-1])
    catalog = await get_ready_catalog_by_id(catalog_id)
    if not catalog:
        await send_md_safe(cb.message, "Каталог не найден.", reply_markup=admin_kb())
        await cb.answer()
        return

    await state.update_data(current_catalog_id=catalog_id)
    await state.set_state(ReadyCatalogState.replace_file)
    await send_md_safe(cb.message, "Пришлите новый файл каталога (XLSX):", reply_markup=cancel_keyboard())
    await cb.answer()


@router.message(ReadyCatalogState.replace_file, F.content_type == ContentType.DOCUMENT)
async def ready_catalog_replace_file(msg: Message, state: FSMContext):
    data = await state.get_data()
    catalog_id = data.get("current_catalog_id")
    if not catalog_id:
        await state.clear()
        await send_md_safe(msg, "Каталог не найден.", reply_markup=admin_kb())
        return

    await update_ready_catalog_file(int(catalog_id), msg.document.file_id)
    await state.clear()
    await send_md_safe(msg, "Файл каталога обновлён.", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("admin:ready:delete:"))
async def ready_catalog_delete(cb: CallbackQuery, state: FSMContext):
    catalog_id = int(cb.data.split(":")[-1])
    await delete_ready_catalog(catalog_id)
    await state.clear()
    await send_md_safe(cb.message, "Каталог удалён.", reply_markup=admin_kb())
    await cb.answer()


def _format_usd_message(rng: str, usd: float | None) -> str:
    """Готовит текст с текущим курсом и коридором."""

    corridor = rng.replace("_", "–")
    if usd is None:
        rate_line = "Курс ЦБ: н/д"
    else:
        rate_line = f"Курс ЦБ: {usd:.2f} ₽"
    return "\n".join([
        rate_line,
        f"Активный коридор: {corridor}",
        "Режим: Авто",
    ])


@router.callback_query(F.data == "admin:usd")
async def show_usd(cb: CallbackQuery):
    rng, usd = await current_range()
    text = _format_usd_message(rng, usd)
    await send_md_safe(
        cb.message,
        text,
        reply_markup=usd_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data == "admin:usd:refresh")
async def refresh_usd(cb: CallbackQuery):
    rng, usd = await refresh_range()
    text = _format_usd_message(rng, usd)
    keyboard = usd_keyboard()
    current_text = cb.message.text or ""
    current_markup_dump = (
        cb.message.reply_markup.model_dump() if cb.message.reply_markup else None
    )
    new_markup_dump = keyboard.model_dump()

    if current_text == text and current_markup_dump == new_markup_dump:
        await cb.answer("Курс актуален")
        return

    try:
        await edit_md_safe(
            cb.message,
            text,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            await cb.answer("Курс актуален")
            return
        raise


@router.callback_query(F.data.startswith("admin:promo:type:"))
async def promo_choose_type(cb: CallbackQuery, state: FSMContext):
    """Фиксирует тип акции для промо-рассылки."""

    current_state = await state.get_state()
    if current_state != PromoBroadcastState.waiting_type.state:
        await cb.answer("Сначала выберите товар", show_alert=True)
        return

    promo_type = cb.data.split(":")[-1]
    if promo_type not in _BROADCAST_TYPES:
        await cb.answer("Неизвестный тип", show_alert=True)
        return

    await state.update_data(promo_type=promo_type)
    await state.set_state(PromoBroadcastState.waiting_extra)
    await send_md_safe(
        cb.message,
        "Введите дополнительный текст акции (можно оставить пустым):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="admin:promo:extra_skip")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
            ]
        ),
    )
    await cb.answer()


@router.message(PromoBroadcastState.waiting_extra)
async def promo_extra_text(msg: Message, state: FSMContext):
    """Сохраняет дополнительный текст и запрашивает URL кнопки."""

    extra_text = (msg.text or msg.caption or "").strip()
    await state.update_data(promo_extra=extra_text)
    await state.set_state(PromoBroadcastState.waiting_url)
    await send_md_safe(msg, "Пришлите URL для кнопки (или «-» если кнопка не нужна):")


@router.callback_query(F.data == "admin:promo:extra_skip")
async def promo_extra_skip(cb: CallbackQuery, state: FSMContext):
    """Пропускает ввод дополнительного текста и переходит к шагу URL."""

    await state.update_data(promo_extra="")
    await state.set_state(PromoBroadcastState.waiting_url)
    await send_md_safe(cb.message, "Пришлите URL для кнопки (или «-» если кнопка не нужна):")
    await cb.answer("Текст пропущен")


@router.message(PromoBroadcastState.waiting_url)
async def promo_url(msg: Message, state: FSMContext):
    """Сохраняет URL кнопки и показывает предпросмотр."""

    url_text = (msg.text or msg.caption or "").strip()
    url_value = None if not url_text or url_text == "-" else url_text

    data = await state.get_data()
    product = data.get("promo_product")
    promo_type = data.get("promo_type")
    city = data.get("promo_city")
    source = data.get("promo_source", "catalog")
    if not product or not promo_type or (source == "stock" and not city):
        await state.clear()
        await send_md_safe(msg, "Не удалось собрать данные для рассылки. Начните заново.", reply_markup=admin_kb())
        return

    rng, usd = await current_range()
    preview_text = _build_promo_preview(
        product,
        promo_type,
        data.get("promo_extra"),
        rng,
        usd,
        source=data.get("promo_source", "catalog"),
    )

    await state.update_data(promo_url=url_value, promo_preview=preview_text)
    await state.set_state(PromoBroadcastState.waiting_confirm)

    button_markup = None
    if url_value:
        button_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подробнее", url=url_value)],
            ]
        )

    await send_md_safe(
        msg,
        "Предпросмотр промо:\n\n" + preview_text,
        reply_markup=button_markup or promo_preview_keyboard(),
    )
    if button_markup:
        await send_md_safe(msg, "Подтвердите отправку.", reply_markup=promo_preview_keyboard())


async def _run_promo_broadcast(bot, text: str, promo_url: str | None, chat_id: int):
    """Фоновая отправка промо-рассылки с уведомлением администратора."""

    reply_markup = None
    if promo_url:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Подробнее", url=promo_url)]]
        )

    delivered, blocked, failed = await send_bulk_message(
        bot,
        text,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup,
    )
    summary_lines = [
        "Промо-рассылка завершена:",
        f"✅ Доставлено: {delivered}",
        f"🚫 Заблокировано: {blocked}",
        f"⚠️ Ошибок: {failed}",
    ]
    await send_md_safe_to_chat(bot, chat_id, "\n".join(summary_lines))


@router.callback_query(F.data == "admin:promo:confirm")
async def promo_confirm(cb: CallbackQuery, state: FSMContext):
    """Запускает массовую промо-рассылку."""

    current_state = await state.get_state()
    if current_state != PromoBroadcastState.waiting_confirm.state:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    data = await state.get_data()
    preview_text = data.get("promo_preview")
    promo_url = data.get("promo_url")
    product = data.get("promo_product")
    if not preview_text or not product:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    await send_md_safe(cb.message, "Рассылка запущена, сообщим об итогах.")
    await state.clear()

    asyncio.create_task(_run_promo_broadcast(cb.bot, preview_text, promo_url, cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "admin:promo:cancel")
async def promo_cancel(cb: CallbackQuery, state: FSMContext):
    """Отменяет промо-рассылку и очищает состояние."""

    await state.clear()
    await send_md_safe(cb.message, "Рассылка отменена.", reply_markup=admin_kb())
    await cb.answer()


@router.callback_query(F.data == "admin:announce:start")
async def announce_start(cb: CallbackQuery, state: FSMContext):
    """Запускает сценарий объявления без товара."""

    await state.clear()
    await state.set_state(AnnouncementState.waiting_type)
    await send_md_safe(
        cb.message,
        "Выберите тип объявления:",
        reply_markup=announce_type_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:announce:type:"))
async def announce_choose_type(cb: CallbackQuery, state: FSMContext):
    """Фиксирует тип объявления и запрашивает текст."""

    current_state = await state.get_state()
    if current_state != AnnouncementState.waiting_type.state:
        await cb.answer("Сначала начните сценарий объявления", show_alert=True)
        return

    announce_type = cb.data.split(":")[-1]
    if announce_type not in _BROADCAST_TYPES:
        await cb.answer("Неизвестный тип", show_alert=True)
        return

    await state.update_data(announce_type=announce_type)
    await state.set_state(AnnouncementState.waiting_text)
    await send_md_safe(cb.message, "Пришлите текст объявления. Можно использовать форматирование.")
    await cb.answer()


@router.message(AnnouncementState.waiting_text)
async def announce_text(msg: Message, state: FSMContext):
    """Сохраняет текст объявления и запрашивает URL кнопки."""

    announce_text = message_to_markdown(msg)
    await state.update_data(announce_text=announce_text)
    await state.set_state(AnnouncementState.waiting_url)
    await send_md_safe(msg, "Пришлите URL для кнопки (или «-» если кнопка не нужна):")


@router.message(AnnouncementState.waiting_url)
async def announce_url(msg: Message, state: FSMContext):
    """Готовит предпросмотр объявления и запрашивает подтверждение."""

    url_text = (msg.text or msg.caption or "").strip()
    url_value = None if not url_text or url_text == "-" else url_text

    data = await state.get_data()
    announce_type = data.get("announce_type")
    announce_text = data.get("announce_text", "")
    if not announce_type:
        await state.clear()
        await send_md_safe(msg, "Сценарий сброшен. Начните заново.", reply_markup=admin_kb())
        return

    preview_text = _build_announcement_preview(announce_type, announce_text)

    await state.update_data(
        announce_url=url_value,
        announce_preview=preview_text,
    )
    await state.set_state(AnnouncementState.waiting_confirm)

    button_markup = None
    if url_value:
        button_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Подробнее", url=url_value)]]
        )
        await send_md_safe(
            msg,
            preview_text,
            reply_markup=button_markup,
        )
        await send_md_safe(
            msg,
            "Подтвердите отправку.",
            reply_markup=promo_preview_keyboard(),
        )
    else:
        await send_md_safe(
            msg,
            preview_text,
            reply_markup=promo_preview_keyboard(),
        )


async def _run_announce_broadcast(bot, text: str, url: str | None, chat_id: int):
    """Фоновая отправка объявления без товара."""

    reply_markup = None
    if url:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Подробнее", url=url)]]
        )

    delivered, blocked, failed = await send_bulk_message(
        bot,
        text,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup,
    )
    summary_lines = [
        "Объявление отправлено:",
        f"✅ Доставлено: {delivered}",
        f"🚫 Заблокировано: {blocked}",
        f"⚠️ Ошибок: {failed}",
    ]
    await send_md_safe_to_chat(bot, chat_id, "\n".join(summary_lines))


@router.callback_query(F.data == "admin:announce:confirm")
async def announce_confirm(cb: CallbackQuery, state: FSMContext):
    """Запускает массовую рассылку объявления."""

    current_state = await state.get_state()
    if current_state != AnnouncementState.waiting_confirm.state:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    data = await state.get_data()
    preview_text = data.get("announce_preview")
    announce_url = data.get("announce_url")
    announce_text = data.get("announce_text", "")
    if not preview_text:
        if not announce_text:
            await cb.answer("Нечего отправлять", show_alert=True)
            return
        preview_text = _build_announcement_preview(data.get("announce_type", ""), announce_text)
    if not announce_text:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    await send_md_safe(cb.message, "Рассылка запущена, сообщим об итогах.")
    await state.clear()

    asyncio.create_task(_run_announce_broadcast(cb.bot, preview_text, announce_url, cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "admin:announce:cancel")
async def announce_cancel(cb: CallbackQuery, state: FSMContext):
    """Отменяет сценарий объявления и очищает состояние."""

    await state.clear()
    await send_md_safe(cb.message, "Рассылка отменена.", reply_markup=admin_kb())
    await cb.answer()


# простые текстовые поля (без JSON)
@router.callback_query(F.data.startswith("admin:edit:"))
async def ask_text(cb: CallbackQuery):
    key = cb.data.split(":")[-1]
    pretty = _EDITABLE_SETTINGS.get(key)
    if not pretty:
        await cb.answer()
        return
    await set_setting("edit_target", key)
    cur = await get_setting(key, "")
    prompt_lines = [
        f"Пришлите новый текст для «{pretty}». Поддерживается MarkdownV2.",
        "Используйте кнопку «👁 Предпросмотр», чтобы оценить форматирование.",
    ]
    if cur:
        prompt_lines.append("Текущая версия показана ниже.")
    else:
        prompt_lines.append("Текущая версия: —")

    await send_md_safe(
        cb.message,
        "\n".join(prompt_lines),
        reply_markup=edit_prompt_kb(key),
    )

    if cur:
        await send_md_safe(cb.message, "Текущая версия:")
        await send_md_safe(cb.message, cur)
    await cb.answer()


@router.callback_query(F.data.startswith("admin:preview:"))
async def preview_text(cb: CallbackQuery):
    """Показывает текущую версию настройки с сохранением форматирования."""

    key = cb.data.split(":")[-1]
    if key not in _EDITABLE_SETTINGS:
        await cb.answer()
        return
    stored = await get_setting(key, "")
    if not stored:
        await send_md_safe(cb.message, "Текст пока не задан.")
        await cb.answer()
        return

    await send_md_safe(cb.message, "Предпросмотр:")
    await send_md_safe(cb.message, stored)
    await cb.answer()


@router.message(F.content_type == ContentType.TEXT)
async def save_text(msg: Message):
    target = await get_setting("edit_target","")
    if target not in _EDITABLE_SETTINGS:
        return
    if target == "ready_catalog_url":
        await set_setting(target, (msg.text or msg.caption or "").strip())
    else:
        await set_setting(target, message_to_markdown(msg))
    await set_setting("edit_target","")
    await send_md_safe(
        msg,
        "Готово ✅",
        reply_markup=admin_kb(),
    )

# импорты
@router.callback_query(F.data.startswith("admin:import:"))
async def imp_start(cb: CallbackQuery):
    target_key = cb.data.split(":", maxsplit=2)[-1]

    if target_key == "cancel":
        await set_setting("import_target", "")
        await send_md_safe(cb.message, "Загрузка отменена.", reply_markup=admin_kb())
        await cb.answer()
        return

    target = _IMPORT_TARGETS.get(target_key)

    if not target:
        await send_md_safe(cb.message, "Неизвестный раздел импорта.")
        await cb.answer()
        return

    await set_setting("import_target", target_key)
    await send_md_safe(
        cb.message,
        target["prompt"],
        reply_markup=import_cancel_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data == "admin:import:cancel")
async def import_cancel(cb: CallbackQuery):
    """Отменяет ожидание файла для импорта."""

    await set_setting("import_target", "")
    await send_md_safe(cb.message, "Загрузка отменена.", reply_markup=admin_kb())
    await cb.answer()

@router.message(F.content_type == ContentType.DOCUMENT)
async def import_xlsx(msg: Message):
    target_key = await get_setting("import_target", "")
    if not target_key:
        return

    target_config = _IMPORT_TARGETS.get(target_key)
    if not target_config:
        await msg.answer("Неизвестный раздел импорта.", parse_mode=None)
        await set_setting("import_target", "")
        return

    section = target_config["section"]
    city = target_config.get("city")
    parser = target_config.get("parser")
    parser_kwargs = target_config.get("parser_kwargs", {})
    if parser is None:
        await msg.answer("Не найден обработчик для выбранного импорта.", parse_mode=None)
        await set_setting("import_target", "")
        return

    f = await msg.bot.get_file(msg.document.file_id)
    stream = await msg.bot.download_file(f.file_path)
    file_name = msg.document.file_name or ""
    ext = Path(file_name).suffix.lower()
    if ext == ".xls":
        await msg.answer(
            "Ошибка: формат XLS не поддерживается. Используйте XLSX",
            parse_mode=None,
        )
        await set_setting("import_target", "")
        return
    if ext not in {".xlsx", ".csv"}:
        await msg.answer(
            "Ошибка: поддерживаются только файлы XLSX или CSV.",
            parse_mode=None,
        )
        await set_setting("import_target", "")
        return

    if target_key == "stock_hardware_spb":
        try:
            result = importer.parse_hardware_stock_spb(stream)
        except ImportErrorFriendly as e:
            raise
        except Exception as exc:  # noqa: BLE001
            logging.exception("Ошибка сохранения файла остатков фурнитуры СПБ")
            raise ImportErrorFriendly(
                title="Не удалось сохранить файл остатков фурнитуры СПБ",
                details=str(exc),
                template=None,
            ) from exc

        saved_path = result.get("saved_path") if isinstance(result, dict) else None
        file_note = f" ({Path(saved_path).name})" if saved_path else ""
        await msg.answer(
            f"Файл остатков фурнитуры СПБ сохранён{file_note}.",
            parse_mode=None,
            reply_markup=import_result_keyboard(),
        )
        await set_setting("import_target", "")
        return

    target_section = section
    target_city = city
    try:
        try:
            parsed_result = parser(stream, **parser_kwargs)
        except ImportErrorFriendly as e:
            if getattr(e, "reason", None) == "wrong_section":
                preview = [p or "—" for p in (e.preview or [])]
                text = (
                    "Ошибка: загруженная таблица не соответствует выбранному разделу.\n"
                    f"Обнаружено посторонних записей: {e.total}\n"
                    f"Примеры (первые {len(preview)}):\n"
                    + "\n".join(f"• {p}" for p in preview)
                    + "\n\nПожалуйста, используйте корректный шаблон."
                )
                await msg.answer(text, parse_mode=None)
                template_path = f"templates/{target_key}_example.xlsx"
                if not os.path.exists(template_path):
                    await msg.answer(
                        "Шаблон отсутствует на сервере. Обратитесь к разработчику.",
                        parse_mode=None,
                    )
                    await set_setting("import_target", "")
                    return

                await msg.answer_document(FSInputFile(template_path))
                await set_setting("import_target", "")
                return
            raise
        except Exception as exc:
            logging.exception("Ошибка разбора файла для раздела %s", section)
            raise ImportErrorFriendly(
                title="Не удалось обработать файл",
                details=str(exc),
                template=importer.TABLE_SCHEMAS.get(target_key, {}).get("template_path"),
            ) from exc

        skipped_rows: list[str] = []
        warnings: list[str] = []
        if isinstance(parsed_result, ParsedResult):
            items = parsed_result.items
            imported_count = len(items)
            warnings = parsed_result.warnings
        elif isinstance(parsed_result, dict):
            items = parsed_result.get("items", [])
            imported_count = parsed_result.get("imported", len(items))
            skipped_rows = parsed_result.get("skipped", []) or []
        else:
            items = parsed_result
            imported_count = len(items)

        if warnings:
            preview = [w or "—" for w in warnings]
            text = (
                "⚠️ В таблице найдены строки, которые не относятся к разделу "
                f"{HUMAN_NAME[target_key]}.\n"
                "Импорт прерван.\n\n"
                "Примеры несовпадающих строк:\n"
                + "\n".join(f"• {row}" for row in preview[:20])
                + ("\n… остальные скрыты" if len(preview) > 20 else "")
            )
            await msg.answer(text, parse_mode=None)
            await set_setting("import_target", "")
            return

        if imported_count:
            logging.info(
                f"[IMPORT DONE] Type={target_key} City={city} Items={imported_count}"
            )
        else:
            logging.warning(
                f"[IMPORT WARNING] Parsed 0 items for {target_key} ({city})"
            )

        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute("BEGIN")

                if section in {"fabrics", "hardware"} and target_key.startswith("stock_"):
                    import_count = await add_stock_items(db, items, city, section)
                else:
                    products_exist_cursor = await db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
                    )
                    products_exists = await products_exist_cursor.fetchone()
                    if not products_exists:
                        logging.error("Таблица products не найдена, импорт каталога прерван")
                        if db.in_transaction:
                            await db.rollback()
                        await msg.answer(
                            "Импорт каталога невозможен: таблица products отсутствует.",
                            parse_mode=None,
                        )
                        await set_setting("import_target", "")
                        return

                    target_section = "fabrics" if target_key == "fabrics_catalog" else section
                    target_city = city or ("all" if target_key == "fabrics_catalog" else "Санкт-Петербург")

                    if target_section == "hardware":
                        product_sql = (
                            "INSERT INTO products("  # noqa: ISC003
                            "city,section,category,subcategory,\"group\",name,article,"
                            "special,multiplicity,brand_country,unit,currency,price_rrc,price_opt,image_url"
                            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                        )
                        payload = [
                            (
                                item.get("city", target_city),
                                item.get("section", target_section),
                                item.get("category"),
                                item.get("subcategory"),
                                item.get("group"),
                                item.get("name"),
                                item.get("article"),
                                item.get("special"),
                                item.get("multiplicity"),
                                item.get("brand_country"),
                                item.get("unit"),
                                item.get("currency"),
                                item.get("price_rrc"),
                                item.get("price_opt"),
                                item.get("image_url"),
                            )
                            for item in items
                        ]
                    else:
                        product_sql = (
                            "INSERT INTO products("  # noqa: ISC003
                            "city,section,category,subcategory,name,country,fabric_type,segment,"
                            "wholesale_roll,wholesale_piece,"
                            "price_roll_85_90,price_piece_85_90,price_roll_90_95,price_piece_90_95,price_roll_95_100,price_piece_95_100,"
                            "special,image_url) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                        )

                        payload = []
                        for item in items:
                            payload.append(
                                (
                                    item.get("city", target_city),
                                    item.get("section", target_section),
                                    item.get("category"),
                                    item.get("subcategory"),
                                    item.get("name"),
                                    item.get("country"),
                                    item.get("fabric_type"),
                                    item.get("segment"),
                                    item.get("wholesale_roll"),
                                    item.get("wholesale_piece"),
                                    item.get("price_roll_85_90"),
                                    item.get("price_piece_85_90"),
                                    item.get("price_roll_90_95"),
                                    item.get("price_piece_90_95"),
                                    item.get("price_roll_95_100"),
                                    item.get("price_piece_95_100"),
                                    item.get("special"),
                                    item.get("image_url"),
                                )
                            )

                    try:
                        if target_section == "fabrics":
                            await db.execute(
                                "DELETE FROM products WHERE section='fabrics'",
                            )
                        else:
                            await db.execute(
                                "DELETE FROM products WHERE section='hardware'",
                            )
                        if payload:
                            await db.executemany(product_sql, payload)
                        import_count = len(payload)
                    except sqlite3.OperationalError as exc:
                        logging.error("Ошибка при записи каталога в products: %s", exc)
                        if db.in_transaction:
                            await db.rollback()
                        await msg.answer(
                            "Импорт каталога невозможен: ошибка структуры таблицы products.",
                            parse_mode=None,
                        )
                        await set_setting("import_target", "")
                        return
            except Exception as exc:
                if db.in_transaction:
                    await db.rollback()
                logging.exception("Ошибка импорта раздела %s", section)
                raise ImportErrorFriendly(
                    title="Импорт прерван из-за ошибки",
                    details=str(exc),
                    template=importer.TABLE_SCHEMAS.get(target_key, {}).get("template_path"),
                ) from exc
            else:
                row = None
                if target_section in {"fabrics", "fabrics_catalog"} and not target_key.startswith(
                    "stock_"
                ):
                    cursor = await db.execute(
                        "SELECT * FROM products WHERE section=? AND city=? AND name=?",
                        (target_section, target_city, "BISON"),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        logging.warning(
                            "Не найдена коллекция BISON после импорта, выводим первую запись раздела тканей."
                        )
                        cursor = await db.execute(
                            "SELECT * FROM products WHERE section=? AND city=? LIMIT 1",
                            (target_section, target_city),
                        )
                        row = await cursor.fetchone()
                    if row is not None:
                        columns = [desc[0] for desc in cursor.description]
                        snapshot = {column: row[idx] for idx, column in enumerate(columns)}
                        logging.info("Запись ткани после импорта: %s", snapshot)
                    else:
                        logging.warning(
                            "После импорта раздела тканей записи не найдены."
                        )
                if not target_key.startswith("stock_"):
                    await db.commit()

        await set_setting("import_target", "")

        if skipped_rows:
            skipped_lines = [
                f"{idx}) {escape_md(name)}" for idx, name in enumerate(skipped_rows, start=1)
            ]
            skipped_text = "\n".join(
                [
                    "⚠️ Обнаружены посторонние позиции, не относящиеся к тканям:",
                    "",
                    *skipped_lines,
                    "",
                    "Эти строки были пропущены.",
                    f"Импорт завершён: добавлено {import_count} позиций.",
                ]
            )
            await send_md_safe(msg, skipped_text, reply_markup=import_result_keyboard())
        else:
            await send_md_safe(
                msg,
                f"Импортировано {import_count} позиций для раздела {target_config['title']}",
                reply_markup=import_result_keyboard(),
            )
    except ImportErrorFriendly as e:
        if getattr(e, "reason", None) == "bad_xlsx":
            await msg.answer(
                "Ошибка: файл XLSX повреждён или сохранён в неподдерживаемом режиме Excel.\n"
                "Пожалуйста, откройте таблицу в Excel и сохраните через:\n"
                "Файл → Сохранить как → Excel (*.xlsx) (ОБЫЧНЫЙ, не Strict OpenXML).",
                parse_mode=None,
            )
            await set_setting("import_target", "")
            return

        if getattr(e, "reason", None) == "missing_columns":
            missing_cols = e.preview or []
            text = (
                "Ошибка: в таблице отсутствуют обязательные столбцы:\n"
                + "\n".join(f"• {col}" for col in missing_cols)
            )
            await msg.answer(text, parse_mode=None)
            await set_setting("import_target", "")
            return

        text = (
            f"Ошибка! {e.title}.\n\n"
            + (f"{e.details}\n\n" if e.details else "")
            + "Пожалуйста, используйте корректный шаблон."
        )

        await msg.answer(text, parse_mode=None)

        if e.template:
            template_path = e.template
            if not os.path.exists(template_path):
                await msg.answer(
                    "Шаблон отсутствует на сервере. Обратитесь к разработчику.",
                    parse_mode=None,
                )
                await set_setting("import_target", "")
                return

            await msg.answer_document(FSInputFile(template_path))

        await set_setting("import_target", "")
        return
