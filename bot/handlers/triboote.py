from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..config import (
    ADMIN_ID,
    TRIBUTE_PAYMENT_MODE,
    TRIBUTE_PRODUCT_IDS,
    TRIBUTE_PRODUCT_NAMES,
    TRIBUTE_PRODUCT_URLS,
)
from ..database import (
    create_pending,
    get_latest_pending_for_user,
    get_pending,
    get_pending_by_external_ref,
    get_settings,
    mark_pending_processing,
    mark_pending_status,
)
from ..services.delivery import deliver_purchase
from ..services.settings_service import price_with_active_discount
from ..services.triboote_api import (
    TribooteError,
    create_payment,
    get_product_payment_url,
    get_product_ref,
)

log = logging.getLogger(__name__)
router = Router(name="triboote")

PLAN_LABELS = {"1m": "1 месяц", "2m": "2 месяца", "3m": "3 месяца", "6m": "6 месяцев", "forever": "Forever"}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}
PLAN_CODES = tuple(PLAN_LABELS.keys())

_PLAN_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    "forever": (r"\bforever\b", r"\blifetime\b", r"навсегда", r"бессроч"),
    "6m": (r"\b6\s*(m|mo|month|months)\b", r"6\s*мес", r"6\s*месяц", r"\b180\s*(д|day|days)\b", r"half\s*year"),
    "3m": (r"\b3\s*(m|mo|month|months)\b", r"3\s*мес", r"3\s*месяц", r"\b90\s*(д|day|days)\b", r"quarter"),
    "2m": (r"\b2\s*(m|mo|month|months)\b", r"2\s*мес", r"2\s*месяц", r"\b60\s*(д|day|days)\b"),
    "1m": (r"\b1\s*(m|mo|month)\b", r"1\s*мес", r"1\s*месяц", r"\b30\s*(д|day|days)\b"),
}


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id == ADMIN_ID


async def _send_payment_error(call: CallbackQuery, exc: Exception, plan_code: str) -> None:
    if call.message is None or call.from_user is None:
        return

    if _is_admin(call.from_user.id):
        await call.message.answer(
            "⚠️ Не удалось создать платёж через Tribute.\n"
            f"Причина: {exc}"
        )
        return

    await call.message.answer("⚠️ Не удалось создать платёж через Tribute.")

    user_ref = f"@{call.from_user.username}" if call.from_user.username else f"id={call.from_user.id}"
    try:
        await call.bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Ошибка создания платежа Tribute</b>\n\n"
            f"Пользователь: {user_ref}\n"
            f"Тариф: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
            f"TRIBUTE_PAYMENT_MODE: <code>{TRIBUTE_PAYMENT_MODE}</code>\n"
            f"Причина: <code>{str(exc)}</code>",
        )
    except Exception:
        log.exception("Failed to notify admin about Tribute payment error")


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
    pay_url = None
    external_ref = None

    if TRIBUTE_PAYMENT_MODE != "api":
        pay_url = get_product_payment_url(plan_code)
        external_ref = get_product_ref(plan_code)

    if pay_url is None:
        if TRIBUTE_PAYMENT_MODE in {"links", "product", "products"}:
            await call.message.answer(
                "⚠️ Для этого тарифа не задана ссылка Tribute.\n"
                f"Добавьте TRIBUTE_PRODUCT_URL_{plan_code.upper()} в env или переключите TRIBUTE_PAYMENT_MODE=api."
            )
            return
        try:
            result = await create_payment(
                amount_rub=amount,
                payment_id=payment_id,
                description=f"Таблица перепродаж — {label}",
                title=f"Таблица Каливана — {label}",
                user_id=call.from_user.id,
                plan_code=plan_code,
            )
        except TribooteError as exc:
            log.error("Tribute error: %s", exc)
            await _send_payment_error(call, exc, plan_code)
            return
        pay_url = result.pay_url
        external_ref = result.payment_id

    await create_pending(
        payment_id=payment_id,
        user_id=call.from_user.id,
        username=call.from_user.username,
        plan_code=plan_code,
        payment_method="triboote",
        external_ref=external_ref,
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)]]
    )
    await call.message.answer(
        f"Платёж создан.\n\nТариф: <b>{label}</b>\n"
        f"Сумма: <b>{amount} ₽</b>\n\n"
        "Нажмите кнопку ниже, чтобы оплатить в Tribute. После успешной оплаты бот автоматически пришлёт токен и инструкцию.",
        reply_markup=kb,
    )


async def complete_from_webhook(bot: Bot, payment_id: str) -> bool:
    pending = await get_pending(payment_id) or await get_pending_by_external_ref(payment_id)
    if pending is None:
        log.warning("Tribute webhook unknown payment_id=%s", payment_id)
        return False
    return await _complete_pending(bot, pending)


async def complete_from_tribute_event(bot: Bot, data: dict[str, Any]) -> bool:
    name = str(data.get("name") or data.get("event") or "").lower()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data

    if name == "new_digital_product":
        return await _complete_digital_product(bot, payload)
    if name == "shop_order":
        return await _complete_shop_order(bot, payload)
    if name == "digital_product_refunded":
        await _handle_digital_refund(payload)
        return True

    status = str(payload.get("status") or data.get("status") or "").lower()
    payment_id = (
        payload.get("uuid")
        or payload.get("external_id")
        or payload.get("payment_id")
        or payload.get("id")
        or data.get("external_id")
        or data.get("payment_id")
        or data.get("id")
    )
    if status in {"paid", "succeeded", "success", "completed", "payment.success"} and payment_id:
        return await complete_from_webhook(bot, str(payment_id))

    log.info("Tribute webhook ignored name=%s status=%s", name, status)
    return True


async def _complete_shop_order(bot: Bot, payload: dict[str, Any]) -> bool:
    if str(payload.get("status") or "").lower() != "paid":
        return True

    order_uuid = str(payload.get("uuid") or "")
    if not order_uuid:
        log.warning("Tribute shop_order without uuid: %s", payload)
        return False

    pending = await get_pending_by_external_ref(order_uuid) or await get_pending(order_uuid)
    if pending is None:
        log.warning("Tribute shop_order unknown uuid=%s", order_uuid)
        return False
    return await _complete_pending(bot, pending)


async def _complete_digital_product(bot: Bot, payload: dict[str, Any]) -> bool:
    try:
        user_id = int(payload.get("telegram_user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        log.warning("Tribute digital product without telegram_user_id: %s", payload)
        return False

    plan_code = await _resolve_plan_code(payload)
    linked_pending_id: str | None = None
    if plan_code is None:
        latest_pending = await get_latest_pending_for_user(user_id=user_id, payment_method="triboote")
        if latest_pending is not None:
            plan_code = latest_pending.get("plan_code")
            linked_pending_id = latest_pending.get("payment_id")

    if plan_code not in PLAN_CODES:
        log.warning("Tribute digital product cannot map plan: %s", payload)
        return False

    event_id = _digital_event_id(payload)
    await create_pending(
        payment_id=event_id,
        user_id=user_id,
        username=payload.get("telegram_username"),
        plan_code=plan_code,
        payment_method="triboote",
        external_ref=str(payload.get("purchase_id") or payload.get("transaction_id") or payload.get("product_id") or ""),
    )
    pending = await get_pending(event_id)
    if pending is None:
        return False

    ok = await _complete_pending(bot, pending)
    if ok and linked_pending_id:
        await mark_pending_status(linked_pending_id, "completed")
    return ok


async def _complete_pending(bot: Bot, pending: dict) -> bool:
    payment_id = pending["payment_id"]
    if pending.get("status") == "completed":
        return True

    claimed = await mark_pending_processing(payment_id)
    if not claimed:
        current = await get_pending(payment_id)
        return current is not None and current.get("status") in {"completed", "processing"}

    try:
        await deliver_purchase(
            bot,
            user_id=pending["user_id"],
            username=pending.get("username"),
            plan_code=pending["plan_code"],
            plan_label=PLAN_LABELS.get(pending["plan_code"], pending["plan_code"]),
            days=PLAN_DAYS.get(pending["plan_code"]),
            payment_method="triboote",
        )
    except Exception:
        await mark_pending_status(payment_id, "failed")
        raise

    await mark_pending_status(payment_id, "completed")
    return True


async def _resolve_plan_code(payload: dict[str, Any]) -> str | None:
    product_id = str(payload.get("product_id") or "").strip()
    if product_id:
        for code, configured_id in TRIBUTE_PRODUCT_IDS.items():
            if str(configured_id).strip() == product_id:
                return code

    web_app_link = str(payload.get("web_app_link") or payload.get("link") or "").strip()
    if web_app_link:
        normalized = _normalize_url(web_app_link)
        for code, configured_url in TRIBUTE_PRODUCT_URLS.items():
            if _normalize_url(configured_url) == normalized:
                return code

    product_name = str(payload.get("product_name") or payload.get("title") or "").strip()
    if product_name:
        for code, configured_name in TRIBUTE_PRODUCT_NAMES.items():
            if configured_name and configured_name.strip().casefold() == product_name.casefold():
                return code
        plan_from_name = _plan_from_name(product_name)
        if plan_from_name:
            return plan_from_name

    return await _plan_from_amount(payload)


async def _plan_from_amount(payload: dict[str, Any]) -> str | None:
    currency = str(payload.get("currency") or "").lower()
    if currency not in {"rub", "rur", "₽", ""}:
        return None

    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    matches: list[str] = []
    for code in PLAN_CODES:
        price = await price_with_active_discount(int(prices_rub.get(code, 0)))
        if price > 0 and amount in {price, price * 100}:
            matches.append(code)
    return matches[0] if len(matches) == 1 else None


def _plan_from_name(name: str) -> str | None:
    normalized = name.casefold()
    for code, patterns in _PLAN_NAME_PATTERNS.items():
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            return code
    return None


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/")


def _digital_event_id(payload: dict[str, Any]) -> str:
    raw = (
        payload.get("purchase_id")
        or payload.get("transaction_id")
        or f"{payload.get('product_id')}:{payload.get('telegram_user_id')}:{payload.get('purchase_created_at')}"
    )
    return f"tribute:digital:{raw}"


async def _handle_digital_refund(payload: dict[str, Any]) -> None:
    log.warning(
        "Tribute digital product refunded: purchase_id=%s transaction_id=%s user=%s product=%s",
        payload.get("purchase_id"),
        payload.get("transaction_id"),
        payload.get("telegram_user_id"),
        payload.get("product_id"),
    )
