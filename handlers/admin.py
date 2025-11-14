from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from middlewares.admin_filter import AdminOnly
from data.db_utils import set_setting, get_setting
from data.importer import parse_fabrics, parse_hardware
import aiosqlite
from config import DB_PATH
from structure.markdown import send_md_safe, edit_md_safe, message_to_markdown
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

@router.message(F.content_type == ContentType.DOCUMENT)
async def import_xlsx(msg: Message):
    target = await get_setting("import_target","")
    if not target: return
    f = await msg.bot.get_file(msg.document.file_id)
    stream = await msg.bot.download_file(f.file_path)
    if target == "fabrics":
        items = parse_fabrics(stream)
    else:
        items = parse_hardware(stream)
    # полная замена раздела
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE section=?", (target,))
        sql = ("INSERT INTO products(section,category,subcategory,name,article,country,fabric_type,segment,"
               "collection,brand_country,multiplicity,unit,currency,status,"
               "price_piece_85_90,price_roll_85_90,price_piece_90_95,price_roll_90_95,price_piece_95_100,price_roll_95_100,"
               "price_rrc,price_opt,special,in_stock,image_url) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        await db.executemany(sql, [(
            i.get("section"), i.get("category"), i.get("subcategory"), i.get("name"), i.get("article"),
            i.get("country"), i.get("fabric_type"), i.get("segment"),
            i.get("collection"), i.get("brand_country"), i.get("multiplicity"), i.get("unit"), i.get("currency"), i.get("status"),
            i.get("price_piece_85_90"), i.get("price_roll_85_90"),
            i.get("price_piece_90_95"), i.get("price_roll_90_95"),
            i.get("price_piece_95_100"), i.get("price_roll_95_100"),
            i.get("price_rrc"), i.get("price_opt"), i.get("special"),
            i.get("in_stock"), i.get("image_url")
        ) for i in items])
        await db.commit()
    await set_setting("import_target","")
    await send_md_safe(
        msg,
        f"Импортировано {len(items)} позиций",
        reply_markup=import_result_keyboard(),
    )
