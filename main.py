import asyncio
import logging
from aiohttp import ClientConnectorError
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config import BOT_TOKEN, LOG_LEVEL, TELEGRAM_SOCKS5_PROXY
from handlers import start as start_handlers
from handlers import menu as menu_handlers
from handlers import stock as stock_handlers
from handlers import admin as admin_handlers
from handlers import fallback as fallback_handlers
from data.db_init import init_db
from middlewares.user_registry import UserRegistry

def create_session(proxy: str | None) -> AiohttpSession:
    """Создаёт HTTP-сессию с заданным SOCKS5-прокси."""

    return AiohttpSession(proxy=proxy or None, timeout=90)


async def create_bot(token: str) -> Bot | None:
    """Создаёт экземпляр бота с fallback с SOCKS5 на прямое подключение."""

    proxy_url = TELEGRAM_SOCKS5_PROXY or None
    attempts = [proxy_url] if proxy_url else []
    attempts.append(None)

    for proxy in attempts:
        session: AiohttpSession | None = None
        try:
            session = create_session(proxy)
            bot = Bot(
                token,
                session=session,
                default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
                request_timeout=60,
            )
            await bot.get_me()
            if proxy:
                logging.info("[BOT] запущен через SOCKS5")
            else:
                logging.info("[BOT] запущен без прокси")
            return bot
        except Exception as exc:  # noqa: BLE001
            logging.warning("[BOT] не удалось запустить с proxy=%s: %s", proxy or "direct", exc)
            if session:
                try:
                    await session.close()
                except Exception:  # noqa: BLE001
                    logging.debug("[BOT] не удалось корректно закрыть сессию после ошибки")

    logging.error("[BOT] не удалось инициализировать бота ни с прокси, ни напрямую")
    return None


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        filename="bot_debug.log",
        filemode="a",
    )
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    logging.getLogger("").addHandler(console)
    # Отключаем детальный вывод для aiosqlite, чтобы не засорять логи
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    bot = await create_bot(BOT_TOKEN)
    if bot is None:
        return

    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(UserRegistry())
    dp.callback_query.middleware(UserRegistry())

    try:
        await init_db()  # создаём таблицы, если их нет
    except Exception as exc:  # noqa: BLE001
        logging.exception("Не удалось инициализировать базу данных: %s", exc)
        await bot.session.close()
        return

    dp.include_router(start_handlers.router)
    dp.include_router(menu_handlers.router)
    dp.include_router(stock_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(fallback_handlers.router)

    # Устанавливаем описание команды /start, чтобы кнопка меню отображалась рядом с полем ввода
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])

    try:
        await dp.start_polling(bot)
    except (TelegramNetworkError, ClientConnectorError, TimeoutError) as exc:  # noqa: PERF203
        logging.exception("Сетевое исключение при работе бота: %s", exc)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
