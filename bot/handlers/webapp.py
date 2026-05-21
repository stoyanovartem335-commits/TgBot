"""Receives web_app_data and shows payment methods."""
from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import Message

from ..keyboards import payment_methods_kb

log = logging.getLogger(__name__)
router = Router(name="webapp")


@router.message(F.web_app_data)
async def on_webapp_data(message: Message) -> None:
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Bad web_app_data: %r", raw)
        await message.answer("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435. \u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u0432\u0438\u0442\u0440\u0438\u043d\u0443 \u0435\u0449\u0451 \u0440\u0430\u0437.")
        return

    plan_code = payload.get("plan")
    if not plan_code:
        await message.answer("\u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d \u0442\u0430\u0440\u0438\u0444. \u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u0432\u0438\u0442\u0440\u0438\u043d\u0443 \u0435\u0449\u0451 \u0440\u0430\u0437.")
        return

    plan_label = payload.get("label", plan_code)
    price_rub = payload.get("price_rub", 0)

    text = (
        "\u0412\u044b \u0432\u044b\u0431\u0440\u0430\u043b\u0438:\n\n"
        f"\U0001f4e6 <b>{plan_label}</b>\n"
        f"\U0001f4b0 \u0426\u0435\u043d\u0430: <b>{price_rub} \u20bd</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b:"
    )
    await message.answer(text, reply_markup=payment_methods_kb(plan_code))
