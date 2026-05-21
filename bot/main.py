"""Bot entrypoint: starts aiogram dispatcher + aiohttp web server."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN
from .database import init_db
from .handlers import admin, gsheets, menu, requisites, stars, start, triboote, webapp
from .webhook_server import start_web_server


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


async def main() -> None:
    setup_logging()
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

    runner = await start_web_server(bot)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
