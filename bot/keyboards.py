from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from .config import TG_CHANNEL_URL, WEBAPP_URL, support_url

BTN_MAIN = "📋 Ознакомиться/купить скрипт"
BTN_NEWS = "📰 Новости Рынка"
BTN_SUPPORT = "💬 Тех поддержка"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_MAIN, web_app=WebAppInfo(url=f"{WEBAPP_URL}/"))],
            [KeyboardButton(text=BTN_NEWS), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def news_link_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть канал", url=TG_CHANNEL_URL)]
        ]
    )


def support_link_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать в поддержку", url=support_url())]
        ]
    )


def payment_methods_kb(plan_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay:stars:{plan_code}")],
            [InlineKeyboardButton(text="💳 Triboote", callback_data=f"pay:triboote:{plan_code}")],
            [InlineKeyboardButton(text="🏦 По реквизитам", callback_data=f"pay:requisites:{plan_code}")],
            [InlineKeyboardButton(text="↩️ Отменить", callback_data="pay:cancel")],
        ]
    )


def i_paid_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid:{payment_id}")]
        ]
    )


def admin_review_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm:ok:{payment_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:no:{payment_id}"),
            ]
        ]
    )


def post_purchase_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Инструкция (Telegram-канал)", url=TG_CHANNEL_URL)],
            [InlineKeyboardButton(text="📋 Запросить Google Sheets", callback_data="gsheets:request")],
        ]
    )


def cancel_email_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="gsheets:cancel")]
        ]
    )
