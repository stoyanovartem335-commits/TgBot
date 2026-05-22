from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import ADMIN_ID, REQUISITES_CARD, REQUISITES_NAME, REQUISITES_TEXT
from ..database import create_pending, get_pending, get_settings
from ..keyboards import admin_review_kb, i_paid_kb
from ..services.settings_service import price_with_active_discount

log = logging.getLogger(__name__)
router = Router(name="requisites")

PLAN_LABELS = {"1m": "1 месяц", "2m": "2 месяца", "3m": "3 месяца", "6m": "6 месяцев", "forever": "Forever"}


@router.callback_query(F.data.startswith("pay:requisites:"))
async def on_pay_requisites(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None or call.from_user is None:
        return

    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})

    amount = await price_with_active_discount(prices_rub.get(plan_code, 0))
    label = PLAN_LABELS.get(plan_code, plan_code)

    if amount <= 0:
        await call.answer("Тариф не найден", show_alert=True)
        return

    await call.answer()
    payment_id = uuid.uuid4().hex

    await create_pending(
        payment_id=payment_id,
        user_id=call.from_user.id,
        username=call.from_user.username,
        plan_code=plan_code,
        payment_method="requisites",
    )

    text = (
        f"Оплата по реквизитам — тариф <b>{label}</b>\n\n"
        f"Сумма: <b>{amount} ₽</b>\n\n"
        f"Банк: <b>{REQUISITES_TEXT}</b>\n"
        f"Карта: <code>{REQUISITES_CARD}</code>\n"
        f"Получатель: <b>{REQUISITES_NAME}</b>\n\n"
        "После перевода нажмите «Я оплатил»."
    )
    await call.message.answer(text, reply_markup=i_paid_kb(payment_id))


@router.callback_query(F.data.startswith("paid:"))
async def on_user_paid(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return
    payment_id = call.data.split(":", 1)[1]
    pending = await get_pending(payment_id)
    if pending is None or pending["user_id"] != call.from_user.id:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") != "pending":
        await call.answer("Заявка уже обработана", show_alert=True)
        return

    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    plan_code = pending["plan_code"]
    label = PLAN_LABELS.get(plan_code, plan_code)
    amount = await price_with_active_discount(prices_rub.get(plan_code, 0))

    await call.answer("Спасибо! Заявка отправлена на проверку.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "🕒 Заявка отправлена администратору. После подтверждения вы получите токен."
    )

    uname = call.from_user.username
    user_ref = f"@{uname}" if uname else f"id={call.from_user.id}"
    admin_text = (
        "🔔 <b>Новая заявка на оплату по реквизитам</b>\n\n"
        f"Пользователь: {user_ref}\n"
        f"Имя: {call.from_user.full_name}\n"
        f"Тариф: <b>{label}</b>\n"
        f"Сумма: <b>{amount} ₽</b>\n"
        f"Payment ID: <code>{payment_id}</code>"
    )
    try:
        await call.bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_review_kb(payment_id))
    except Exception as exc:
        log.exception("Failed to notify admin: %s", exc)
