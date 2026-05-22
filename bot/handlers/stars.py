from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ..database import get_settings
from ..services.delivery import deliver_purchase
from ..services.settings_service import price_with_active_discount

log = logging.getLogger(__name__)
router = Router(name="stars")

PLAN_LABELS = {"1m": "1 месяц", "2m": "2 месяца", "3m": "3 месяца", "6m": "6 месяцев", "forever": "Forever"}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}


@router.callback_query(F.data.startswith("pay:stars:"))
async def on_pay_stars(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None:
        return

    settings = await get_settings()
    prices_stars = settings.get("prices_stars", {})

    stars_price = await price_with_active_discount(prices_stars.get(plan_code, 0))
    label = PLAN_LABELS.get(plan_code, plan_code)

    if stars_price <= 0:
        await call.answer("Тариф не найден", show_alert=True)
        return

    await call.answer()
    await call.message.answer_invoice(
        title=f"Таблица перепродаж — {label}",
        description=f"Доступ к Таблице перепродаж, тариф «{label}».",
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

    await deliver_purchase(
        message.bot,
        user_id=message.from_user.id,
        username=message.from_user.username,
        plan_code=plan_code,
        plan_label=PLAN_LABELS.get(plan_code, plan_code),
        days=PLAN_DAYS.get(plan_code),
        payment_method="stars",
    )
