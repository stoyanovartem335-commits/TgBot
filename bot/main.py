from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonDefault

from .config import BOT_TOKEN
from .database import close_db, init_db
from .handlers import admin, gsheets, menu, requisites, stars, start, triboote, webapp
from .services import api_client
from .webhook_server import start_web_server


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _handle_asyncio_exception(loop, context):
    msg = context.get("exception", context["message"])
    logging.getLogger(__name__).error("Unhandled asyncio exception: %s", msg)


async def setup_bot_ui(bot: Bot) -> None:
    log = logging.getLogger(__name__)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="menu", description="Показать меню"),
            BotCommand(command="adm", description="Админ-панель"),
        ])
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception:
        log.exception("Failed to setup Telegram menu button")


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_handle_asyncio_exception)

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        start.router,
        menu.router,
        webapp.router,
        stars.router,
        triboote.router,
        requisites.router,
        admin.router,
        gsheets.router,
    )

    await setup_bot_ui(bot)
    runner = await start_web_server(bot)
    log.info("Service started. Bot polling beginning.")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await api_client.close_session()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        logging.getLogger(__name__).critical("Fatal startup error: %s", exc, exc_info=True)
        sys.exit(1)
