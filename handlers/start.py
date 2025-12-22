import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from config import LOGIN_ADMIN, PASSWORD_ADMIN
from structure.keyboards import main_menu_with_link
from structure.markdown import send_md_safe
from structure.states import GetAdminState
from data.admins import is_admin, add_admin_user

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    is_admin_user = await is_admin(msg.from_user.id if msg.from_user else 0)
    menu_markup = await main_menu_with_link(is_admin_user)
    await send_md_safe(
        msg,
        "Добро пожаловать! Выберите нужный раздел:",
        reply_markup=menu_markup,
    )


@router.message(F.text == "/getadmin")
async def cmd_getadmin(msg: Message, state: FSMContext):
    """Скрытая команда для авторизации администратора."""

    user_id = msg.from_user.id if msg.from_user else 0
    if await is_admin(user_id):
        await send_md_safe(msg, "Вы уже являетесь администратором.")
        return

    await state.set_state(GetAdminState.waiting_login)
    await send_md_safe(msg, "Введите логин администратора:")


@router.message(GetAdminState.waiting_login)
async def admin_login(msg: Message, state: FSMContext):
    login = (msg.text or "").strip()
    await state.update_data(admin_login=login)
    await state.set_state(GetAdminState.waiting_password)
    await send_md_safe(msg, "Введите пароль администратора:")


@router.message(GetAdminState.waiting_password)
async def admin_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    login = data.get("admin_login", "")
    password = (msg.text or "").strip()

    if login == LOGIN_ADMIN and password == PASSWORD_ADMIN and login and password:
        await add_admin_user(msg.from_user.id)
        await state.clear()
        await send_md_safe(msg, "Доступ администратора предоставлен ✅")
    else:
        await state.clear()
        await send_md_safe(msg, "Неверный логин или пароль ❌")
