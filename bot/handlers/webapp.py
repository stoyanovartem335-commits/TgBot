from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import Message

from ..keyboards import payment_methods_kb
from ..services.payment_flow import selected_plan_text
from ..services.settings_service import get_plans_from_settings

log = logging.getLogger(__name__)
router = Router(name="webapp")


@router.message(F.web_app_data)
async def on_webapp_data(message: Message) -> None:
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Bad web_app_data: %r", raw)
        await message.answer("Не удалось разобрать данные. Откройте витрину ещё раз.")
        return

    plan_code = payload.get("plan")
    if not plan_code:
        await message.answer("Не выбран тариф. Откройте витрину ещё раз.")
        return

    plans = await get_plans_from_settings()
    plan = next((item for item in plans if item["code"] == plan_code), None)
    plan_label = plan["label"] if plan else payload.get("label", plan_code)
    price_rub = plan["discounted_price_rub"] if plan else payload.get("price_rub", 0)
    price_stars = plan["discounted_price_stars"] if plan else payload.get("price_stars", 0)

    await message.answer(
        selected_plan_text(plan_label, price_rub, price_stars, "💰"),
        reply_markup=payment_methods_kb(plan_code),
    )
