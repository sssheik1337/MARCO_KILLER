import asyncio
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    ContentType,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from middlewares.admin_filter import AdminOnly
from data.db_utils import get_setting, set_setting
from config import LOGIN_ADMIN, PASSWORD_ADMIN
from formatter import send_md_safe
from data.admins import is_superadmin
from structure.markdown import edit_md_safe, message_to_markdown, escape_user, send_md_safe_to_chat
from structure.keyboards import cancel_keyboard
from structure.ready_catalogs import ready_catalogs_manage_keyboard, ready_catalog_item_keyboard
from structure.states import AdminTextEditState, BroadcastState, ReadyCatalogState
from data.ready_catalogs import (
    add_ready_catalog,
    delete_ready_catalog,
    get_ready_catalog_by_id,
    get_ready_catalogs,
    update_ready_catalog_file,
    update_ready_catalog_title,
)
from services.notifications import send_bulk_message
from data.file_storage import ADMIN_IMPORT_KEYS

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
        "prompt": "Пришлите файл каталога тканей (XLSX).",
        "title": "каталог тканей",
        "setting_key": ADMIN_IMPORT_KEYS["fabrics_catalog"],
    },
    "hardware_catalog": {
        "prompt": "Пришлите файл каталога фурнитуры (XLSX).",
        "title": "каталог фурнитуры",
        "setting_key": ADMIN_IMPORT_KEYS["hardware_catalog"],
    },
    "stock_fabrics_msk": {
        "prompt": "Пришлите файл остатков тканей для Москвы (XLSX).",
        "title": "остатки тканей (Москва)",
        "setting_key": ADMIN_IMPORT_KEYS["stock_fabrics_msk"],
    },
    "stock_fabrics_spb": {
        "prompt": "Пришлите файл остатков тканей для Санкт-Петербурга (XLSX).",
        "title": "остатки тканей (СПБ)",
        "setting_key": ADMIN_IMPORT_KEYS["stock_fabrics_spb"],
    },
    "stock_hardware_msk": {
        "prompt": "Пришлите файл остатков фурнитуры для Москвы (XLSX).",
        "title": "остатки фурнитуры (Москва)",
        "setting_key": ADMIN_IMPORT_KEYS["stock_hardware_msk"],
    },
    "stock_hardware_spb": {
        "prompt": "Пришлите файл остатков фурнитуры для Санкт-Петербурга (XLSX).",
        "title": "остатки фурнитуры (СПБ)",
        "setting_key": ADMIN_IMPORT_KEYS["stock_hardware_spb"],
    },
}




def admin_kb(show_credentials: bool = False):
    rows = [
        [InlineKeyboardButton(text="📇 Править контакты", callback_data="admin:edit:contacts"),
         InlineKeyboardButton(text="🗺️ Адрес/маршрут", callback_data="admin:edit:address")],
        [InlineKeyboardButton(text="🕘 Режим работы", callback_data="admin:edit:worktime"),
         InlineKeyboardButton(text="📄 Реквизиты", callback_data="admin:edit:requisites")],
        [InlineKeyboardButton(text="📄 Каталог тканей", callback_data="admin:import:fabrics_catalog"),
         InlineKeyboardButton(text="📄 Каталог фурнитуры", callback_data="admin:import:hardware_catalog")],
        [InlineKeyboardButton(text="📄 Остатки тканей Москва", callback_data="admin:import:stock_fabrics_msk"),
         InlineKeyboardButton(text="📄 Остатки тканей СПБ", callback_data="admin:import:stock_fabrics_spb")],
        [InlineKeyboardButton(text="📄 Остатки фурнитуры Москва", callback_data="admin:import:stock_hardware_msk"),
         InlineKeyboardButton(text="📄 Остатки фурнитуры СПБ", callback_data="admin:import:stock_hardware_spb")],
        [InlineKeyboardButton(text="➕ Добавить каталог готовых изделий", callback_data="admin:ready:add")],
        [InlineKeyboardButton(text="✏️ Управление каталогами готовых изделий", callback_data="admin:ready:manage")],
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin:broadcast:start")],
        [InlineKeyboardButton(text="👤 Пользовательское меню", callback_data="menu:toggle_user")],
    ]
    if show_credentials:
        rows.insert(0, [InlineKeyboardButton(text="🔐 Данные для входа администратора", callback_data="admin:creds")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_prompt_kb(target: str) -> InlineKeyboardMarkup:
    """Формирует клавиатуру с кнопкой предпросмотра текущего текста."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Предпросмотр", callback_data=f"admin:preview:{target}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")],
        ]
    )


def edit_confirm_kb() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения сохранения текста."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить", callback_data="admin:edit:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin:edit:cancel"),
            ],
        ]
    )


def import_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для отмены ожидаемой загрузки файла."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:import:cancel")],
            [InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="admin:open")],
        ]
    )

def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения универсальной рассылки."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить всем", callback_data="admin:broadcast:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin:broadcast:cancel"),
            ],
            [InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="admin:open")],
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


@router.callback_query(F.data == "admin:broadcast:start")
async def broadcast_start(cb: CallbackQuery, state: FSMContext):
    """Запускает сценарий универсальной рассылки."""

    await state.clear()
    await state.set_state(BroadcastState.waiting_text)
    await send_md_safe(
        cb.message,
        "Введите текст рассылки (можно с MarkdownV2, эмодзи, переносами):",
        reply_markup=cancel_keyboard(),
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


@router.message(BroadcastState.waiting_text)
async def broadcast_text(msg: Message, state: FSMContext):
    """Сохраняет текст рассылки и запрашивает URL кнопки."""

    text = message_to_markdown(msg)
    if not text.strip():
        await send_md_safe(msg, "Текст не может быть пустым. Введите текст рассылки:")
        return

    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastState.waiting_url)
    await send_md_safe(msg, "Введите URL или \"-\" если кнопка не нужна:", reply_markup=cancel_keyboard())


@router.message(BroadcastState.waiting_url)
async def broadcast_url(msg: Message, state: FSMContext):
    """Готовит предпросмотр рассылки и запрашивает подтверждение."""

    url_text = (msg.text or msg.caption or "").strip()
    url_value = None if not url_text or url_text == "-" else url_text

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    if not text:
        await state.clear()
        await send_md_safe(msg, "Сценарий сброшен. Начните заново.", reply_markup=admin_kb())
        return

    await state.update_data(broadcast_url=url_value)
    await state.set_state(BroadcastState.waiting_confirm)

    button_markup = None
    if url_value:
        button_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Подробнее", url=url_value)]]
        )

    await send_md_safe(
        msg,
        text,
        reply_markup=button_markup,
    )
    await send_md_safe(
        msg,
        "Подтвердите отправку.",
        reply_markup=broadcast_confirm_keyboard(),
    )


async def _run_broadcast(bot, text: str, url: str | None, chat_id: int):
    """Фоновая отправка универсальной рассылки."""

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
        "Рассылка завершена:",
        f"✅ Доставлено: {delivered}",
        f"🚫 Заблокировано: {blocked}",
        f"⚠️ Ошибок: {failed}",
    ]
    await send_md_safe_to_chat(bot, chat_id, "\n".join(summary_lines))


@router.callback_query(F.data == "admin:broadcast:confirm")
async def broadcast_confirm(cb: CallbackQuery, state: FSMContext):
    """Запускает массовую рассылку."""

    current_state = await state.get_state()
    if current_state != BroadcastState.waiting_confirm.state:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    url_value = data.get("broadcast_url")
    if not text:
        await cb.answer("Нечего отправлять", show_alert=True)
        return

    await send_md_safe(cb.message, "Рассылка запущена, сообщим об итогах.")
    await state.clear()

    asyncio.create_task(_run_broadcast(cb.bot, text, url_value, cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "admin:broadcast:cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    """Отменяет рассылку и очищает состояние."""

    await state.clear()
    await send_md_safe(cb.message, "Рассылка отменена.", reply_markup=admin_kb())
    await cb.answer()


# простые текстовые поля (без JSON)
@router.callback_query(F.data.startswith("admin:edit:"))
async def ask_text(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[-1]
    pretty = _EDITABLE_SETTINGS.get(key)
    if not pretty:
        await cb.answer()
        return
    await set_setting("edit_target", key)
    prompt_lines = [
        f"Пришлите новый текст для «{pretty}». Поддерживается MarkdownV2.",
        "Используйте кнопку «👁 Предпросмотр», чтобы оценить форматирование.",
    ]
    await state.set_state(AdminTextEditState.waiting_text)
    await edit_md_safe(
        cb.message,
        "\n".join(prompt_lines),
        reply_markup=edit_prompt_kb(key),
    )
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

    await send_md_safe_to_chat(cb.message.bot, cb.message.chat.id, "Текущая версия:")
    await send_md_safe_to_chat(cb.message.bot, cb.message.chat.id, stored)
    await cb.answer()


@router.message(AdminTextEditState.waiting_text)
async def edit_text_input(msg: Message, state: FSMContext):
    """Сохраняет новый текст в состояние и показывает предпросмотр."""

    target = await get_setting("edit_target", "")
    if target not in _EDITABLE_SETTINGS:
        await state.clear()
        return

    new_text = message_to_markdown(msg)
    if not new_text.strip():
        await send_md_safe(msg, "Текст не может быть пустым. Введите новый текст:")
        return

    await state.update_data(edit_text=new_text)
    await state.set_state(AdminTextEditState.waiting_confirm)
    await send_md_safe(msg, "Предпросмотр:")
    await send_md_safe(msg, new_text)
    await send_md_safe(msg, "Сохранить изменения?", reply_markup=edit_confirm_kb())


@router.callback_query(F.data == "admin:edit:confirm")
async def edit_text_confirm(cb: CallbackQuery, state: FSMContext):
    """Подтверждает сохранение нового текста."""

    data = await state.get_data()
    new_text = data.get("edit_text", "")
    target = await get_setting("edit_target", "")
    if not new_text or target not in _EDITABLE_SETTINGS:
        await state.clear()
        await cb.answer("Нечего сохранять", show_alert=True)
        return

    await set_setting(target, new_text)
    await set_setting("edit_target", "")
    await state.clear()
    await send_md_safe(cb.message, "Готово ✅", reply_markup=admin_kb())
    await cb.answer()


@router.callback_query(F.data == "admin:edit:cancel")
async def edit_text_cancel(cb: CallbackQuery, state: FSMContext):
    """Отменяет редактирование текста."""

    await state.clear()
    await set_setting("edit_target", "")
    await send_md_safe(cb.message, "Редактирование отменено.", reply_markup=admin_kb())
    await cb.answer()

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

    file_name = msg.document.file_name or ""
    ext = Path(file_name).suffix.lower()
    if ext != ".xlsx":
        await msg.answer(
            "Ошибка: поддерживаются только файлы XLSX.",
            parse_mode=None,
        )
        await set_setting("import_target", "")
        return

    setting_key = target_config.get("setting_key")
    if not setting_key:
        await msg.answer("Не найден ключ хранения для выбранного импорта.", parse_mode=None)
        await set_setting("import_target", "")
        return

    await set_setting(setting_key, msg.document.file_id)
    await set_setting("import_target", "")
    await send_md_safe(
        msg,
        f"Файл «{escape_user(target_config['title'])}» сохранён.",
        reply_markup=admin_kb(),
    )
