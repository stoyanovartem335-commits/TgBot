from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from ..config import ADMIN_ID, TG_CHANNEL_URL, ZIP_FILE_PATH
from ..database import insert_purchase
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
) -> str:
    method_label = PAYMENT_METHOD_LABEL.get(payment_method, payment_method)

    promo_enabled, _ = await get_promotion_status()

    try:
        tokens = await issue_tokens(plan_code, days, count=2 if promo_enabled else 1)
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

    from datetime import datetime, timedelta, timezone
    paid_at = datetime.now(timezone.utc)
    expires_at = paid_at + timedelta(days=days) if days else None

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
