# handlers/menu.py
import logging
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from config import PAGE_SIZE, ADMINS
from structure.keyboards import (
    main_menu,
    pager,
    product_controls,
    empty_catalog_keyboard,
    cart_keyboard,
)
from structure.markdown_utils import safe_send, safe_edit
from structure.formatter import escape_md
from structure.states import SupportRequestState
from services.pagination import slice_page
from services import cart, view_filters
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


# --- корзина: вспомогательные функции ---


def _format_money(value: float | None) -> str:
    """Форматирует стоимость для отображения пользователю."""

    if value is None:
        return "—"
    return f"{value:.2f} ₽"


def _resolve_cart_price(product: dict, rng: str) -> float | None:
    """Определяет цену товара для расчёта корзины."""

    section = product.get("section")
    if section == "fabrics":
        price = product.get(f"price_piece_{rng}")
        if price is None:
            price = product.get(f"price_roll_{rng}")
    else:
        price = product.get("price_opt")
        if price is None:
            price = product.get("price_rrc")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


async def _build_cart_summary(user_id: int) -> tuple[list[dict], float, bool, str]:
    """Собирает информацию о корзине для отображения и отправки админам."""

    items_raw = cart.items(user_id)
    if not items_raw:
        return [], 0.0, False, ""

    rng, usd = await current_range()
    label = range_label(rng, usd)

    items: list[dict] = []
    total = 0.0
    has_priced = False

    for pid, qty in items_raw.items():
        product = await db_utils.fetch_product(pid)
        if not product:
            logger.warning("Товар %s не найден при построении корзины", pid)
            continue

        price = _resolve_cart_price(product, rng)
        line_total = price * qty if price is not None else None
        if line_total is not None:
            total += line_total
            has_priced = True

        items.append(
            {
                "id": pid,
                "name": product.get("name") or f"ID {pid}",
                "qty": qty,
                "line_total": line_total,
            }
        )

    return items, total, has_priced, label


def _render_cart_text(items: list[dict], total: float, has_priced: bool, label: str) -> str:
    """Строит текст корзины для пользователя."""

    if not items:
        return "Корзина пуста"

    lines = [
        f"{_mdv2(item['name'])} × {item['qty']} = {_mdv2(_format_money(item['line_total']))}"
        for item in items
    ]
    total_line = _format_money(total) if has_priced else "—"
    lines.append(f"*Итого:* {_mdv2(total_line)}")
    if label:
        lines.append(_mdv2(label))
    return "\n".join(lines)


def _render_cart_admin_text(
    source: CallbackQuery | Message,
    items: list[dict],
    total: float,
    has_priced: bool,
    label: str,
) -> str:
    """Формирует сообщение для администраторов о содержимом корзины."""

    if not items:
        return ""

    from_user = source.from_user if source.from_user else None
    if not from_user:
        return ""

    full_name = from_user.full_name or "Без имени"
    header = [
        "🧺 Новая заявка из корзины",
        f"Имя: {escape_md(full_name)}",
    ]
    if from_user.username:
        header.append(f"Юзернейм: @{escape_md(from_user.username)}")

    body = [
        f"- {escape_md(item['name'])} × {item['qty']} = {escape_md(_format_money(item['line_total']))} (ID: {item['id']})"
        for item in items
    ]
    total_line = _format_money(total) if has_priced else "—"
    footer = [f"Итого: {escape_md(total_line)}"]
    if label:
        footer.append(escape_md(label))

    return "\n".join(header + ["Позиции:"] + body + footer)


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
    await safe_send(
        cb.message,
        "Главное меню:",
        reply_markup=main_menu(_is_admin(cb.from_user.id)),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


# --- каталог: разделы → категории → товары ---

@router.callback_query(F.data == "menu:catalog")
async def catalog_root(cb: CallbackQuery):
    user_id = cb.from_user.id
    only_available = view_filters.is_in_stock(user_id)
    sections = await db_utils.fetch_sections(only_available=only_available)
    if not sections:
        if only_available:
            await safe_send(
                cb.message,
                "Сейчас нет товаров в наличии. Вы можете отключить фильтр «В наличии» в главном меню.",
                reply_markup=main_menu(_is_admin(user_id)),
            )
        else:
            await safe_send(
                cb.message,
                "Каталог пуст: загрузите XLSX тканей и фурнитуры",
                reply_markup=empty_catalog_keyboard(_is_admin(user_id)),
            )
        await cb.answer()
        return

    # пагинация разделов
    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, 1, PAGE_SIZE)

    rng, usd = await current_range()
    label = range_label(rng, usd)  # «Курс: 91.05 ₽ → 90–95»
    if only_available:
        label = f"{label}\n\nПоказываются только товары в наличии."

    prefix = "secstock" if only_available else "sec"

    await safe_send(
        cb.message,
        label,
        reply_markup=pager(prefix, page_items, page, total),
    )
    await cb.answer()


@router.callback_query(F.data == "menu:stock")
async def toggle_in_stock_filter(cb: CallbackQuery):
    """Переключает режим показа только товаров в наличии."""

    user_id = cb.from_user.id
    enabled = view_filters.toggle_in_stock(user_id)
    text = (
        "Фильтр «В наличии» включён. Каталог и прайс теперь показывают только доступные позиции."
        if enabled
        else "Фильтр «В наличии» отключён. Каталог и прайс снова показывают весь ассортимент."
    )
    await safe_send(
        cb.message,
        text,
        reply_markup=main_menu(_is_admin(user_id)),
    )
    await cb.answer("Фильтр включён" if enabled else "Фильтр отключён")


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
        await safe_send(
            cb.message,
            "Здесь пока пусто.",
            parse_mode="MarkdownV2",
        )
        await cb.answer()
        return
    items = [(c, c) for c in cats]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    cat_prefix = "catstock" if only_available else "cat"
    await safe_send(
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
    await safe_send(
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
    course_line = None
    if p["section"] == "fabrics":
        piece = p.get(f"price_piece_{rng}")
        roll = p.get(f"price_roll_{rng}")
        price_line = f"Отрез: {piece or '-'} · Ролик: {roll or '-'}"
        course_line = f"💵 {lbl}"
    else:
        price_line = f"РРЦ: {p.get('price_rrc') or '-'} · Опт: {p.get('price_opt') or '-'}"

    qty = cart.get_qty(cb.from_user.id, pid) or 1

    lines = [
        f"*{_mdv2(p.get('name'))}*",
        f"Артикул: {_mdv2(p.get('article'))}",
        f"{_mdv2(price_line)}",
    ]
    if course_line:
        lines.append(_mdv2(course_line))
    lines.append(f"Наличие: {p.get('in_stock') or 0}")
    if not course_line:
        lines.append(_mdv2(lbl))

    caption = "\n".join(lines)

    if p.get("image_url"):
        await cb.message.answer_photo(
            p["image_url"], caption=caption, parse_mode="MarkdownV2",
            reply_markup=product_controls(pid, qty)
        )
    else:
        await safe_send(
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
    items, total, has_priced, label = await _build_cart_summary(cb.from_user.id)
    text = _render_cart_text(items, total, has_priced, label)
    await safe_send(
        cb.message,
        text,
        reply_markup=cart_keyboard(bool(items)),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data == "cart:clear")
async def clear_cart(cb: CallbackQuery):
    cart.clear(cb.from_user.id)
    await safe_edit(
        cb.message,
        "Корзина пуста",
        reply_markup=cart_keyboard(False),
        parse_mode="MarkdownV2",
    )
    await cb.answer("Корзина очищена")


@router.callback_query(F.data == "cart:checkout")
async def checkout_cart(cb: CallbackQuery):
    items, total, has_priced, label = await _build_cart_summary(cb.from_user.id)
    if not items:
        await cb.answer("Корзина пуста", show_alert=True)
        return

    admin_text = _render_cart_admin_text(cb, items, total, has_priced, label)
    if admin_text and ADMINS:
        for admin_id in ADMINS:
            try:
                await cb.message.bot.send_message(
                    admin_id,
                    admin_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception as exc:
                logger.warning(
                    "Не удалось отправить корзину админу %s: %s", admin_id, exc
                )

    cart.clear(cb.from_user.id)

    await safe_edit(
        cb.message,
        "Заявка по корзине отправлена. Корзина очищена.",
        reply_markup=cart_keyboard(False),
        parse_mode="MarkdownV2",
    )
    await cb.answer("Отправлено")


@router.callback_query(F.data == "menu:price")
async def show_price(cb: CallbackQuery):
    """Прайс идёт по тому же пути, что и каталог: разделы → категории → товары."""

    user_id = cb.from_user.id
    only_available = view_filters.is_in_stock(user_id)
    sections = await db_utils.fetch_sections(only_available=only_available)
    if not sections:
        if only_available:
            await safe_send(
                cb.message,
                "Сейчас нет товаров в наличии. Вы можете отключить фильтр «В наличии» в главном меню.",
                reply_markup=main_menu(_is_admin(user_id)),
            )
        else:
            await safe_send(
                cb.message,
                "Каталог пуст: загрузите XLSX тканей и фурнитуры",
                reply_markup=empty_catalog_keyboard(_is_admin(user_id)),
            )
        await cb.answer()
        return

    labeled = _label_sections(sections)
    page_items, page, total = slice_page(labeled, 1, PAGE_SIZE)

    rng, usd = await current_range()
    label = range_label(rng, usd)
    if only_available:
        label = f"{label}\n\nПоказываются только товары в наличии."

    prefix = "secstock" if only_available else "sec"

    await safe_send(
        cb.message,
        label,
        reply_markup=pager(prefix, page_items, page, total),
    )
    await cb.answer()


# --- информационные страницы ---

async def _send_setting_text(target: Message, user_id: int, key: str, empty_text: str) -> None:
    """Отправляет пользователю текст из настроек или запасной вариант."""

    stored = await db_utils.get_setting(key, "")
    text = stored or empty_text
    await safe_send(
        target,
        text,
        reply_markup=main_menu(_is_admin(user_id)),
    )


_INFO_COMMANDS = {
    "📇 Контакты": ("contacts", "Контакты пока не заполнены."),
    "🗺️ Как проехать": ("address", "Адрес пока не указан."),
    "📄 Реквизиты": ("requisites", "Реквизиты пока не добавлены."),
}


@router.callback_query(F.data == "menu:contacts")
async def show_contacts(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "contacts",
            "Контакты пока не заполнены.",
        )
    await cb.answer()


@router.callback_query(F.data == "menu:route")
async def show_route(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "address",
            "Адрес пока не указан.",
        )
    await cb.answer()


@router.callback_query(F.data == "menu:requisites")
async def show_requisites(cb: CallbackQuery):
    if cb.message:
        await _send_setting_text(
            cb.message,
            cb.from_user.id,
            "requisites",
            "Реквизиты пока не добавлены.",
        )
    await cb.answer()


@router.message(F.text.in_(tuple(_INFO_COMMANDS.keys())))
async def show_info_message(msg: Message):
    """Обрабатывает текстовые запросы на контакты, адрес и реквизиты."""

    if not msg.from_user:
        return

    key, fallback = _INFO_COMMANDS[msg.text]
    await _send_setting_text(msg, msg.from_user.id, key, fallback)



# --- обращения пользователей ---

async def _start_request(cb: CallbackQuery, state: FSMContext, request_key: str) -> None:
    """Подготавливает сбор данных для выбранного обращения."""

    await state.set_state(SupportRequestState.waiting_text)
    await state.update_data(request_type=request_key)
    await safe_send(
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
    lines = [
        f"🔔 {escape_md(_REQUEST_TITLES[request_key])}",
        f"Имя: {escape_md(full_name)}",
    ]
    if user.username:
        lines.append(f"Юзернейм: @{escape_md(user.username)}")
    lines.extend(
        [
            "Сообщение:",
            escape_md(user_text),
        ]
    )
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
        await safe_send(
            msg,
            "Пожалуйста, отправьте текстовое сообщение или контакт.",
            parse_mode="MarkdownV2",
        )
        return

    await _notify_admins(msg, request_key, user_text)

    user_id = msg.from_user.id if msg.from_user else 0
    await safe_send(
        msg,
        _REQUEST_CONFIRMATIONS[request_key],
        reply_markup=main_menu(_is_admin(user_id)),
        parse_mode="MarkdownV2",
    )

    await state.clear()
