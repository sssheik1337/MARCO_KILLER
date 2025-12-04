import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, LOG_LEVEL
from handlers import start as start_handlers
from handlers import menu as menu_handlers
from handlers import admin as admin_handlers
from handlers import fallback as fallback_handlers
from data.db_utils import init_db
from middlewares.user_registry import UserRegistry

async def main() -> None:
    logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(UserRegistry())
    dp.callback_query.middleware(UserRegistry())

    try:
        await init_db()  # создаём таблицы, если их нет
    except Exception as exc:
        logging.exception("Не удалось инициализировать базу данных: %s", exc)
        return

    dp.include_router(start_handlers.router)
    dp.include_router(menu_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(fallback_handlers.router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
