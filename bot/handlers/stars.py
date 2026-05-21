"""Telegram Stars (XTR) payment flow."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ..database import get_settings
from ..services.delivery import deliver_purchase

log = logging.getLogger(__name__)
router = Router(name="stars")


@router.callback_query(F.data.startswith("pay:stars:"))
async def on_pay_stars(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None:
        return

    settings = await get_settings()
    prices_stars = settings.get("prices_stars", {})
    prices_rub = settings.get("prices_rub", {})

    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
    plan_days = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}

    stars_price = prices_stars.get(plan_code, 0)
    rub_price = prices_rub.get(plan_code, 0)
    label = plan_labels.get(plan_code, plan_code)
    days = plan_days.get(plan_code)

    if stars_price <= 0:
        await call.answer("\u0422\u0430\u0440\u0438\u0444 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    await call.answer()
    await call.message.answer_invoice(
        title=f"\u0422\u0430\u0431\u043b\u0438\u0446\u0430 \u043f\u0435\u0440\u0435\u043f\u0440\u043e\u0434\u0430\u0436 \u2014 {label}",
        description=f"\u0414\u043e\u0441\u0442\u0443\u043f \u043a \u0422\u0430\u0431\u043b\u0438\u0446\u0435 \u043f\u0435\u0440\u0435\u043f\u0440\u043e\u0434\u0430\u0436, \u0442\u0430\u0440\u0438\u0444 \u00ab{label}\u00bb.",
        payload=f"stars:{plan_code}",
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=stars_price)],
        provider_token="",
    )


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if sp is None or message.from_user is None:
        return

    payload = sp.invoice_payload or ""
    if not payload.startswith("stars:"):
        return
    plan_code = payload.split(":", 1)[1]

    settings = await get_settings()
    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
    plan_days = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}

    await deliver_purchase(
        message.bot,
        user_id=message.from_user.id,
        username=message.from_user.username,
        plan_code=plan_code,
        plan_label=plan_labels.get(plan_code, plan_code),
        days=plan_days.get(plan_code),
        payment_method="stars",
    )
