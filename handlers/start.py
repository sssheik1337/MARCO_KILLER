import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from config import ADMINS
from structure.keyboards import main_menu_with_link
from structure.markdown import send_md_safe

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    is_admin = bool(msg.from_user and msg.from_user.id in ADMINS)
    menu_markup = await main_menu_with_link(is_admin)
    await send_md_safe(
        msg,
        "Добро пожаловать! Выберите нужный раздел:",
        reply_markup=menu_markup,
    )
