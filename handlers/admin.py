import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from middlewares.admin_filter import AdminOnly
from data.db_utils import (
    fetch_active_users,
    find_catalog_product_by_article,
    find_product_by_code,
    get_setting,
    mark_user_blocked,
    set_setting,
)
from data.importer import parse_fabrics, parse_hardware, parse_stock
import aiosqlite
from config import DB_PATH
from structure.markdown import send_md_safe, edit_md_safe, message_to_markdown, escape_user, send_md_safe_to_chat
from structure.keyboards import usd_keyboard, import_result_keyboard
from structure.states import BroadcastState
from services.exchange import current_range, refresh_range
from services.notifications import broadcast, build_product_card
from services.product_render import build_product_caption

router = Router()
router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())


_EDITABLE_SETTINGS = {
    "contacts": "Контакты",
    "address": "Адрес/маршрут",
    "worktime": "Режим работы",
    "requisites": "Реквизиты",
    "ready_catalog_url": "Ссылка на каталог готовых изделий",
}


_IMPORT_TARGETS = {
    "fabrics_msk": {
        "section": "fabrics",
        "city": "msk",
        "prompt": "Пришлите XLSX с тканями для Москвы.",
        "title": "ткани (Москва)",
    },
    "fabrics_spb": {
        "section": "fabrics",
        "city": "spb",
        "prompt": "Пришлите XLSX с тканями для Санкт-Петербурга.",
        "title": "ткани (СПБ)",
    },
    "hardware_msk": {
        "section": "hardware",
        "city": "msk",
        "prompt": "Пришлите XLSX с фурнитурой для Москвы.",
        "title": "фурнитура (Москва)",
    },
    "hardware_spb": {
        "section": "hardware",
        "city": "spb",
        "prompt": "Пришлите XLSX с фурнитурой для Санкт-Петербурга.",
        "title": "фурнитура (СПБ)",
    },
    "stock_msk": {
        "section": "stock",
        "city": "msk",
        "prompt": "Пришлите XLSX с остатками для Москвы.",
        "title": "наличие (Москва)",
    },
    "stock_spb": {
        "section": "stock",
        "city": "spb",
        "prompt": "Пришлите XLSX с остатками для Санкт-Петербурга.",
        "title": "наличие (СПБ)",
    },
}


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


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📇 Править контакты", callback_data="admin:edit:contacts"),
         InlineKeyboardButton(text="🗺️ Адрес/маршрут", callback_data="admin:edit:address")],
        [InlineKeyboardButton(text="🕘 Режим работы", callback_data="admin:edit:worktime"),
         InlineKeyboardButton(text="📄 Реквизиты", callback_data="admin:edit:requisites")],
        [InlineKeyboardButton(text="Изменить ссылку на каталог готовых изделий", callback_data="admin:edit:ready_catalog_url")],
        [InlineKeyboardButton(text="📤 Ткани Москва (xlsx)", callback_data="admin:import:fabrics_msk"),
         InlineKeyboardButton(text="📤 Ткани СПБ (xlsx)", callback_data="admin:import:fabrics_spb")],
        [InlineKeyboardButton(text="📤 Фурнитура Москва (xlsx)", callback_data="admin:import:hardware_msk"),
         InlineKeyboardButton(text="📤 Фурнитура СПБ (xlsx)", callback_data="admin:import:hardware_spb")],
        [InlineKeyboardButton(text="📦 Наличие Москва (xlsx)", callback_data="admin:import:stock_msk"),
         InlineKeyboardButton(text="📦 Наличие СПБ (xlsx)", callback_data="admin:import:stock_spb")],
        [InlineKeyboardButton(text="Публикация акции / новинки / распродажи", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💵 Курс USD: авто/ручной", callback_data="admin:usd")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
    ])


def broadcast_type_kb() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру выбора типа рассылки."""

    buttons = [
        InlineKeyboardButton(text=cfg["label"], callback_data=f"admin:broadcast:type:{key}")
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


@router.callback_query(F.data == "admin:open")
async def open_admin(cb: CallbackQuery):
    await send_md_safe(
        cb.message,
        "Админ-панель:",
        reply_markup=admin_kb(),
    )
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


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_menu(cb: CallbackQuery, state: FSMContext):
    """Запускает сценарий рассылки по артикулу."""

    await state.clear()
    await send_md_safe(
        cb.message,
        "Выберите тип рассылки:",
        reply_markup=broadcast_type_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:broadcast:type:"))
async def choose_broadcast_type(cb: CallbackQuery, state: FSMContext):
    """Фиксирует выбранный тип и запрашивает артикул товара."""

    broadcast_type = cb.data.split(":")[-1]
    if broadcast_type not in _BROADCAST_TYPES:
        await cb.answer("Неизвестный тип", show_alert=True)
        return

    await state.set_state(BroadcastState.waiting_article)
    await state.update_data(broadcast_type=broadcast_type)
    label = _BROADCAST_TYPES[broadcast_type]["label"]
    await send_md_safe(
        cb.message,
        f"Вы выбрали {label}. Пришлите артикул товара или серийный номер для рассылки.",
    )
    await cb.answer()


@router.message(BroadcastState.waiting_article)
async def process_broadcast(msg: Message, state: FSMContext):
    """Ищет товар по артикулу и отправляет карточку всем пользователям."""

    data = await state.get_data()
    broadcast_type = data.get("broadcast_type")
    if not broadcast_type or broadcast_type not in _BROADCAST_TYPES:
        await send_md_safe(msg, "Сначала выберите тип рассылки через меню админа.")
        await state.clear()
        return

    article = (msg.text or msg.caption or "").strip()
    if not article:
        await send_md_safe(msg, "Пришлите артикул товара для рассылки.")
        return

    product = await find_product_by_code(article)
    if not product:
        await send_md_safe(msg, "Товар с таким артикулом не найден.")
        await state.clear()
        return

    rng, usd = await current_range()
    caption = build_product_caption(
        product,
        rng,
        usd,
        include_city=True,
        prefix=_BROADCAST_TYPES[broadcast_type]["label"],
    )

    recipients = await fetch_active_users()
    if not recipients:
        await send_md_safe(msg, "Список пользователей пуст, отправлять некому.")
        await state.clear()
        return

    sent = 0
    blocked = 0
    for user_id in recipients:
        try:
            await send_md_safe_to_chat(msg.bot, user_id, caption)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            await mark_user_blocked(user_id)
        except TelegramBadRequest as exc:
            logging.warning("Не удалось отправить рассылку пользователю %s: %s", user_id, exc)
        except Exception as exc:  # pragma: no cover - логирование сетевых ошибок
            logging.warning("Сбой отправки рассылки пользователю %s: %s", user_id, exc)

    await state.clear()
    await send_md_safe(
        msg,
        f"Рассылка завершена. Доставлено: {sent}. Заблокировали: {blocked}.",
        reply_markup=admin_kb(),
    )

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
    if key == "ready_catalog_url":
        prompt_lines = [
            "Пришлите новую ссылку на каталог готовых изделий.",
            "Текущая ссылка будет показана ниже, если она сохранена.",
        ]
    else:
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
    target = _IMPORT_TARGETS.get(target_key)

    if not target:
        await send_md_safe(cb.message, "Неизвестный раздел импорта.")
        await cb.answer()
        return

    await set_setting("import_target", target_key)
    await send_md_safe(
        cb.message,
        target["prompt"],
    )
    await cb.answer()

@router.message(F.content_type == ContentType.DOCUMENT)
async def import_xlsx(msg: Message):
    target_key = await get_setting("import_target", "")
    if not target_key:
        return

    target_config = _IMPORT_TARGETS.get(target_key)
    if not target_config:
        await send_md_safe(msg, "Неизвестный раздел импорта.")
        await set_setting("import_target", "")
        return

    section = target_config["section"]
    city = target_config["city"]

    f = await msg.bot.get_file(msg.document.file_id)
    stream = await msg.bot.download_file(f.file_path)
    file_name = (msg.document.file_name or "").lower()
    if not file_name.endswith(".xlsx"):
        await send_md_safe(
            msg,
            "Ошибка: формат XLS не поддерживается. Загрузите файл в формате XLSX.",
        )
        await set_setting("import_target", "")
        return

    try:
        if section == "fabrics":
            items = parse_fabrics(stream, city=city)
        elif section == "hardware":
            items = parse_hardware(stream, city=city)
        elif section == "stock":
            items = parse_stock(stream, city=city)
        else:
            await send_md_safe(msg, "Неизвестный раздел импорта.")
            return
    except Exception as exc:
        logging.exception("Ошибка разбора файла для раздела %s", section)
        await send_md_safe(
            msg,
            f"Не удалось обработать файл: {escape_user(str(exc))}",
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("BEGIN")

            if section == "stock":
                await db.execute("DELETE FROM stock_items WHERE city=?", (city,))
                stock_sql = (
                    "INSERT INTO stock_items(city,section,category,name,article,quantity,unit,status) "
                    "VALUES(?,?,?,?,?,?,?,?)"
                )
                stock_payload = [
                    (
                        item.get("city", city),
                        item.get("section"),
                        item.get("category"),
                        item.get("name"),
                        item.get("article"),
                        item.get("quantity"),
                        item.get("unit"),
                        item.get("status"),
                    )
                    for item in items
                ]
                if stock_payload:
                    await db.executemany(stock_sql, stock_payload)
                import_count = len(stock_payload)
            else:
                product_sql = (
                    "INSERT INTO products("  # noqa: ISC003
                    "city,section,category,subcategory,name,article,country,fabric_type,segment,"
                    "collection,brand_country,multiplicity,unit,currency,status,"
                    "price_piece_85_90,price_roll_85_90,price_piece_90_95,price_roll_90_95,price_piece_95_100,price_roll_95_100,"
                    "price_rrc,price_opt,special,in_stock,image_url) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                )

                payload = [
                    (
                        item.get("city", city),
                        item.get("section"),
                        item.get("category"),
                        item.get("subcategory"),
                        item.get("name"),
                        item.get("article"),
                        item.get("country"),
                        item.get("fabric_type"),
                        item.get("segment"),
                        item.get("collection"),
                        item.get("brand_country"),
                        item.get("multiplicity"),
                        item.get("unit"),
                        item.get("currency"),
                        item.get("status"),
                        item.get("price_piece_85_90"),
                        item.get("price_roll_85_90"),
                        item.get("price_piece_90_95"),
                        item.get("price_roll_90_95"),
                        item.get("price_piece_95_100"),
                        item.get("price_roll_95_100"),
                        item.get("price_rrc"),
                        item.get("price_opt"),
                        item.get("special"),
                        item.get("in_stock"),
                        item.get("image_url"),
                    )
                    for item in items
                ]

                await db.execute(
                    "DELETE FROM products WHERE section=? AND city=?",
                    (section, city),
                )
                if payload:
                    await db.executemany(product_sql, payload)
                import_count = len(payload)
        except Exception as exc:
            if db.in_transaction:
                await db.rollback()
            logging.exception("Ошибка импорта раздела %s", section)
            await send_md_safe(
                msg,
                f"Импорт прерван из-за ошибки: {escape_user(str(exc))}",
            )
            return
        else:
            row = None
            if section == "fabrics":
                cursor = await db.execute(
                    "SELECT * FROM products WHERE section=? AND city=? AND name LIKE ?",
                    ("fabrics", city, "%BISON%"),
                )
                row = await cursor.fetchone()
                if row is None:
                    logging.warning(
                        "Не найдена коллекция BISON после импорта, выводим первую запись раздела тканей."
                    )
                    cursor = await db.execute(
                        "SELECT * FROM products WHERE section=? AND city=? LIMIT 1",
                        ("fabrics", city),
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
            await db.commit()

    await set_setting("import_target", "")
    await send_md_safe(
        msg,
        f"Импортировано {import_count} позиций для раздела {target_config['title']}",
        reply_markup=import_result_keyboard(),
    )
