from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from ..config import ADMIN_ID, TG_CHANNEL_URL, ZIP_FILE_PATH
from ..database import (
    get_latest_purchase_for_user,
    insert_purchase,
    update_api_token_expiration,
    update_purchase_expiration,
)
from ..keyboards import post_purchase_kb
from .settings_service import get_promotion_status
from .token_service import TokenGenerationError, issue_tokens

log = logging.getLogger(__name__)

PAYMENT_METHOD_LABEL = {
    "stars": "Telegram Stars",
    "triboote": "Tribute",
    "requisites": "По реквизитам",
}


async def deliver_purchase(
    bot: Bot,
    *,
    user_id: int,
    username: str | None,
    plan_code: str,
    plan_label: str,
    days: int | None,
    payment_method: str,
    expires_at_override=None,
) -> str:
    method_label = PAYMENT_METHOD_LABEL.get(payment_method, payment_method)

    promo_enabled, _ = await get_promotion_status()
    from datetime import datetime, timedelta, timezone
    paid_at = datetime.now(timezone.utc)
    expires_at = None if days is None else expires_at_override or paid_at + timedelta(days=days)

    try:
        tokens = await issue_tokens(plan_code, days, count=2 if promo_enabled else 1, expires_at=expires_at)
    except TokenGenerationError as exc:
        log.error("Token generation failed for user %s: %s", user_id, exc)
        await bot.send_message(
            user_id,
            "⚠️ Не удалось выдать токен — обратитесь в поддержку.",
        )
        try:
            await bot.send_message(
                ADMIN_ID,
                f"⚠️ Ошибка генерации токена для пользователя {user_id}: {exc}",
            )
        except Exception:
            pass
        raise

    token = tokens[0]
    friend_token = tokens[1] if promo_enabled and len(tokens) > 1 else None

    await insert_purchase(
        user_id=user_id,
        username=username,
        plan_code=plan_code,
        token=token,
        friend_token=friend_token,
        payment_method=payment_method,
        expires_at=expires_at,
    )

    expiry_line = (
        "Срок действия: <b>бессрочный</b>"
        if expires_at is None
        else f"Действует до: <b>{expires_at.strftime('%d.%m.%Y %H:%M UTC')}</b>"
    )

    text = (
        "✅ <b>Оплата подтверждена</b>\n\n"
        f"Тариф: <b>{plan_label}</b>\n"
        f"Способ оплаты: <b>{method_label}</b>\n"
        f"{expiry_line}\n\n"
        "🔑 <b>Ваш токен:</b>\n"
        f"<code>{token}</code>\n\n"
    )
    if friend_token:
        text += (
            "🎁 <b>Токен «для друга»</b> (тот же срок):\n"
            f"<code>{friend_token}</code>\n\n"
        )
    text += f"📖 Все инструкции — в канале:\n{TG_CHANNEL_URL}"

    await bot.send_message(
        user_id,
        text,
        reply_markup=post_purchase_kb(),
        disable_web_page_preview=True,
    )

    zip_path = Path(ZIP_FILE_PATH)
    if zip_path.exists():
        try:
            await bot.send_document(
                user_id,
                FSInputFile(zip_path, filename="Price_by_KALYVAN.zip"),
                caption="📦 Ваш архив со скриптом. Распакуйте и следуйте инструкциям в канале.",
            )
        except Exception as exc:
            log.error("Failed to send ZIP to user %s: %s", user_id, exc)
            await bot.send_message(
                user_id,
                "⚠️ Не удалось отправить архив. Напишите в поддержку.",
            )
    else:
        log.warning("ZIP file not found at %s", zip_path)

    log.info(
        "Delivered: user=%s plan=%s method=%s token=%s",
        user_id, plan_code, payment_method, token,
    )
    return token


async def renew_latest_purchase(
    bot: Bot,
    *,
    user_id: int,
    username: str | None,
    plan_code: str,
    plan_label: str,
    days: int | None,
    payment_method: str,
    expires_at_override=None,
) -> bool:
    purchase = await get_latest_purchase_for_user(user_id, payment_method=payment_method)
    if not purchase:
        await deliver_purchase(
            bot,
            user_id=user_id,
            username=username,
            plan_code=plan_code,
            plan_label=plan_label,
            days=days,
            payment_method=payment_method,
            expires_at_override=expires_at_override,
        )
        return True

    if days is None:
        await update_purchase_expiration(purchase["_id"], plan_code=plan_code, expires_at=None)
        await update_api_token_expiration(purchase["token"], None)
        await bot.send_message(
            user_id,
            "✅ <b>Подписка продлена</b>\n\n"
            f"Тариф: <b>{plan_label}</b>\n"
            "Ваш токен теперь бессрочный:\n"
            f"<code>{purchase['token']}</code>",
            reply_markup=post_purchase_kb(),
            disable_web_page_preview=True,
        )
        return True

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    raw_expires = purchase.get("expires_at")
    current_expires = None
    if raw_expires:
        try:
            current_expires = datetime.fromisoformat(str(raw_expires))
            if current_expires.tzinfo is None:
                current_expires = current_expires.replace(tzinfo=timezone.utc)
        except ValueError:
            current_expires = None
    base = current_expires if current_expires and current_expires > now else now
    expires_at = expires_at_override or base + timedelta(days=days)
    expiration_str = expires_at.strftime("%d.%m.%Y")

    await update_purchase_expiration(purchase["_id"], plan_code=plan_code, expires_at=expires_at)
    await update_api_token_expiration(purchase["token"], expiration_str)
    friend_token = purchase.get("friend_token")
    if friend_token:
        await update_api_token_expiration(friend_token, expiration_str)

    await bot.send_message(
        user_id,
        "✅ <b>Подписка продлена</b>\n\n"
        f"Тариф: <b>{plan_label}</b>\n"
        f"Действует до: <b>{expires_at.strftime('%d.%m.%Y %H:%M UTC')}</b>\n\n"
        "Ваш токен остаётся прежним:\n"
        f"<code>{purchase['token']}</code>",
        reply_markup=post_purchase_kb(),
        disable_web_page_preview=True,
    )
    return True
