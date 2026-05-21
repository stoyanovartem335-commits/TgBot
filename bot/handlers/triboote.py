"""Triboote payment flow."""
from __future__ import annotations

import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..database import create_pending, get_pending, get_settings, mark_pending_status
from ..services.delivery import deliver_purchase
from ..services.triboote_api import TribooteError, create_payment

log = logging.getLogger(__name__)
router = Router(name="triboote")


@router.callback_query(F.data.startswith("pay:triboote:"))
async def on_pay_triboote(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None or call.from_user is None:
        return

    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}

    amount = prices_rub.get(plan_code, 0)
    label = plan_labels.get(plan_code, plan_code)

    if amount <= 0:
        await call.answer("\u0422\u0430\u0440\u0438\u0444 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    await call.answer("\u0421\u043e\u0437\u0434\u0430\u044e \u043f\u043b\u0430\u0442\u0451\u0436\u2026")
    payment_id = uuid.uuid4().hex

    try:
        result = await create_payment(
            amount_rub=amount,
            payment_id=payment_id,
            description=f"\u0422\u0430\u0431\u043b\u0438\u0446\u0430 \u043f\u0435\u0440\u0435\u043f\u0440\u043e\u0434\u0430\u0436 \u2014 {label}",
        )
    except TribooteError as exc:
        log.error("Triboote error: %s", exc)
        await call.message.answer(
            "\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u043f\u043b\u0430\u0442\u0451\u0436 \u0447\u0435\u0440\u0435\u0437 Triboote.\n"
            f"\u041f\u0440\u0438\u0447\u0438\u043d\u0430: {exc}\n\n"
            "\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b."
        )
        return

    await create_pending(
        payment_id=payment_id,
        user_id=call.from_user.id,
        username=call.from_user.username,
        plan_code=plan_code,
        payment_method="triboote",
        external_ref=result.payment_id,
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="\U0001f4b3 \u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a \u043e\u043f\u043b\u0430\u0442\u0435", url=result.pay_url)]]
    )
    await call.message.answer(
        f"\u041f\u043b\u0430\u0442\u0451\u0436 \u0441\u043e\u0437\u0434\u0430\u043d.\n\n\u0422\u0430\u0440\u0438\u0444: <b>{label}</b>\n"
        f"\u0421\u0443\u043c\u043c\u0430: <b>{amount} \u20bd</b>\n\n"
        "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435, \u0447\u0442\u043e\u0431\u044b \u043e\u043f\u043b\u0430\u0442\u0438\u0442\u044c. \u041f\u043e\u0441\u043b\u0435 \u043e\u043f\u043b\u0430\u0442\u044b \u0431\u043e\u0442 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043f\u0440\u0438\u0448\u043b\u0451\u0442 \u0442\u043e\u043a\u0435\u043d \u0438 \u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u044e.",
        reply_markup=kb,
    )


async def complete_from_webhook(bot: Bot, payment_id: str) -> bool:
    pending = await get_pending(payment_id)
    if pending is None:
        log.warning("Triboote webhook unknown payment_id=%s", payment_id)
        return False
    if pending.get("status") == "completed":
        return True

    plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
    plan_days = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}

    await deliver_purchase(
        bot,
        user_id=pending["user_id"],
        username=pending.get("username"),
        plan_code=pending["plan_code"],
        plan_label=plan_labels.get(pending["plan_code"], pending["plan_code"]),
        days=plan_days.get(pending["plan_code"]),
        payment_method="triboote",
    )
    await mark_pending_status(payment_id, "completed")
    return True
