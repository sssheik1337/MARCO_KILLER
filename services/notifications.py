"""Утилиты для рассылки уведомлений пользователям."""

import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from data.db_utils import get_active_user_ids, mark_user_blocked
from structure.markdown import MarkdownV2Escaper


def build_product_card(source: str, product: dict) -> str:
    """Формирует текст карточки товара для рассылки."""

    escape = MarkdownV2Escaper.escape_plain

    name = escape(product.get("name") or "Без названия")
    article = escape(product.get("article") or "—")
    collection = escape(product.get("collection") or product.get("fabric_type") or "—")
    status = escape(product.get("status") or product.get("special_status") or "")

    lines = [
        f"Источник: {'Фурнитура' if source == 'hardware' else 'Ткани'}",
        f"Артикул: {article}",
        f"Название: {name}",
        f"Коллекция: {collection}",
    ]

    if status:
        lines.append(f"Статус: {status}")

    if source == "hardware":
        currency = escape(product.get("currency") or "")
        price_rrc = product.get("price_rrc")
        price_opt = product.get("price_opt")
        if price_rrc is not None:
            lines.append(f"РРЦ: {price_rrc} {currency}".rstrip())
        if price_opt is not None:
            lines.append(f"Оптовая: {price_opt} {currency}".rstrip())
    else:
        price_pairs = [
            ("Оптовая от ролика", product.get("wholesale_roll")),
            ("Оптовая в отрез", product.get("wholesale_piece")),
            ("Ролик 85-90", product.get("price_roll_85_90")),
            ("Отрез 85-90", product.get("price_piece_85_90")),
            ("Ролик 90-95", product.get("price_roll_90_95")),
            ("Отрез 90-95", product.get("price_piece_90_95")),
            ("Ролик 95-100", product.get("price_roll_95_100")),
            ("Отрез 95-100", product.get("price_piece_95_100")),
        ]
        for title, value in price_pairs:
            if value is not None:
                lines.append(f"{title}: {value}")

    return "\n".join(lines)


async def broadcast(bot: Bot, text: str) -> tuple[int, int]:
    """Рассылает сообщение всем пользователям и ведёт учёт ошибок."""

    escaped = MarkdownV2Escaper.escape_preserving(text)
    delivered, blocked, failed = await send_bulk_message(
        bot,
        escaped,
        parse_mode="MarkdownV2",
    )
    return delivered, blocked + failed


async def send_bulk_message(
    bot: Bot,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_web_page_preview: bool | None = None,
    throttle_delay: float = 0.05,
) -> tuple[int, int, int]:
    """Отправляет сообщение всем активным пользователям."""

    recipients = await get_active_user_ids()
    delivered = 0
    blocked = 0
    failed = 0

    for tg_id in recipients:
        try:
            await bot.send_message(
                tg_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
            delivered += 1
        except TelegramForbiddenError:
            blocked += 1
            await mark_user_blocked(tg_id)
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "chat not found" in lowered or "blocked by the user" in lowered:
                blocked += 1
                await mark_user_blocked(tg_id)
            else:
                failed += 1
                logging.warning("Не удалось отправить уведомление %s: %s", tg_id, exc)
        except Exception as exc:  # pragma: no cover - сетевые ошибки
            failed += 1
            logging.warning("Сбой отправки уведомления %s: %s", tg_id, exc)
        if throttle_delay > 0:
            await asyncio.sleep(throttle_delay)

    return delivered, blocked, failed
