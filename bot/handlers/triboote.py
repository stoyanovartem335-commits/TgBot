from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

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
    get_latest_pending_for_user,
    get_pending,
    get_pending_by_external_ref,
    get_settings,
    mark_pending_processing,
    mark_pending_status,
)
from ..services.delivery import deliver_purchase, renew_latest_purchase
from ..services.settings_service import price_with_active_discount

log = logging.getLogger(__name__)
router = Router(name="triboote")

PLAN_LABELS = {
    "1m": "1 месяц",
    "2m": "2 месяца",
    "3m": "3 месяца",
    "6m": "6 месяцев",
    "forever": "Forever",
}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}
PLAN_CODES = tuple(PLAN_LABELS.keys())

_PLAN_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    "forever": (r"\bforever\b", r"\blifetime\b", r"навсегда", r"бессроч"),
    "6m": (r"\b6\s*(m|mo|month|months)\b", r"6\s*мес", r"6\s*месяц", r"\b180\s*(д|day|days)\b", r"half\s*year"),
    "3m": (r"\b3\s*(m|mo|month|months)\b", r"3\s*мес", r"3\s*месяц", r"\b90\s*(д|day|days)\b", r"quarter"),
    "2m": (r"\b2\s*(m|mo|month|months)\b", r"2\s*мес", r"2\s*месяц", r"\b60\s*(д|day|days)\b"),
    "1m": (r"\b1\s*(m|mo|month)\b", r"1\s*мес", r"1\s*месяц", r"\b30\s*(д|day|days)\b"),
}


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

    if not TRIBUTE_SUBSCRIPTION_URL:
        await call.answer("Tribute ссылка не настроена", show_alert=True)
        await call.message.answer(
            "⚠️ Tribute ссылка на подписку не настроена.\n\n"
            "Админу нужно добавить в env переменную <code>TRIBUTE_SUBSCRIPTION_URL</code>."
        )
        try:
            await call.bot.send_message(
                ADMIN_ID,
                "⚠️ Пользователь нажал оплату через Tribute, но <code>TRIBUTE_SUBSCRIPTION_URL</code> пустой.",
            )
        except Exception:
            log.exception("Failed to notify admin about missing Tribute subscription URL")
        return

    await call.answer("Открываю Tribute...")
    payment_id = f"tribute:checkout:{call.from_user.id}:{uuid.uuid4().hex}"
    await create_pending(
        payment_id=payment_id,
        user_id=call.from_user.id,
        username=call.from_user.username,
        plan_code=plan_code,
        payment_method="triboote",
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате в Tribute", url=TRIBUTE_SUBSCRIPTION_URL)]]
    )
    await call.message.answer(
        f"Вы выбрали: <b>{label}</b>\n"
        f"Цена в боте: <b>{amount} ₽</b>\n\n"
        "В Tribute откроется окно подписки с тарифами. "
        "Если там выберете другой срок, бот выдаст доступ по фактически оплаченному тарифу.",
        reply_markup=kb,
    )


async def complete_from_webhook(bot: Bot, payment_id: str) -> bool:
    pending = await get_pending(payment_id) or await get_pending_by_external_ref(payment_id)
    if pending is None:
        log.warning("Tribute webhook unknown payment_id=%s", payment_id)
        return False
    return await _complete_pending(bot, pending, renew=False)


async def complete_from_tribute_event(bot: Bot, data: dict[str, Any]) -> bool:
    name = str(data.get("name") or data.get("event") or data.get("type") or "").lower()
    payload = _extract_payload(data)

    if data.get("test_event") == "test_event":
        return True

    if name in {"new_subscription", "subscription_created", "subscription.paid", "subscription_paid"}:
        return await _complete_subscription_event(bot, name, payload, data, renew=False)

    if name in {"renewed_subscription", "subscription_renewed", "subscription.renewed", "subscription_rebill"}:
        return await _complete_subscription_event(bot, name, payload, data, renew=True)

    if name in {"cancelled_subscription", "subscription_cancelled", "subscription.cancelled"}:
        log.info("Tribute subscription cancelled: %s", payload)
        return True

    status = str(payload.get("status") or data.get("status") or "").lower()
    payment_id = _first_value(payload, data, "uuid", "external_id", "payment_id", "id")
    if status in {"paid", "succeeded", "success", "completed", "payment.success"} and payment_id:
        return await complete_from_webhook(bot, str(payment_id))

    log.info("Tribute webhook ignored name=%s status=%s payload=%s", name, status, payload)
    return True


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
        latest_pending = await get_latest_pending_for_user(user_id=user_id, payment_method="triboote")
        if latest_pending is not None:
            plan_code = latest_pending.get("plan_code")

    if plan_code not in PLAN_CODES:
        log.warning("Tribute subscription cannot map plan: %s", payload)
        return False

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

    product_name = str(
        payload.get("product_name")
        or payload.get("period_name")
        or payload.get("tariff_name")
        or payload.get("title")
        or ""
    ).strip()
    if product_name:
        plan_from_name = _plan_from_name(product_name)
        if plan_from_name:
            return plan_from_name

    return await _plan_from_amount(payload)


def _extract_payload(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload", "data", "object"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return data


def _extract_telegram_user_id(payload: dict[str, Any]) -> int:
    values = (
        payload.get("telegram_user_id"),
        payload.get("telegramUserId"),
        payload.get("tg_user_id"),
        payload.get("user_id"),
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
    tg_slug = _telegram_slug(TG_CHANNEL_URL)
    if tg_slug:
        allowed_names.add(_normalize_subject_name(tg_slug))
    if allowed_names and channel_name not in allowed_names:
        return False

    subscription_id = _extract_subscription_id(payload)
    if TRIBUTE_ALLOWED_SUBSCRIPTION_IDS and subscription_id not in TRIBUTE_ALLOWED_SUBSCRIPTION_IDS:
        return False

    period_id = _extract_period_id(payload)
    allowed_period_ids = {str(value).strip() for value in TRIBUTE_PERIOD_IDS.values() if str(value).strip()}
    if allowed_period_ids and period_id not in allowed_period_ids:
        return False

    return True


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


def _first_value(*sources_and_keys):
    sources = [item for item in sources_and_keys if isinstance(item, dict)]
    keys = [item for item in sources_and_keys if isinstance(item, str)]
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in {None, ""}:
                return value
    return None
