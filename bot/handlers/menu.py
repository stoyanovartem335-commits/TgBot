from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import TG_CHANNEL_URL, support_url
from ..keyboards import BTN_NEWS, BTN_SUPPORT, BTN_MAIN, news_link_kb, support_link_kb

router = Router(name="menu")


@router.message(F.text == BTN_NEWS)
async def on_news(message: Message) -> None:
    await message.answer(
        "📰 <b>Новости Рынка</b>\n\n"
        f"Свежие новости — в нашем Telegram-канале:\n{TG_CHANNEL_URL}",
        reply_markup=news_link_kb(),
        disable_web_page_preview=False,
    )


@router.message(F.text == BTN_SUPPORT)
async def on_support(message: Message) -> None:
    await message.answer(
        "💬 <b>Тех поддержка</b>\n\n"
        f"По любым вопросам — напишите нам:\n{support_url()}",
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
