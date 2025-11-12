import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, LOG_LEVEL
from handlers import start as start_handlers
from handlers import menu as menu_handlers
from handlers import admin as admin_handlers
from data.db_utils import init_db

async def main() -> None:
    logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    await init_db()  # создаём таблицы, если их нет

    dp.include_router(start_handlers.router)
    dp.include_router(menu_handlers.router)
    dp.include_router(admin_handlers.router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())