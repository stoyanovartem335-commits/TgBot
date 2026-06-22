from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from ..config import (
    ADMIN_ID,
    TG_CHANNEL_URL,
    TRIBUTE_ALLOWED_CHANNEL_IDS,
    TRIBUTE_ALLOWED_CHANNEL_NAMES,
    TRIBUTE_ALLOWED_SUBSCRIPTION_IDS,
    TRIBUTE_PERIOD_IDS,
    TRIBUTE_SUBSCRIPTION_URL,
)
from ..database import (
    create_pending,
    get_latest_purchase_for_user,
    get_latest_pending_for_user,
    get_pending,
    get_pending_by_external_ref,
    get_settings,
    mark_pending_processing,
    mark_pending_status,
)
from ..keyboards import BTN_PAY_TRIBUTE, main_menu_kb
from ..services.delivery import deliver_purchase, renew_latest_purchase
from ..services.plans import PLAN_CODES, PLAN_DAYS, PLAN_LABELS, plan_code_by_label
from ..services.settings_service import price_with_active_discount

log = logging.getLogger(__name__)
router = Router(name="triboote")

_PLAN_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    "forever": (r"\bforever\b", r"\blifetime\b", r"навсегда", r"бессроч"),
    "6m": (r"\b6\s*(m|mo|month|months)\b", r"6\s*мес", r"6\s*месяц", r"\b180\s*(д|day|days)\b", r"half\s*year"),
    "3m": (r"\b3\s*(m|mo|month|months)\b", r"3\s*мес", r"3\s*месяц", r"\b90\s*(д|day|days)\b", r"quarter"),
    "1m": (r"\b1\s*(m|mo|month)\b", r"1\s*мес", r"1\s*месяц", r"\b30\s*(д|day|days)\b"),
}

_PLAN_NAME_PATTERNS = {
    "forever": (r"\bforever\b", r"\blifetime\b", r"\bpermanent\b", r"\bunlimited\b", r"\bone[_\s-]?time\b", r"навсегда", r"бессроч"),
    "6m": (r"\b6\s*(m|mo|month|months)\b", r"\b6[_\s-]?month", r"\bsemi[_\s-]?annual\b", r"\bhalf[_\s-]?year\b", r"6\s*мес", r"6\s*месяц", r"\b180\s*(д|day|days)\b"),
    "3m": (r"\b3\s*(m|mo|month|months)\b", r"\b3[_\s-]?month", r"\bquarter", r"\bthree[_\s-]?month", r"3\s*мес", r"3\s*месяц", r"\b90\s*(д|day|days)\b"),
    "1m": (r"\b1\s*(m|mo|month)\b", r"\bmonthly\b", r"\bmonth\b", r"\b1[_\s-]?month", r"1\s*мес", r"1\s*месяц", r"\b30\s*(д|day|days)\b"),
}


_DIGITAL_PRODUCT_EVENTS = {
    "new_digital_product",
    "digital_product",
    "digital_product.paid",
    "digital_product_paid",
}


def _plan_code_from_payment_text(text: str, prefix: str) -> str | None:
    raw = text.removeprefix(prefix).strip()
    if raw.startswith("—"):
        raw = raw[1:].strip()
    return plan_code_by_label(raw)


async def _send_tribute_payment(message: Message, user: User, plan_code: str, *, notify_error: bool) -> bool:
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    amount = await price_with_active_discount(prices_rub.get(plan_code, 0))
    label = PLAN_LABELS.get(plan_code, plan_code)

    if amount <= 0:
        if notify_error:
            await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return False

    if not TRIBUTE_SUBSCRIPTION_URL:
        if notify_error:
            await message.answer(
                "⚠️ Tribute ссылка на подписку не настроена.\n\n"
                "Админу нужно добавить в env переменную <code>TRIBUTE_SUBSCRIPTION_URL</code>."
            )
        try:
            await message.bot.send_message(
                ADMIN_ID,
                "⚠️ Пользователь нажал оплату через Tribute, но <code>TRIBUTE_SUBSCRIPTION_URL</code> пустой.",
            )
        except Exception:
            log.exception("Failed to notify admin about missing Tribute subscription URL")
        return False

    payment_id = f"tribute:checkout:{user.id}:{uuid.uuid4().hex}"
    await create_pending(
        payment_id=payment_id,
        user_id=user.id,
        username=user.username,
        plan_code=plan_code,
        payment_method="triboote",
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате в Tribute", url=TRIBUTE_SUBSCRIPTION_URL)]]
    )
    await message.answer(
        f"Вы выбрали: <b>{label}</b>\n"
        f"Цена в боте: <b>{amount} ₽</b>\n\n"
        "В Tribute откроется окно подписки с тарифами. "
        "Если там выберете другой срок, бот выдаст доступ по фактически оплаченному тарифу.",
        reply_markup=kb,
    )
    return True


@router.callback_query(F.data.startswith("pay:triboote:"))
async def on_pay_triboote(call: CallbackQuery) -> None:
    plan_code = call.data.split(":", 2)[2]
    if call.message is None or call.from_user is None:
        return

    if not TRIBUTE_SUBSCRIPTION_URL:
        await call.answer("Tribute ссылка не настроена", show_alert=True)
        await _send_tribute_payment(call.message, call.from_user, plan_code, notify_error=True)
        return

    ok = await _send_tribute_payment(call.message, call.from_user, plan_code, notify_error=False)
    if not ok:
        await call.answer("Тариф не найден", show_alert=True)
        return

    await call.answer("Открываю Tribute...")


@router.message(F.text.startswith(BTN_PAY_TRIBUTE))
async def on_pay_tribute_from_keyboard(message: Message) -> None:
    if message.from_user is None or not message.text:
        return
    plan_code = _plan_code_from_payment_text(message.text, BTN_PAY_TRIBUTE)
    if plan_code is None:
        await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return
    await _send_tribute_payment(message, message.from_user, plan_code, notify_error=True)


async def complete_from_webhook(bot: Bot, payment_id: str) -> bool:
    pending = await get_pending(payment_id) or await get_pending_by_external_ref(payment_id)
    if pending is None:
        log.warning("Tribute webhook unknown payment_id=%s", payment_id)
        return False
    return await _complete_pending(bot, pending, renew=False)


async def complete_from_tribute_event(bot: Bot, data: dict[str, Any]) -> bool:
    name = str(data.get("name") or data.get("event") or data.get("type") or "").lower()
    payload = _extract_payload(data)
    payload = _payload_with_event_fields(payload, data)

    if data.get("test_event") == "test_event":
        return True

    if name in {"new_subscription", "subscription_created", "subscription.paid", "subscription_paid", "new_subscription_gift", "subscription_gift", "gift_subscription", "gifted_subscription"}:
        return await _complete_subscription_event(bot, name, payload, data, renew=False)

    if name in _DIGITAL_PRODUCT_EVENTS:
        return await _complete_digital_product_event(bot, name, payload, data)

    if name in {"renewed_subscription", "subscription_renewed", "subscription.renewed", "subscription_rebill", "rebill_subscription", "recurring_payment", "subscription_payment"}:
        return await _complete_subscription_event(bot, name, payload, data, renew=True)

    if name in {"cancelled_subscription", "subscription_cancelled", "subscription.cancelled", "canceled_subscription", "subscription_canceled", "subscription.canceled"}:
        log.info("Tribute subscription cancelled: %s", payload)
        return True

    status = str(payload.get("status") or data.get("status") or "").lower()
    payment_id = _first_value(payload, data, "uuid", "external_id", "payment_id", "id")
    if status in {"paid", "succeeded", "success", "completed", "payment.success"} and payment_id:
        user_id = _extract_telegram_user_id(payload)
        plan_code = await _resolve_plan_code(payload)
        if user_id > 0 and plan_code in PLAN_CODES and _is_allowed_tribute_subject(payload):
            event_id = f"tribute:payment:{payment_id}"
            await create_pending(
                payment_id=event_id,
                user_id=user_id,
                username=str(payload.get("telegram_username") or payload.get("username") or "") or None,
                plan_code=plan_code,
                payment_method="triboote",
                external_ref=str(payment_id),
            )
            pending = await get_pending(event_id)
            if pending is None:
                return False
            return await _complete_pending(bot, pending, renew=False, expires_at_override=_extract_expires_at(payload))
        if _has_plan_signal(payload):
            log.warning("Tribute paid event has plan signal but cannot map plan safely: %s", payload)
            return False
        return await complete_from_webhook(bot, str(payment_id))

    log.info("Tribute webhook ignored name=%s status=%s payload=%s", name, status, payload)
    return True


async def _complete_digital_product_event(
    bot: Bot,
    name: str,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> bool:
    user_id = _extract_telegram_user_id(payload)
    if user_id <= 0:
        log.warning("Tribute digital product without telegram_user_id: %s", payload)
        return False

    plan_code = await _resolve_plan_code(payload)
    if plan_code not in PLAN_CODES:
        log.warning("Tribute digital product cannot map plan: %s", payload)
        return False

    event_id = _digital_product_event_id(name, payload, data)
    await create_pending(
        payment_id=event_id,
        user_id=user_id,
        username=str(payload.get("telegram_username") or payload.get("username") or "") or None,
        plan_code=plan_code,
        payment_method="triboote",
        external_ref=_digital_product_external_ref(payload, data),
    )
    pending = await get_pending(event_id)
    if pending is None:
        return False
    return await _complete_pending(bot, pending, renew=False, expires_at_override=_extract_expires_at(payload))


async def _complete_subscription_event(
    bot: Bot,
    name: str,
    payload: dict[str, Any],
    data: dict[str, Any],
    *,
    renew: bool,
) -> bool:
    if not _is_allowed_tribute_subject(payload):
        log.warning("Tribute subscription ignored by filters: %s", payload)
        return False

    user_id = _extract_telegram_user_id(payload)
    if user_id <= 0:
        log.warning("Tribute subscription without telegram_user_id: %s", payload)
        return False

    plan_code = await _resolve_plan_code(payload)
    if plan_code is None:
        if _has_plan_signal(payload):
            log.warning("Tribute subscription has plan signal but cannot map plan safely: %s", payload)
            return False
        latest_pending = await get_latest_pending_for_user(user_id=user_id, payment_method="triboote")
        if latest_pending is not None:
            plan_code = latest_pending.get("plan_code")

    if plan_code not in PLAN_CODES:
        log.warning("Tribute subscription cannot map plan: %s", payload)
        return False

    existing_purchase = await get_latest_purchase_for_user(user_id, payment_method="triboote")
    renew = renew or existing_purchase is not None

    event_id = _subscription_event_id(name, payload, data)
    await create_pending(
        payment_id=event_id,
        user_id=user_id,
        username=str(payload.get("telegram_username") or payload.get("username") or "") or None,
        plan_code=plan_code,
        payment_method="triboote",
        external_ref=_subscription_external_ref(payload),
    )
    pending = await get_pending(event_id)
    if pending is None:
        return False
    return await _complete_pending(bot, pending, renew=renew, expires_at_override=_extract_expires_at(payload))


async def _complete_pending(bot: Bot, pending: dict, *, renew: bool, expires_at_override=None) -> bool:
    payment_id = pending["payment_id"]
    if pending.get("status") == "completed":
        return True

    claimed = await mark_pending_processing(payment_id)
    if not claimed:
        current = await get_pending(payment_id)
        return current is not None and current.get("status") in {"completed", "processing"}

    plan_code = pending["plan_code"]
    try:
        if renew:
            await renew_latest_purchase(
                bot,
                user_id=pending["user_id"],
                username=pending.get("username"),
                plan_code=plan_code,
                plan_label=PLAN_LABELS.get(plan_code, plan_code),
                days=PLAN_DAYS.get(plan_code),
                payment_method="triboote",
                expires_at_override=expires_at_override,
            )
        else:
            await deliver_purchase(
                bot,
                user_id=pending["user_id"],
                username=pending.get("username"),
                plan_code=plan_code,
                plan_label=PLAN_LABELS.get(plan_code, plan_code),
                days=PLAN_DAYS.get(plan_code),
                payment_method="triboote",
                expires_at_override=expires_at_override,
            )
    except Exception:
        await mark_pending_status(payment_id, "failed")
        raise

    await mark_pending_status(payment_id, "completed")
    return True


async def _resolve_plan_code(payload: dict[str, Any]) -> str | None:
    period_id = _extract_period_id(payload)
    if period_id:
        for code, configured_id in TRIBUTE_PERIOD_IDS.items():
            if str(configured_id).strip() == period_id:
                return code

    product_name = _extract_plan_name(payload)
    if product_name:
        plan_from_name = _plan_from_name(product_name)
        if plan_from_name:
            return plan_from_name

    plan_from_dates = _plan_from_dates(payload)
    if plan_from_dates:
        return plan_from_dates

    return await _plan_from_amount(payload)


def _has_plan_signal(payload: dict[str, Any]) -> bool:
    return bool(_extract_period_id(payload) or _extract_plan_name(payload) or _extract_amount(payload) > 0)


def _extract_plan_name(payload: dict[str, Any]) -> str:
    values = (
        payload.get("product_name"),
        payload.get("period_name"),
        payload.get("tariff_name"),
        payload.get("plan_name"),
        payload.get("title"),
        payload.get("name"),
    )
    for nested_key in ("period", "tariff", "plan", "product", "subscription"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            values = (
                *values,
                nested.get("product_name"),
                nested.get("period_name"),
                nested.get("tariff_name"),
                nested.get("plan_name"),
                nested.get("title"),
                nested.get("name"),
            )
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_payload(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload", "data", "object"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return data


def _payload_with_event_fields(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if payload is data:
        return payload
    merged = dict(payload)
    for key in ("name", "event", "type", "created_at", "createdAt", "sent_at", "sentAt"):
        if key in data and key not in merged:
            merged[key] = data[key]
    return merged


def _extract_telegram_user_id(payload: dict[str, Any]) -> int:
    values = (
        payload.get("recipient_telegram_user_id"),
        payload.get("recipientTelegramUserId"),
        payload.get("receiver_telegram_user_id"),
        payload.get("receiverTelegramUserId"),
        payload.get("gifted_to_telegram_user_id"),
        payload.get("giftedToTelegramUserId"),
        payload.get("telegram_user_id"),
        payload.get("telegramUserId"),
        payload.get("tg_user_id"),
        payload.get("user_id"),
    )
    for nested_key in ("recipient", "receiver", "gift_recipient", "gifted_to"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            values = (
                *values,
                nested.get("telegram_user_id"),
                nested.get("telegramUserId"),
                nested.get("tg_user_id"),
                nested.get("id"),
            )
    user = payload.get("user")
    if isinstance(user, dict):
        values = (*values, user.get("telegram_user_id"), user.get("telegramUserId"), user.get("id"))
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 0


def _extract_period_id(payload: dict[str, Any]) -> str:
    values = (payload.get("period_id"), payload.get("periodId"), payload.get("tariff_id"), payload.get("plan_id"))
    period = payload.get("period")
    if isinstance(period, dict):
        values = (*values, period.get("id"), period.get("uuid"))
    tariff = payload.get("tariff")
    if isinstance(tariff, dict):
        values = (*values, tariff.get("id"), tariff.get("uuid"), tariff.get("period_id"))
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_subscription_id(payload: dict[str, Any]) -> str:
    values = (payload.get("subscription_id"), payload.get("subscriptionId"))
    subscription = payload.get("subscription")
    if isinstance(subscription, dict):
        values = (*values, subscription.get("id"), subscription.get("uuid"))
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_channel_id(payload: dict[str, Any]) -> str:
    values = (payload.get("channel_id"), payload.get("channelId"))
    channel = payload.get("channel")
    if isinstance(channel, dict):
        values = (*values, channel.get("id"), channel.get("telegram_id"), channel.get("telegramId"))
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_channel_name(payload: dict[str, Any]) -> str:
    values = (
        payload.get("channel_name"),
        payload.get("channelName"),
        payload.get("channel_username"),
        payload.get("channelUsername"),
    )
    channel = payload.get("channel")
    if isinstance(channel, dict):
        values = (*values, channel.get("name"), channel.get("username"), channel.get("link"))
    for value in values:
        text = _normalize_subject_name(str(value or ""))
        if text:
            return text
    return ""


def _is_allowed_tribute_subject(payload: dict[str, Any]) -> bool:
    channel_id = _extract_channel_id(payload)
    if TRIBUTE_ALLOWED_CHANNEL_IDS and channel_id not in TRIBUTE_ALLOWED_CHANNEL_IDS:
        return False

    channel_name = _extract_channel_name(payload)
    allowed_names = {_normalize_subject_name(value) for value in TRIBUTE_ALLOWED_CHANNEL_NAMES}
    if allowed_names and channel_name not in allowed_names:
        return False

    subscription_id = _extract_subscription_id(payload)
    if TRIBUTE_ALLOWED_SUBSCRIPTION_IDS and subscription_id not in TRIBUTE_ALLOWED_SUBSCRIPTION_IDS:
        return False

    return True


def _plan_from_dates(payload: dict[str, Any]) -> str | None:
    created_at = _extract_created_at(payload)
    expires_at = _extract_expires_at(payload)
    if created_at is None or expires_at is None:
        return None
    days = (expires_at - created_at).total_seconds() / 86400
    if 20 <= days <= 45:
        return "1m"
    if 70 <= days <= 120:
        return "3m"
    if 150 <= days <= 220:
        return "6m"
    return None


async def _plan_from_amount(payload: dict[str, Any]) -> str | None:
    currency = str(payload.get("currency") or payload.get("amount_currency") or "").lower()
    if currency not in {"rub", "rur", "₽", ""}:
        return None

    amount = _extract_amount(payload)
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


def _extract_amount(payload: dict[str, Any]) -> int:
    values = (
        payload.get("amount"),
        payload.get("price"),
        payload.get("total"),
        payload.get("paid_amount"),
        payload.get("amount_value"),
    )
    period = payload.get("period")
    if isinstance(period, dict):
        values = (*values, period.get("amount"), period.get("price"))
    for value in values:
        try:
            text = str(value or "").replace(" ", "").replace(",", ".")
            if not text:
                continue
            parsed = float(text)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return int(round(parsed))
    return 0


def _extract_expires_at(payload: dict[str, Any]):
    raw = payload.get("expires_at") or payload.get("expiresAt") or payload.get("subscription_expires_at")
    return _parse_tribute_datetime(raw)


def _extract_created_at(payload: dict[str, Any]):
    raw = payload.get("created_at") or payload.get("createdAt") or payload.get("paid_at") or payload.get("paidAt")
    return _parse_tribute_datetime(raw)


def _parse_tribute_datetime(raw):
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _plan_from_name(name: str) -> str | None:
    normalized = name.casefold()
    for code, patterns in _PLAN_NAME_PATTERNS.items():
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            return code
    return None


def _normalize_subject_name(value: str) -> str:
    raw = value.strip().rstrip("/")
    raw = raw.rsplit("/", 1)[-1] if "/" in raw else raw
    return raw.lstrip("@").casefold()


def _telegram_slug(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    return raw.rsplit("/", 1)[-1].lstrip("@")


def _subscription_external_ref(payload: dict[str, Any]) -> str:
    return ":".join([
        "subscription",
        _extract_subscription_id(payload),
        _extract_period_id(payload),
        str(_extract_telegram_user_id(payload) or ""),
    ])


def _subscription_event_id(name: str, payload: dict[str, Any], data: dict[str, Any]) -> str:
    raw = _first_value(
        payload,
        data,
        "transaction_id",
        "transactionId",
        "payment_id",
        "paymentId",
        "invoice_id",
        "invoiceId",
        "expires_at",
        "expiresAt",
        "created_at",
        "createdAt",
        "sent_at",
        "sentAt",
    ) or uuid.uuid4().hex
    return (
        "tribute:subscription:"
        f"{name}:"
        f"{_extract_subscription_id(payload)}:"
        f"{_extract_period_id(payload)}:"
        f"{_extract_telegram_user_id(payload)}:"
        f"{raw}"
    )


def _digital_product_external_ref(payload: dict[str, Any], data: dict[str, Any]) -> str:
    raw = _first_value(
        payload,
        data,
        "purchase_id",
        "purchaseId",
        "transaction_id",
        "transactionId",
        "payment_id",
        "paymentId",
        "invoice_id",
        "invoiceId",
        "product_id",
        "productId",
    ) or ""
    return f"digital_product:{raw}"


def _digital_product_event_id(name: str, payload: dict[str, Any], data: dict[str, Any]) -> str:
    raw = _first_value(
        payload,
        data,
        "purchase_id",
        "purchaseId",
        "transaction_id",
        "transactionId",
        "payment_id",
        "paymentId",
        "invoice_id",
        "invoiceId",
        "created_at",
        "createdAt",
        "sent_at",
        "sentAt",
    ) or uuid.uuid4().hex
    product_id = _first_value(payload, data, "product_id", "productId", "id") or ""
    return (
        "tribute:digital_product:"
        f"{name}:"
        f"{product_id}:"
        f"{_extract_telegram_user_id(payload)}:"
        f"{raw}"
    )


def _first_value(*sources_and_keys):
    sources = [item for item in sources_and_keys if isinstance(item, dict)]
    keys = [item for item in sources_and_keys if isinstance(item, str)]
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in {None, ""}:
                return value
    return None
