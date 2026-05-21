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
        "\U0001f4cb <b>\u0417\u0430\u043f\u0440\u043e\u0441 Google Sheets</b>\n\n"
        "\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0441\u0432\u043e\u0439 Gmail \u043e\u0434\u043d\u0438\u043c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435\u043c \u2014 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440 \u043e\u0442\u043a\u0440\u043e\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f \u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 \u0441\u0443\u0442\u043e\u043a.",
        reply_markup=cancel_email_kb(),
    )


@router.callback_query(F.data == "gsheets:cancel")
async def on_cancel(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        return
    await state.clear()
    await call.answer("\u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("\u0417\u0430\u044f\u0432\u043a\u0430 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430.")


@router.message(GSheetsFlow.waiting_email, F.text)
async def on_email(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    email = (message.text or "").strip()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        await message.answer("\u042d\u0442\u043e \u043d\u0435 \u043f\u043e\u0445\u043e\u0436\u0435 \u043d\u0430 email. \u041f\u0440\u0438\u0448\u043b\u0438\u0442\u0435 \u0432 \u0444\u043e\u0440\u043c\u0430\u0442\u0435 <code>user@gmail.com</code>.")
        return

    await state.clear()
    token = await latest_token_for_user(message.from_user.id)
    req_id = await insert_gsheets_request(
        user_id=message.from_user.id,
        username=message.from_user.username,
        email=email,
        token=token,
    )

    await message.answer(f"\u2705 \u0417\u0430\u044f\u0432\u043a\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430.\n\nEmail: <code>{email}</code>\n\u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440 \u043e\u0442\u043a\u0440\u043e\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f \u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 \u0441\u0443\u0442\u043e\u043a.")

    uname = message.from_user.username
    user_ref = f"@{uname}" if uname else f"id={message.from_user.id}"
    admin_text = (
        "\U0001f4cb <b>\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u044f\u0432\u043a\u0430 \u043d\u0430 Google Sheets</b>\n\n"
        f"\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c: {user_ref}\n"
        f"\u0418\u043c\u044f: {message.from_user.full_name}\n"
        f"Email: <code>{email}</code>\n"
        f"\u0422\u043e\u043a\u0435\u043d: <code>{token or '\u2014'}</code>\n"
        f"\u0417\u0430\u044f\u0432\u043a\u0430 #{req_id}"
    )
    try:
        await message.bot.send_message(ADMIN_ID, admin_text)
    except Exception:
        log.exception("Failed to notify admin about GSheets request")
