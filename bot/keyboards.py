from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from .config import TG_CHANNEL_URL, WEBAPP_URL, support_url

BTN_MAIN = "\U0001f4cb \u041e\u0437\u043d\u0430\u043a\u043e\u043c\u0438\u0442\u044c\u0441\u044f/\u043a\u0443\u043f\u0438\u0442\u044c \u0441\u043a\u0440\u0438\u043f\u0442"
BTN_NEWS = "\U0001f4f0 \u041d\u043e\u0432\u043e\u0441\u0442\u0438 \u0420\u044b\u043d\u043a\u0430"
BTN_SUPPORT = "\U0001f4ac \u0422\u0435\u0445 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430"


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
            [InlineKeyboardButton(text="\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u043d\u0430\u043b", url=TG_CHANNEL_URL)]
        ]
    )


def support_link_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u041d\u0430\u043f\u0438\u0441\u0430\u0442\u044c \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443", url=support_url())]
        ]
    )


def payment_methods_kb(plan_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2b50 Telegram Stars", callback_data=f"pay:stars:{plan_code}")],
            [InlineKeyboardButton(text="\U0001f4b3 Triboote", callback_data=f"pay:triboote:{plan_code}")],
            [InlineKeyboardButton(text="\U0001f3e6 \u041f\u043e \u0440\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u0430\u043c", callback_data=f"pay:requisites:{plan_code}")],
            [InlineKeyboardButton(text="\u21a9\ufe0f \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", callback_data="pay:cancel")],
        ]
    )


def i_paid_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2705 \u042f \u043e\u043f\u043b\u0430\u0442\u0438\u043b", callback_data=f"paid:{payment_id}")]
        ]
    )


def admin_review_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c", callback_data=f"adm:ok:{payment_id}"),
                InlineKeyboardButton(text="\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c", callback_data=f"adm:no:{payment_id}"),
            ]
        ]
    )


def post_purchase_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\U0001f4d6 \u0418\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u044f (Telegram-\u043a\u0430\u043d\u0430\u043b)", url=TG_CHANNEL_URL)],
            [InlineKeyboardButton(text="\U0001f4cb \u0417\u0430\u043f\u0440\u043e\u0441\u0438\u0442\u044c Google Sheets", callback_data="gsheets:request")],
        ]
    )


def cancel_email_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u21a9\ufe0f \u041e\u0442\u043c\u0435\u043d\u0430", callback_data="gsheets:cancel")]
        ]
    )
