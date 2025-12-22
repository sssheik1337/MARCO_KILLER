import logging
import os
import sqlite3
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
    fetch_active_users,
    find_catalog_product_by_article,
    find_product_by_code,
    get_setting,
    mark_user_blocked,
    set_setting,
)
from data import importer
from data.importer import ImportErrorFriendly, ParsedResult
import aiosqlite
from config import DB_PATH
from formatter import escape_md, send_md_safe
from structure.markdown import edit_md_safe, message_to_markdown, escape_user, send_md_safe_to_chat
from structure.keyboards import usd_keyboard, import_result_keyboard, cancel_keyboard
from structure.ready_catalogs import ready_catalogs_manage_keyboard, ready_catalog_item_keyboard
from structure.states import BroadcastState, ReadyCatalogState
from data.ready_catalogs import (
    add_ready_catalog,
    delete_ready_catalog,
    get_ready_catalog_by_id,
    get_ready_catalogs,
    update_ready_catalog_file,
    update_ready_catalog_title,
)
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
        [InlineKeyboardButton(text="Публикация акции / новинки / распродажи", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💵 Курс USD: авто/ручной", callback_data="admin:usd")],
    ]
    if show_credentials:
        rows.insert(0, [InlineKeyboardButton(text="🔐 Данные для входа администратора", callback_data="admin:creds")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def import_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для отмены ожидаемой загрузки файла."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:import:cancel")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


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
