from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import ADMIN_ID
from ..database import get_latest_gsheets_request_for_user, insert_gsheets_request, latest_token_for_user
from ..keyboards import cancel_email_kb
from ..services.payment_review import user_ref_html

log = logging.getLogger(__name__)
router = Router(name="gsheets")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GSheetsFlow(StatesGroup):
    waiting_email = State()


def _admin_review_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"adm:gsheets_accept:{request_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:gsheets_reject:{request_id}"),
    ]])


@router.callback_query(F.data == "gsheets:request")
async def on_request(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.from_user is None:
        return

    token = await latest_token_for_user(call.from_user.id)
    if not token:
        await call.answer("Сначала оплатите тариф и получите токен", show_alert=True)
        return

    latest = await get_latest_gsheets_request_for_user(call.from_user.id)
    if latest and latest.get("status") == "pending":
        await call.answer("Заявка уже на проверке", show_alert=True)
        return
    if latest and latest.get("status") == "accepted":
        await call.answer("Доступ уже был подтвержден", show_alert=True)
        return

    await call.answer()
    await state.set_state(GSheetsFlow.waiting_email)
    await state.update_data(token=token)
    await call.message.answer(
        "📋 <b>Доступ к Google Sheets</b>\n\n"
        "Отправьте email Google-аккаунта одним сообщением. Администратор проверит заявку и добавит доступ к таблицам.",
        reply_markup=cancel_email_kb(),
    )


@router.callback_query(F.data == "gsheets:cancel")
async def on_cancel(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        return
    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_reply_markup(reply_markup=None)


@router.message(GSheetsFlow.waiting_email, F.text)
async def on_email(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    email = (message.text or "").strip()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        await message.answer("Это не похоже на email. Пришлите адрес в формате <code>user@gmail.com</code>.")
        return

    data = await state.get_data()
    token = data.get("token") or await latest_token_for_user(message.from_user.id)
    if not token:
        await state.clear()
        await message.answer("Не нашел активную покупку. Сначала оплатите тариф и получите токен.")
        return

    latest = await get_latest_gsheets_request_for_user(message.from_user.id)
    if latest and latest.get("status") in {"pending", "accepted"}:
        await state.clear()
        await message.answer("У вас уже есть активная заявка на доступ к Google Sheets.")
        return

    await state.clear()
    request_id = await insert_gsheets_request(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        email=email,
        token=token,
    )

    await message.answer(
        "✅ Заявка отправлена администратору.\n\n"
        f"Email: <code>{html.escape(email)}</code>\n"
        "После проверки вам придет сообщение в бот."
    )

    user_ref = user_ref_html(message.from_user.id, message.from_user.full_name, message.from_user.username)
    admin_text = (
        "📋 <b>Новая заявка на доступ к Google Sheets</b>\n\n"
        f"Пользователь: {user_ref}\n"
        f"Email: <code>{html.escape(email)}</code>\n"
        f"Токен: <code>{html.escape(token)}</code>\n"
        f"Заявка: <code>{request_id}</code>"
    )
    try:
        await message.bot.send_message(ADMIN_ID, admin_text, reply_markup=_admin_review_kb(request_id))
    except Exception:
        log.exception("Failed to notify admin about Google Sheets request")
