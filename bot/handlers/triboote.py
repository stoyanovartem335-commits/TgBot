from __future__ import annotations

import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..database import create_pending, get_pending, get_settings, mark_pending_status
from ..services.delivery import deliver_purchase
from ..services.settings_service import price_with_active_discount
from ..services.triboote_api import TribooteError, create_payment

log = logging.getLogger(__name__)
router = Router(name="triboote")

PLAN_LABELS = {"1m": "1 месяц", "2m": "2 месяца", "3m": "3 месяца", "6m": "6 месяцев", "forever": "Forever"}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}


@router.callback_query(F.data.startswith("pay:triboote:"))
async def on_pay_triboote(call: CallbackQuery) -> None:
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

    await call.answer("Создаю платёж…")
    payment_id = uuid.uuid4().hex

    try:
        result = await create_payment(
            amount_rub=amount,
            payment_id=payment_id,
            description=f"Таблица перепродаж — {label}",
        )
    except TribooteError as exc:
        log.error("Triboote error: %s", exc)
        await call.message.answer(
            "⚠️ Не удалось создать платёж через Triboote.\n"
            f"Причина: {exc}\n\n"
            "Попробуйте другой способ оплаты."
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
        inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", url=result.pay_url)]]
    )
    await call.message.answer(
        f"Платёж создан.\n\nТариф: <b>{label}</b>\n"
        f"Сумма: <b>{amount} ₽</b>\n\n"
        "Нажмите кнопку ниже, чтобы оплатить. После оплаты бот автоматически пришлёт токен и инструкцию.",
        reply_markup=kb,
    )


async def complete_from_webhook(bot: Bot, payment_id: str) -> bool:
    pending = await get_pending(payment_id)
    if pending is None:
        log.warning("Triboote webhook unknown payment_id=%s", payment_id)
        return False
    if pending.get("status") == "completed":
        return True

    await deliver_purchase(
        bot,
        user_id=pending["user_id"],
        username=pending.get("username"),
        plan_code=pending["plan_code"],
        plan_label=PLAN_LABELS.get(pending["plan_code"], pending["plan_code"]),
        days=PLAN_DAYS.get(pending["plan_code"]),
        payment_method="triboote",
    )
    await mark_pending_status(payment_id, "completed")
    return True
