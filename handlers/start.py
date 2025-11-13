import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from structure.keyboards import main_menu
from structure.markdown_utils import safe_answer
from structure.states import CityState
from aiogram.fsm.context import FSMContext

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CityState.choosing)
    await safe_answer(
        msg,
        "Добро пожаловать! Выберите город для каталога:",
        reply_markup=main_menu(),
        parse_mode="MarkdownV2",
    )
