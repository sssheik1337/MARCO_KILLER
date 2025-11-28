import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from middlewares.admin_filter import AdminOnly
from data.db_utils import set_setting, get_setting
from data.importer import parse_fabrics, parse_hardware, parse_stock
import aiosqlite
from config import DB_PATH, DEFAULT_CITY
from structure.markdown import send_md_safe, edit_md_safe, message_to_markdown, escape_user
from structure.keyboards import usd_keyboard, import_result_keyboard
from services.exchange import current_range, refresh_range

router = Router()
router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())


_EDITABLE_SETTINGS = {
    "contacts": "Контакты",
    "address": "Адрес/маршрут",
    "worktime": "Режим работы",
    "requisites": "Реквизиты",
}


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📇 Править контакты", callback_data="admin:edit:contacts"),
         InlineKeyboardButton(text="🗺️ Адрес/маршрут", callback_data="admin:edit:address")],
        [InlineKeyboardButton(text="🕘 Режим работы", callback_data="admin:edit:worktime"),
         InlineKeyboardButton(text="📄 Реквизиты", callback_data="admin:edit:requisites")],
        [InlineKeyboardButton(text="📤 Импорт ТКАНИ (xlsx)", callback_data="admin:import:fabrics")],
        [InlineKeyboardButton(text="📤 Импорт ФУРНИТУРА (xlsx)", callback_data="admin:import:hardware")],
        [InlineKeyboardButton(text="📦 Импорт НАЛИЧИЕ (xlsx)", callback_data="admin:import:stock")],
        [InlineKeyboardButton(text="💵 Курс USD: авто/ручной", callback_data="admin:usd")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
    ])


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

    await cb.answer("Курс обновлён")

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
    await set_setting(target, message_to_markdown(msg))
    await set_setting("edit_target","")
    await send_md_safe(
        msg,
        "Готово ✅",
        reply_markup=admin_kb(),
    )

# импорты
@router.callback_query(F.data == "admin:import:fabrics")
async def imp_fabrics(cb: CallbackQuery): 
    await set_setting("import_target","fabrics")
    await send_md_safe(
        cb.message,
        "Пришлите XLSX с тканями.",
    )

@router.callback_query(F.data == "admin:import:hardware")
async def imp_hw(cb: CallbackQuery):
    await set_setting("import_target","hardware")
    await send_md_safe(
        cb.message,
        "Пришлите XLSX с фурнитурой.",
    )


@router.callback_query(F.data == "admin:import:stock")
async def imp_stock(cb: CallbackQuery):
    await set_setting("import_target", "stock")
    await send_md_safe(
        cb.message,
        "Пришлите XLSX с остатками товаров.",
    )

@router.message(F.content_type == ContentType.DOCUMENT)
async def import_xlsx(msg: Message):
    target = await get_setting("import_target","")
    if not target:
        return

    city = DEFAULT_CITY

    f = await msg.bot.get_file(msg.document.file_id)
    stream = await msg.bot.download_file(f.file_path)
    section_title = {
        "fabrics": "«ткани»",
        "hardware": "«фурнитура»",
        "stock": "«наличие»",
    }

    try:
        if target == "fabrics":
            items = parse_fabrics(stream, city=city)
        elif target == "hardware":
            items = parse_hardware(stream, city=city)
        elif target == "stock":
            items = parse_stock(stream, city=city)
        else:
            await send_md_safe(msg, "Неизвестный раздел импорта.")
            return
    except Exception as exc:
        logging.exception("Ошибка разбора файла для раздела %s", target)
        await send_md_safe(
            msg,
            f"Не удалось обработать файл: {escape_user(str(exc))}",
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("BEGIN")

            if target == "stock":
                await db.execute("DELETE FROM stock_items WHERE city=?", (city,))
                stock_sql = (
                    "INSERT INTO stock_items(city,section,category,name,article,quantity,unit) "
                    "VALUES(?,?,?,?,?,?,?)"
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
                    (target, city),
                )
                if payload:
                    await db.executemany(product_sql, payload)
                import_count = len(payload)
        except Exception as exc:
            if db.in_transaction:
                await db.rollback()
            logging.exception("Ошибка импорта раздела %s", target)
            await send_md_safe(
                msg,
                f"Импорт прерван из-за ошибки: {escape_user(str(exc))}",
            )
            return
        else:
            row = None
            if target == "fabrics":
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
                    logging.info(
                        "Запись ткани после импорта: %s",
                        snapshot,
                    )
                else:
                    logging.warning(
                        "После импорта раздела тканей записи не найдены."
                    )
            await db.commit()

    await set_setting("import_target","")
    await send_md_safe(
        msg,
        f"Импортировано {import_count} позиций для раздела {section_title.get(target, target)}",
        reply_markup=import_result_keyboard(),
    )
