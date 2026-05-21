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


@router.callback_query(F.data.startswith("pay:requisites:"))
async def on_pay_requisites(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None or call.from_user is None:
        return

    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}

    amount = await price_with_active_discount(prices_rub.get(plan_code, 0))
    label = plan_labels.get(plan_code, plan_code)

    if amount <= 0:
        await call.answer("\u0422\u0430\u0440\u0438\u0444 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
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
        f"\u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e \u0440\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u0430\u043c \u2014 \u0442\u0430\u0440\u0438\u0444 <b>{label}</b>\n\n"
        f"\u0421\u0443\u043c\u043c\u0430: <b>{amount} \u20bd</b>\n\n"
        f"\u0411\u0430\u043d\u043a: <b>{REQUISITES_TEXT}</b>\n"
        f"\u041a\u0430\u0440\u0442\u0430: <code>{REQUISITES_CARD}</code>\n"
        f"\u041f\u043e\u043b\u0443\u0447\u0430\u0442\u0435\u043b\u044c: <b>{REQUISITES_NAME}</b>\n\n"
        "\u041f\u043e\u0441\u043b\u0435 \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u0430 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u042f \u043e\u043f\u043b\u0430\u0442\u0438\u043b\u00bb."
    )
    await call.message.answer(text, reply_markup=i_paid_kb(payment_id))


@router.callback_query(F.data.startswith("paid:"))
async def on_user_paid(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return
    payment_id = call.data.split(":", 1)[1]
    pending = await get_pending(payment_id)
    if pending is None or pending["user_id"] != call.from_user.id:
        await call.answer("\u0417\u0430\u044f\u0432\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430", show_alert=True)
        return
    if pending.get("status") != "pending":
        await call.answer("\u0417\u0430\u044f\u0432\u043a\u0430 \u0443\u0436\u0435 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u0430", show_alert=True)
        return

    settings = await get_settings()
    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
    prices_rub = settings.get("prices_rub", {})
    plan_code = pending["plan_code"]
    label = plan_labels.get(plan_code, plan_code)
    amount = await price_with_active_discount(prices_rub.get(plan_code, 0))

    await call.answer("\u0421\u043f\u0430\u0441\u0438\u0431\u043e! \u0417\u0430\u044f\u0432\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430 \u043d\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "\U0001f552 \u0417\u0430\u044f\u0432\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443. \u041f\u043e\u0441\u043b\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u0432\u044b \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 \u0442\u043e\u043a\u0435\u043d."
    )

    uname = call.from_user.username
    user_ref = f"@{uname}" if uname else f"id={call.from_user.id}"
    admin_text = (
        "\U0001f514 <b>\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u044f\u0432\u043a\u0430 \u043d\u0430 \u043e\u043f\u043b\u0430\u0442\u0443 \u043f\u043e \u0440\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u0430\u043c</b>\n\n"
        f"\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c: {user_ref}\n"
        f"\u0418\u043c\u044f: {call.from_user.full_name}\n"
        f"\u0422\u0430\u0440\u0438\u0444: <b>{label}</b>\n"
        f"\u0421\u0443\u043c\u043c\u0430: <b>{amount} \u20bd</b>\n"
        f"Payment ID: <code>{payment_id}</code>"
    )
    try:
        await call.bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_review_kb(payment_id))
    except Exception as exc:
        log.exception("Failed to notify admin: %s", exc)
