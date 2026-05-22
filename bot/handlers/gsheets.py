from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import ADMIN_ID
from ..database import insert_gsheets_request, latest_token_for_user
from ..keyboards import cancel_email_kb

log = logging.getLogger(__name__)
router = Router(name="gsheets")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GSheetsFlow(StatesGroup):
    waiting_email = State()


@router.callback_query(F.data == "gsheets:request")
async def on_request(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.from_user is None:
        return
    await call.answer()
    await state.set_state(GSheetsFlow.waiting_email)
    await call.message.answer(
        "📋 <b>Запрос Google Sheets</b>\n\n"
        "Отправьте свой Gmail одним сообщением — администратор откроет доступ в течение суток.",
        reply_markup=cancel_email_kb(),
    )


@router.callback_query(F.data == "gsheets:cancel")
async def on_cancel(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        return
    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Заявка отменена.")


@router.message(GSheetsFlow.waiting_email, F.text)
async def on_email(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    email = (message.text or "").strip()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        await message.answer("Это не похоже на email. Пришлите в формате <code>user@gmail.com</code>.")
        return

    await state.clear()
    token = await latest_token_for_user(message.from_user.id)
    req_id = await insert_gsheets_request(
        user_id=message.from_user.id,
        username=message.from_user.username,
        email=email,
        token=token,
    )

    await message.answer(f"✅ Заявка принята.\n\nEmail: <code>{email}</code>\nАдминистратор откроет доступ в течение суток.")

    uname = message.from_user.username
    user_ref = f"@{uname}" if uname else f"id={message.from_user.id}"
    admin_text = (
        "📋 <b>Новая заявка на Google Sheets</b>\n\n"
        f"Пользователь: {user_ref}\n"
        f"Имя: {message.from_user.full_name}\n"
        f"Email: <code>{email}</code>\n"
        f"Токен: <code>{token or '—'}</code>\n"
        f"Заявка #{req_id}"
    )
    try:
        await message.bot.send_message(ADMIN_ID, admin_text)
    except Exception:
        log.exception("Failed to notify admin about GSheets request")
