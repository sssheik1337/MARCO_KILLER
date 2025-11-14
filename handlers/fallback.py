"""Обработчики по умолчанию для нераспознанных событий."""
import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message

from config import ADMINS
from structure.keyboards import main_menu
from structure.markdown_utils import safe_answer
from structure.formatter import escape_md

router = Router()
logger = logging.getLogger(__name__)


def _is_admin(user_id: int | None) -> bool:
    """Проверяет, является ли пользователь администратором."""

    return bool(user_id and user_id in ADMINS)


@router.message()
async def catch_all_message(message: Message) -> None:
    """Логирует и обрабатывает неизвестные сообщения."""

    user_id = message.from_user.id if message.from_user else None
    description = message.text or f"тип: {message.content_type}" if message.content_type else "без текста"
    logger.warning(
        "Получено необработанное сообщение от %s: %s", user_id or "неизвестно", description
    )
    response_text = "Кнопка недоступна, попробуйте ещё раз"
    await safe_answer(
        message,
        response_text,
        reply_markup=main_menu(_is_admin(user_id)),
    )


@router.callback_query()
async def catch_all_callback(callback: CallbackQuery) -> None:
    """Логирует и обрабатывает неизвестные callback-запросы."""

    user_id = callback.from_user.id if callback.from_user else None
    logger.warning(
        "Получен необработанный callback от %s: %s",
        user_id or "неизвестно",
        callback.data or "без данных",
    )
    response_text = "Кнопка недоступна, попробуйте ещё раз"
    await callback.answer()
    if callback.message:
        await safe_answer(
            callback.message,
            response_text,
            reply_markup=main_menu(_is_admin(user_id)),
        )
    elif user_id:
        await callback.bot.send_message(
            user_id,
            escape_md(response_text),
            reply_markup=main_menu(_is_admin(user_id)),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
