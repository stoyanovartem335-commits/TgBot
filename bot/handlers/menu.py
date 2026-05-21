from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import TG_CHANNEL_URL, support_url
from ..keyboards import BTN_NEWS, BTN_SUPPORT, BTN_MAIN, news_link_kb, support_link_kb

router = Router(name="menu")


@router.message(F.text == BTN_NEWS)
async def on_news(message: Message) -> None:
    await message.answer(
        "\U0001f4f0 <b>\u041d\u043e\u0432\u043e\u0441\u0442\u0438 \u0420\u044b\u043d\u043a\u0430</b>\n\n"
        f"\u0421\u0432\u0435\u0436\u0438\u0435 \u043d\u043e\u0432\u043e\u0441\u0442\u0438 \u2014 \u0432 \u043d\u0430\u0448\u0435\u043c Telegram-\u043a\u0430\u043d\u0430\u043b\u0435:\n{TG_CHANNEL_URL}",
        reply_markup=news_link_kb(),
        disable_web_page_preview=False,
    )


@router.message(F.text == BTN_SUPPORT)
async def on_support(message: Message) -> None:
    await message.answer(
        "\U0001f4ac <b>\u0422\u0435\u0445 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430</b>\n\n"
        f"\u041f\u043e \u043b\u044e\u0431\u044b\u043c \u0432\u043e\u043f\u0440\u043e\u0441\u0430\u043c \u2014 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u043d\u0430\u043c:\n{support_url()}",
        reply_markup=support_link_kb(),
        disable_web_page_preview=True,
    )


@router.message(F.text == BTN_MAIN)
async def on_main(message: Message) -> None:
    pass


@router.callback_query(F.data == "pay:cancel")
async def on_payment_cancel(call: CallbackQuery) -> None:
    await call.answer("Отменено")
    if call.message:
        await call.message.edit_text("Покупка отменена. Вы можете открыть витрину и выбрать тариф заново.")
