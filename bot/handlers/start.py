from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from ..keyboards import main_menu_kb, payment_methods_kb
from ..services.delivery import send_pending_purchase_deliveries
from ..services.payment_flow import selected_plan_text
from ..services.settings_service import get_plans_from_settings, get_active_discount, apply_discount

router = Router(name="start")

WELCOME = (
    "👋 <b>Добро пожаловать!</b>\n\n"
    "Это бот для получения доступа к <b>Таблице Калывана</b> — инструменту для перепродаж на Arizona RP.\n\n"
    "Меню:\n"
    "• 📋 <b>Ознакомиться/купить скрипт</b> — открыть витрину и выбрать тариф\n"
    "• 📰 <b>Новости Рынка</b> — наш Telegram-канал\n"
    "• 💬 <b>Тех поддержка</b> — связаться с админом"
)


async def _send_pending_deliveries(message: Message) -> None:
    if message.from_user is not None:
        await send_pending_purchase_deliveries(message.bot, message.from_user.id)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    args = command.args
    if args and args.startswith("buy_"):
        plan_code = args[4:]
        plans = await get_plans_from_settings()
        plan = next((p for p in plans if p["code"] == plan_code), None)
        if plan:
            discount_enabled, discount_pct = await get_active_discount()
            price_rub = plan["price_rub"]
            price_stars = plan["price_stars"]
            if discount_enabled and discount_pct > 0:
                price_rub = apply_discount(price_rub, discount_pct)
                price_stars = apply_discount(price_stars, discount_pct)

            await message.answer(
                selected_plan_text(plan["label"], price_rub, price_stars),
                reply_markup=payment_methods_kb(plan_code),
            )
            await _send_pending_deliveries(message)
            return

    await message.answer(WELCOME, reply_markup=main_menu_kb())
    await _send_pending_deliveries(message)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=main_menu_kb())
    await _send_pending_deliveries(message)
