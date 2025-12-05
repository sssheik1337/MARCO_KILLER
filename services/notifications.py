"""Утилиты для рассылки уведомлений пользователям."""

import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from data.db_utils import fetch_active_users, mark_user_blocked
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

    recipients = await fetch_active_users()
    sent = 0
    failed = 0

    for tg_id in recipients:
        try:
            escaped = MarkdownV2Escaper.escape_preserving(text)
            await bot.send_message(tg_id, escaped)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            await mark_user_blocked(tg_id)
        except TelegramBadRequest as exc:
            failed += 1
            logging.warning("Не удалось отправить уведомление %s: %s", tg_id, exc)
        except Exception as exc:  # pragma: no cover - сетевые ошибки
            failed += 1
            logging.warning("Сбой отправки уведомления %s: %s", tg_id, exc)

    return sent, failed
