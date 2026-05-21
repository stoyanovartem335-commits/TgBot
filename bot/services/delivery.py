"""Final delivery: tokens + ZIP archive + message to user."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from ..config import ADMIN_ID, TG_CHANNEL_URL, ZIP_FILE_PATH
from ..database import insert_purchase
from ..keyboards import post_purchase_kb
from .token_service import TokenGenerationError, issue_tokens

log = logging.getLogger(__name__)

PAYMENT_METHOD_LABEL = {
    "stars": "Telegram Stars",
    "triboote": "Triboote",
    "requisites": "\u041f\u043e \u0440\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u0430\u043c",
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
    """Generate tokens, record purchase, send token + ZIP to user. Returns main token."""
    method_label = PAYMENT_METHOD_LABEL.get(payment_method, payment_method)

    try:
        tokens = await issue_tokens(plan_code, days, count=2)
    except TokenGenerationError as exc:
        log.error("Token generation failed for user %s: %s", user_id, exc)
        await bot.send_message(
            user_id,
            "\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0432\u044b\u0434\u0430\u0442\u044c \u0442\u043e\u043a\u0435\u043d \u2014 \u043e\u0431\u0440\u0430\u0442\u0438\u0442\u0435\u0441\u044c \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443.",
        )
        try:
            await bot.send_message(
                ADMIN_ID,
                f"\u26a0\ufe0f \u041e\u0448\u0438\u0431\u043a\u0430 \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438 \u0442\u043e\u043a\u0435\u043d\u0430 \u0434\u043b\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f {user_id}: {exc}",
            )
        except Exception:
            pass
        raise

    token, friend_token = tokens[0], tokens[1]

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
        "\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f: <b>\u0431\u0435\u0441\u0441\u0440\u043e\u0447\u043d\u044b\u0439</b>"
        if expires_at is None
        else f"\u0414\u0435\u0439\u0441\u0442\u0432\u0443\u0435\u0442 \u0434\u043e: <b>{expires_at.strftime('%d.%m.%Y %H:%M UTC')}</b>"
    )

    text = (
        "\u2705 <b>\u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430</b>\n\n"
        f"\u0422\u0430\u0440\u0438\u0444: <b>{plan_label}</b>\n"
        f"\u0421\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b: <b>{method_label}</b>\n"
        f"{expiry_line}\n\n"
        "\U0001f511 <b>\u0412\u0430\u0448 \u0442\u043e\u043a\u0435\u043d:</b>\n"
        f"<code>{token}</code>\n\n"
        "\U0001f381 <b>\u0422\u043e\u043a\u0435\u043d \u00ab\u0434\u043b\u044f \u0434\u0440\u0443\u0433\u0430\u00bb</b> (\u0442\u043e\u0442 \u0436\u0435 \u0441\u0440\u043e\u043a):\n"
        f"<code>{friend_token}</code>\n\n"
        f"\U0001f4d6 \u0412\u0441\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 \u2014 \u0432 \u043a\u0430\u043d\u0430\u043b\u0435:\n{TG_CHANNEL_URL}"
    )

    await bot.send_message(
        user_id,
        text,
        reply_markup=post_purchase_kb(),
        disable_web_page_preview=True,
    )

    # Send ZIP archive
    zip_path = Path(ZIP_FILE_PATH)
    if zip_path.exists():
        try:
            await bot.send_document(
                user_id,
                FSInputFile(zip_path, filename="Price_by_KALYVAN.zip"),
                caption="\U0001f4e6 \u0412\u0430\u0448 \u0430\u0440\u0445\u0438\u0432 \u0441\u043e \u0441\u043a\u0440\u0438\u043f\u0442\u043e\u043c. \u0420\u0430\u0441\u043f\u0430\u043a\u0443\u0439\u0442\u0435 \u0438 \u0441\u043b\u0435\u0434\u0443\u0439\u0442\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 \u0432 \u043a\u0430\u043d\u0430\u043b\u0435.",
            )
        except Exception as exc:
            log.error("Failed to send ZIP to user %s: %s", user_id, exc)
            await bot.send_message(
                user_id,
                "\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0430\u0440\u0445\u0438\u0432. \u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443.",
            )
    else:
        log.warning("ZIP file not found at %s", zip_path)

    log.info(
        "Delivered: user=%s plan=%s method=%s token=%s",
        user_id, plan_code, payment_method, token,
    )
    return token
