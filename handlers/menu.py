# handlers/menu.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from config import PAGE_SIZE, ADMINS
from structure.keyboards import main_menu, pager, product_controls, empty_catalog_keyboard
from structure.markdown_utils import safe_answer
from services.pagination import slice_page
from services import cart
from data import db_utils
from services.exchange import current_range, range_label

router = Router()


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
    labeled = [("🧵 Ткани" if s == "fabrics" else "🔩 Фурнитура", s) for s in sections]
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


@router.callback_query(F.data.startswith("sec:page:"))
async def catalog_sections_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[-1])
    sections = await db_utils.fetch_sections()
    labeled = [("🧵 Ткани" if s == "fabrics" else "🔩 Фурнитура", s) for s in sections]
    page_items, page, total = slice_page(labeled, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(reply_markup=pager("sec", page_items, page, total))
    await cb.answer()


@router.callback_query(F.data.startswith("sec:open:"))
async def open_section(cb: CallbackQuery):
    section = cb.data.split(":")[-1]                          # 'fabrics' | 'hardware'
    cats = await db_utils.fetch_categories(section)
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
    await safe_answer(
        cb.message,
        "Категории:",
        reply_markup=pager(f"cat:{section}", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cat:") & F.data.contains(":page:"))
async def open_category_page(cb: CallbackQuery):
    # формат: cat:{section}:page:{N}
    _, section, _, s_page = cb.data.split(":")
    page = int(s_page)
    cats = await db_utils.fetch_categories(section)
    items = [(c, c) for c in cats]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(reply_markup=pager(f"cat:{section}", page_items, page, total))
    await cb.answer()


@router.callback_query(F.data.startswith("cat:") & F.data.contains(":open:"))
async def open_category(cb: CallbackQuery):
    # формат: cat:{section}:open:{category}
    _, section, _, category = cb.data.split(":")
    prods = await db_utils.fetch_products_by_category(section, category)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, 1, PAGE_SIZE)
    await safe_answer(
        cb.message,
        category,
        reply_markup=pager(f"prodlist:{section}:{category}", page_items, page, total),
        parse_mode="MarkdownV2",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("prodlist:") & F.data.contains(":page:"))
async def product_list_page(cb: CallbackQuery):
    # формат: prodlist:{section}:{category}:page:{N}
    _, section, category, _, s_page = cb.data.split(":")
    page = int(s_page)
    prods = await db_utils.fetch_products_by_category(section, category)
    items = [(name, str(pid)) for pid, name in prods]
    page_items, page, total = slice_page(items, page, PAGE_SIZE)
    await cb.message.edit_reply_markup(
        reply_markup=pager(f"prodlist:{section}:{category}", page_items, page, total)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("prodlist:") & F.data.contains(":open:"))
async def product_card(cb: CallbackQuery):
    # формат: prodlist:{section}:{category}:open:{product_id}
    pid = int(cb.data.split(":")[-1])
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

    labeled = [("🧵 Ткани" if s == "fabrics" else "🔩 Фурнитура", s) for s in sections]
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
