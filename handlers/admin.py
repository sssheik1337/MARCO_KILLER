from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from middlewares.admin_filter import AdminOnly
from data.db_utils import set_setting, get_setting
from data.importer import parse_fabrics, parse_hardware
from data.db_utils import init_db
from data.db_utils import aiosqlite
from config import DB_PATH
from pathlib import Path
from structure.markdown_utils import safe_answer, safe_edit
from structure.keyboards import usd_keyboard, import_result_keyboard
from services.exchange import current_range, refresh_range

router = Router()
router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())

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
    await safe_answer(
        cb.message,
        "Админ-панель:",
        reply_markup=admin_kb(),
        parse_mode="MarkdownV2",
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
    await safe_answer(
        cb.message,
        text,
        reply_markup=usd_keyboard(),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data == "admin:usd:refresh")
async def refresh_usd(cb: CallbackQuery):
    rng, usd = await refresh_range()
    text = _format_usd_message(rng, usd)
    await safe_edit(
        cb.message,
        text,
        reply_markup=usd_keyboard(),
        parse_mode="MarkdownV2",
    )
    await cb.answer("Курс обновлён")

# простые текстовые поля (без JSON)
@router.callback_query(F.data.startswith("admin:edit:"))
async def ask_text(cb: CallbackQuery):
    key = cb.data.split(":")[-1]
    pretty = {"contacts":"Контакты","address":"Адрес/маршрут","worktime":"Режим работы","requisites":"Реквизиты"}[key]
    await set_setting("edit_target", key)
    cur = await get_setting(key, "")
    prompt = (
        f"Пришлите новый текст для «{pretty}». Поддерживается MarkdownV2.\n"
        "Используйте кнопку «👁 Предпросмотр», чтобы оценить форматирование.\n"
        f"Текущая версия:\n{cur or '—'}"
    )
    await safe_answer(
        cb.message,
        prompt,
        reply_markup=edit_prompt_kb(key),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:preview:"))
async def preview_text(cb: CallbackQuery):
    """Показывает текущую версию настройки с сохранением форматирования."""

    key = cb.data.split(":")[-1]
    stored = await get_setting(key, "")
    if not stored:
        await safe_answer(
            cb.message,
            "Текст пока не задан.",
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return

    try:
        await safe_answer(
            cb.message,
            stored,
            escape=False,
            parse_mode="MarkdownV2",
        )
    except TelegramBadRequest as error:
        await safe_answer(
            cb.message,
            f"Не удалось показать предпросмотр: {error.message}",
            parse_mode="MarkdownV2",
        )
    await cb.answer()


@router.message(F.content_type == ContentType.TEXT)
async def save_text(msg: Message):
    target = await get_setting("edit_target","")
    if not target: 
        return
    await set_setting(target, msg.text)
    await set_setting("edit_target","")
    await safe_answer(
        msg,
        "Готово ✅",
        reply_markup=admin_kb(),
        parse_mode="MarkdownV2",
    )

# импорты
@router.callback_query(F.data == "admin:import:fabrics")
async def imp_fabrics(cb: CallbackQuery): 
    await set_setting("import_target","fabrics")
    await safe_answer(
        cb.message,
        "Пришлите XLSX с тканями.",
        parse_mode="MarkdownV2",
    )

@router.callback_query(F.data == "admin:import:hardware")
async def imp_hw(cb: CallbackQuery): 
    await set_setting("import_target","hardware")
    await safe_answer(
        cb.message,
        "Пришлите XLSX с фурнитурой.",
        parse_mode="MarkdownV2",
    )

@router.message(F.content_type == ContentType.DOCUMENT)
async def import_xlsx(msg: Message):
    target = await get_setting("import_target","")
    if not target: return
    f = await msg.bot.get_file(msg.document.file_id)
    p = await msg.bot.download_file(f.file_path)
    if target == "fabrics":
        items = parse_fabrics(p.name)
    else:
        items = parse_hardware(p.name)
    # полная замена раздела
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE section=?", (target,))
        sql = ("INSERT INTO products(section,category,subcategory,name,article,country,fabric_type,segment,"
               "price_piece_85_90,price_roll_85_90,price_piece_90_95,price_roll_90_95,price_piece_95_100,price_roll_95_100,"
               "price_rrc,price_opt,special,in_stock,image_url) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        await db.executemany(sql, [(
            i.get("section"), i.get("category"), i.get("subcategory"), i.get("name"), i.get("article"),
            i.get("country"), i.get("fabric_type"), i.get("segment"),
            i.get("price_piece_85_90"), i.get("price_roll_85_90"),
            i.get("price_piece_90_95"), i.get("price_roll_90_95"),
            i.get("price_piece_95_100"), i.get("price_roll_95_100"),
            i.get("price_rrc"), i.get("price_opt"), i.get("special"),
            i.get("in_stock"), i.get("image_url")
        ) for i in items])
        await db.commit()
    await set_setting("import_target","")
    await safe_answer(
        msg,
        f"Импортировано {len(items)} позиций",
        reply_markup=import_result_keyboard(),
        parse_mode="MarkdownV2",
    )
