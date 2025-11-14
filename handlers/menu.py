# handlers/menu.py
import logging
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from config import PAGE_SIZE, ADMINS
from structure.keyboards import main_menu, pager, product_controls, empty_catalog_keyboard
from structure.markdown_utils import safe_answer
from structure.formatter import escape_md
from structure.states import SupportRequestState
from services.pagination import slice_page
from services import cart
from data import db_utils
from services.exchange import current_range, range_label

router = Router()
logger = logging.getLogger(__name__)


# --- утилиты ---

def _is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def _mdv2(s: str | None) -> str:
    """Минимальный экранировщик для MarkdownV2 (достаточно для наших полей)."""
    if not s:
        return "-"
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("~", "\\~")
        .replace("`", "\\`")
        .replace(">", "\\>")
        .replace("#", "\\#")
        .replace("+", "\\+")
        .replace("-", "\\-")
        .replace("=", "\\=")
        .replace("|", "\\|")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace(".", "\\.")
        .replace("!", "\\!")
    )


# --- настройки обращений ---

_REQUEST_TYPES = {
    "menu:callback": "callback",
    "menu:question": "question",
    "menu:boss": "boss",
    "menu:bug": "bug",
}

_REQUEST_PROMPTS = {
    "callback": "Оставьте номер телефона и удобное время для звонка.",
    "question": "Опишите ваш вопрос, и мы постараемся ответить как можно быстрее.",
    "boss": "Напишите сообщение для руководителя.",
    "bug": "Расскажите, с какой ошибкой вы столкнулись.",
}

_REQUEST_CONFIRMATIONS = {
    "callback": "Спасибо! Менеджер скоро свяжется с вами.",
    "question": "Спасибо! Мы подготовим ответ и вернёмся к вам.",
    "boss": "Спасибо! Руководитель получит ваше сообщение.",
    "bug": "Спасибо за обратную связь! Мы уже разбираемся.",
}

_REQUEST_TITLES = {
    "callback": "Заявка на звонок",
    "question": "Вопрос от клиента",
    "boss": "Сообщение для руководителя",
    "bug": "Сообщение об ошибке",
}


# --- утилиты каталога ---

def _label_sections(sections: list[str]) -> list[tuple[str, str]]:
    """Возвращает пары «заголовок → идентификатор» для разделов."""

    titles = {
        "fabrics": "🧵 Ткани",
        "hardware": "🔩 Фурнитура",
    }
    return [(titles.get(section, section.title()), section) for section in sections]


# --- главное меню ---

@router.callback_query(F.data == "home")
async def on_home(cb: CallbackQuery):
    await safe_answer(
        cb.message,
        "Главное меню:",
        reply_markup=main_menu(_is_admin(cb.from_user.id)),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


# --- каталог: разделы → категории → товары ---

@router.callback_query(F.data == "menu:catalog")
async def catalog_root(cb: CallbackQuery):
    sections = await db_utils.fetch_sections()                # ['fabrics', 'hardware']
    if not sections:
        is_admin = _is_admin(cb.from_user.id)
        await safe_answer(
            cb.message,
            "Каталог пуст: загрузите XLSX тканей и фурнитуры",
            reply_markup=empty_catalog_keyboard(is_admin),
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return

    # пагинация разделов
    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, 1, PAGE_SIZE)

    rng, usd = await current_range()
    label = range_label(rng, usd)  # «Курс: 91.05 ₽ → 90–95»

    await safe_answer(
        cb.message,
        label,
        reply_markup=pager("sec", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data == "menu:stock")
async def catalog_in_stock(cb: CallbackQuery):
    """Фильтр по товарам, которые есть в наличии."""

    sections = await db_utils.fetch_sections(only_available=True)
    if not sections:
        await safe_answer(
            cb.message,
            "Сейчас нет товаров в наличии.",
            reply_markup=main_menu(_is_admin(cb.from_user.id)),
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return

    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, 1, PAGE_SIZE)

    await safe_answer(
        cb.message,
        "Товары в наличии: выберите раздел.",
        reply_markup=pager("secstock", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^sec(stock)?:page:"))
async def catalog_sections_page(cb: CallbackQuery):
    parts = cb.data.split(":")
    prefix = parts[0]
    page = int(parts[-1])
    only_available = prefix == "secstock"
    sections = await db_utils.fetch_sections(only_available=only_available)
    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(prefix, page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^sec(stock)?:open:"))
async def open_section(cb: CallbackQuery):
    parts = cb.data.split(":")
    prefix = parts[0]
    section = parts[-1]                          # 'fabrics' | 'hardware'
    only_available = prefix == "secstock"
    cats = await db_utils.fetch_categories(section, only_available=only_available)
    if not cats:
        await safe_answer(
            cb.message,
            "Здесь пока пусто.",
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return
    items = [(c, c) for c in cats]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    cat_prefix = "catstock" if only_available else "cat"
    await safe_answer(
        cb.message,
        "Категории:",
        reply_markup=pager(f"{cat_prefix}:{section}", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^cat(stock)?:[^:]+:page:"))
async def open_category_page(cb: CallbackQuery):
    # формат: cat{stock}:{section}:page:{N}
    parts = cb.data.split(":")
    prefix = parts[0]
    section = parts[1]
    page = int(parts[-1])
    only_available = prefix == "catstock"
    cats = await db_utils.fetch_categories(section, only_available=only_available)
    items = [(c, c) for c in cats]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(f"{prefix}:{section}", page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^cat(stock)?:[^:]+:open:"))
async def open_category(cb: CallbackQuery):
    # формат: cat{stock}:{section}:open:{category}
    parts = cb.data.split(":")
    prefix = parts[0]
    section = parts[1]
    category = parts[-1]
    only_available = prefix == "catstock"
    prods = await db_utils.fetch_products_by_category(
        section,
        category,
        only_available=only_available,
    )
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    prod_prefix = "prodliststock" if only_available else "prodlist"
    await safe_answer(
        cb.message,
        category,
        reply_markup=pager(
            f"{prod_prefix}:{section}:{category}", page_items, page, total
        ),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^prodlist(stock)?:[^:]+:[^:]+:page:"))
async def product_list_page(cb: CallbackQuery):
    # формат: prodlist{stock}:{section}:{category}:page:{N}
    parts = cb.data.split(":")
    prefix = parts[0]
    section = parts[1]
    category = parts[2]
    page = int(parts[-1])
    only_available = prefix == "prodliststock"
    prods = await db_utils.fetch_products_by_category(
        section,
        category,
        only_available=only_available,
    )
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(
            f"{prefix}:{section}:{category}", page_items, page, total
        )
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^prodlist(stock)?:[^:]+:[^:]+:open:"))
async def product_card(cb: CallbackQuery):
    # формат: prodlist{stock}:{section}:{category}:open:{product_id}
    parts = cb.data.split(":")
    pid = int(parts[-1])
    p = await db_utils.fetch_product(pid)

    rng, usd = await current_range()            # ('90_95', 91.12) или (последний, None)
    lbl = range_label(rng, usd)

    # цены
    if p["section"] == "fabrics":
        piece = p.get(f"price_piece_{rng}")
        roll = p.get(f"price_roll_{rng}")
        price_line = f"Отрез: {piece or '-'} · Ролик: {roll or '-'}"
    else:
        price_line = f"РРЦ: {p.get('price_rrc') or '-'} · Опт: {p.get('price_opt') or '-'}"

    qty = cart.get_qty(cb.from_user.id, pid) or 1

    caption = (
        f"*{_mdv2(p.get('name'))}*\n"
        f"Артикул: {_mdv2(p.get('article'))}\n"
        f"{_mdv2(price_line)}\n"
        f"Наличие: {p.get('in_stock') or 0}\n"
        f"{_mdv2(lbl)}"
    )

    if p.get("image_url"):
        await cb.message.answer_photo(
            p["image_url"], caption=caption, parse_mode="MarkdownV2",
            reply_markup=product_controls(pid, qty)
        )
    else:
        await safe_answer(
            cb.message,
            caption,
            parse_mode="MarkdownV2",
            reply_markup=product_controls(pid, qty),
        )
    await cb.answer()


# --- карточка: +/- и добавление в корзину ---

@router.callback_query(F.data.startswith("prod:inc:"))
async def prod_inc(cb: CallbackQuery):
    pid = int(cb.data.split(":")[-1])
    q = cart.inc(cb.from_user.id, pid)
    await cb.message.edit_reply_markup(reply_markup=product_controls(pid, q))
    await cb.answer("Добавлено")


@router.callback_query(F.data.startswith("prod:dec:"))
async def prod_dec(cb: CallbackQuery):
    pid = int(cb.data.split(":")[-1])
    q = cart.dec(cb.from_user.id, pid)
    q = q or 1
    await cb.message.edit_reply_markup(reply_markup=product_controls(pid, q))
    await cb.answer("Убрано")


@router.callback_query(F.data.startswith("prod:add:"))
async def prod_add(cb: CallbackQuery):
    pid = int(cb.data.split(":")[-1])
    q = max(1, cart.get_qty(cb.from_user.id, pid))
    cart.inc(cb.from_user.id, pid, 0)  # зафиксировать текущее значение
    await cb.answer(f"В корзине: {q}")


# --- корзина и прайс ---

@router.callback_query(F.data == "menu:cart")
async def show_cart(cb: CallbackQuery):
    lines = cart.as_lines(cb.from_user.id)
    text = "\n".join(lines) if lines else "Корзина пуста"
    await safe_answer(
        cb.message,
        text,
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data == "menu:price")
async def show_price(cb: CallbackQuery):
    """Прайс идёт по тому же пути, что и каталог: разделы → категории → товары."""

    sections = await db_utils.fetch_sections()
    if not sections:
        is_admin = _is_admin(cb.from_user.id)
        await safe_answer(
            cb.message,
            "Каталог пуст: загрузите XLSX тканей и фурнитуры",
            reply_markup=empty_catalog_keyboard(is_admin),
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return

    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, 1, PAGE_SIZE)

    rng, usd = await current_range()
    label = range_label(rng, usd)

    await safe_answer(
        cb.message,
        label,
        reply_markup=pager("sec", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


# --- информационные страницы ---

async def _send_setting_message(cb: CallbackQuery, key: str, empty_text: str) -> None:
    """Выводит текст из настроек или запасной вариант."""

    stored = await db_utils.get_setting(key, "")
    text = stored or empty_text
    await safe_answer(
        cb.message,
        text,
        reply_markup=main_menu(_is_admin(cb.from_user.id)),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data == "menu:contacts")
async def show_contacts(cb: CallbackQuery):
    await _send_setting_message(
        cb,
        "contacts",
        "Контакты пока не заполнены.",
    )


@router.callback_query(F.data == "menu:route")
async def show_route(cb: CallbackQuery):
    await _send_setting_message(
        cb,
        "address",
        "Адрес пока не указан.",
    )


@router.callback_query(F.data == "menu:requisites")
async def show_requisites(cb: CallbackQuery):
    await _send_setting_message(
        cb,
        "requisites",
        "Реквизиты пока не добавлены.",
    )



# --- обращения пользователей ---

async def _start_request(cb: CallbackQuery, state: FSMContext, request_key: str) -> None:
    """Подготавливает сбор данных для выбранного обращения."""

    await state.set_state(SupportRequestState.waiting_text)
    await state.update_data(request_type=request_key)
    await safe_answer(
        cb.message,
        _REQUEST_PROMPTS[request_key],
        parse_mode="MarkdownV2",
    )
    await cb.answer()


async def _notify_admins(msg: Message, request_key: str, user_text: str) -> None:
    """Отправляет уведомление администраторам о новом обращении."""

    if not ADMINS:
        return

    user = msg.from_user
    if not user:
        return

    full_name = user.full_name or "Без имени"
    username_line = (
        f"Юзернейм: @{escape_md(user.username)}"
        if user.username
        else "Юзернейм: —"
    )
    lines = [
        f"🔔 {escape_md(_REQUEST_TITLES[request_key])}",
        f"Пользователь: [{escape_md(full_name)}](tg://user?id={user.id})",
        username_line,
        f"ID: {escape_md(str(user.id))}",
        "Сообщение:",
        escape_md(user_text),
    ]
    admin_message = "\n".join(lines)

    for admin_id in ADMINS:
        try:
            await msg.bot.send_message(
                admin_id,
                admin_message,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as exc:
            logger.warning("Не удалось уведомить администратора %s: %s", admin_id, exc)


def _extract_user_input(msg: Message) -> str:
    """Формирует текст обращения из сообщения пользователя."""

    if msg.text and msg.text.strip():
        return msg.text.strip()

    if msg.contact:
        parts: list[str] = []
        if msg.contact.phone_number:
            parts.append(f"Телефон: {msg.contact.phone_number}")
        name_bits = [msg.contact.first_name or "", msg.contact.last_name or ""]
        name = " ".join(part for part in name_bits if part).strip()
        if name:
            parts.append(f"Имя: {name}")
        if msg.contact.vcard:
            parts.append(f"VCard: {msg.contact.vcard}")
        return "\n".join(parts)

    if msg.caption and msg.caption.strip():
        return msg.caption.strip()

    return ""


@router.callback_query(F.data.in_(tuple(_REQUEST_TYPES.keys())))
async def start_support_request(cb: CallbackQuery, state: FSMContext):
    request_key = _REQUEST_TYPES[cb.data]
    await _start_request(cb, state, request_key)


@router.message(SupportRequestState.waiting_text)
async def handle_support_request(msg: Message, state: FSMContext):
    data = await state.get_data()
    request_key = data.get("request_type")
    if not request_key:
        await state.clear()
        return

    user_text = _extract_user_input(msg)
    if not user_text:
        await safe_answer(
            msg,
            "Пожалуйста, отправьте текстовое сообщение или контакт.",
            parse_mode="MarkdownV2",
        )
        return

    await _notify_admins(msg, request_key, user_text)

    user_id = msg.from_user.id if msg.from_user else 0
    await safe_answer(
        msg,
        _REQUEST_CONFIRMATIONS[request_key],
        reply_markup=main_menu(_is_admin(user_id)),
        parse_mode="MarkdownV2",
    )

    await state.clear()
