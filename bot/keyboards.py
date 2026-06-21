from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from .config import TG_CHANNEL_URL, WEBAPP_URL, support_url

BTN_MAIN = "📋 Ознакомиться/купить скрипт"
BTN_NEWS = "📰 Новости Рынка"
BTN_SUPPORT = "💬 Тех поддержка"
BTN_MY_REQUESTS = "🧾 Мои заявки"
BTN_PAY_STARS = "⭐ Telegram Stars"
BTN_PAY_TRIBUTE = "💳 Tribute"
BTN_PAY_FUNPAY = "🛒 Fun Pay"
BTN_PAY_REQUISITES = "💳 Реквизиты РБ 🇧🇾 | РФ 🇷🇺"


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=BTN_MAIN, web_app=WebAppInfo(url=f"{WEBAPP_URL}/")))
    builder.button(text=BTN_MY_REQUESTS)
    builder.button(text=BTN_NEWS)
    builder.button(text=BTN_SUPPORT)
    builder.adjust(1, 1, 2)
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
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
            [InlineKeyboardButton(text=BTN_PAY_STARS, callback_data=f"pay:stars:{plan_code}")],
            [InlineKeyboardButton(text=BTN_PAY_TRIBUTE, callback_data=f"pay:triboote:{plan_code}")],
            [InlineKeyboardButton(text=BTN_PAY_FUNPAY, callback_data=f"pay:funpay:{plan_code}")],
            [InlineKeyboardButton(text=BTN_PAY_REQUISITES, callback_data=f"pay:requisites:{plan_code}")],
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
