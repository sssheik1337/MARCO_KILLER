import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from config import ADMINS
from structure.keyboards import main_menu
from structure.markdown_utils import safe_answer
from structure.states import CityState

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CityState.choosing)
    is_admin = bool(msg.from_user and msg.from_user.id in ADMINS)
    await safe_answer(
        msg,
        "Добро пожаловать! Выберите город для каталога:",
        reply_markup=main_menu(is_admin),
        parse_mode="MarkdownV2",
    )
