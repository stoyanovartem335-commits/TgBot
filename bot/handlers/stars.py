from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ..database import get_settings
from ..keyboards import BTN_PAY_STARS, main_menu_kb
from ..services.delivery import deliver_purchase
from ..services.plans import PLAN_DAYS, PLAN_LABELS, plan_code_by_label
from ..services.settings_service import price_with_active_discount

log = logging.getLogger(__name__)
router = Router(name="stars")

def _plan_code_from_payment_text(text: str, prefix: str) -> str | None:
    raw = text.removeprefix(prefix).strip()
    if raw.startswith("—"):
        raw = raw[1:].strip()
    return plan_code_by_label(raw)


async def _send_stars_invoice(message: Message, plan_code: str, *, notify_error: bool) -> bool:
    settings = await get_settings()
    prices_stars = settings.get("prices_stars", {})

    stars_price = await price_with_active_discount(prices_stars.get(plan_code, 0), plan_code)
    label = PLAN_LABELS.get(plan_code, plan_code)

    if stars_price <= 0:
        if notify_error:
            await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return False

    await message.answer_invoice(
        title=f"Таблица перепродаж — {label}",
        description=f"Доступ к Таблице перепродаж, тариф «{label}».",
        payload=f"stars:{plan_code}",
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=stars_price)],
        provider_token="",
    )
    return True


@router.callback_query(F.data.startswith("pay:stars:"))
async def on_pay_stars(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None:
        return

    ok = await _send_stars_invoice(call.message, plan_code, notify_error=False)
    if not ok:
        await call.answer("Тариф не найден", show_alert=True)
        return

    await call.answer()


@router.message(F.text.startswith(BTN_PAY_STARS))
async def on_pay_stars_from_keyboard(message: Message) -> None:
    if not message.text:
        return
    plan_code = _plan_code_from_payment_text(message.text, BTN_PAY_STARS)
    if plan_code is None:
        await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return
    await _send_stars_invoice(message, plan_code, notify_error=True)


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
        amount_stars=int(sp.total_amount or 0),
    )
