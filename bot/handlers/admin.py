"""Advanced admin panel (/adm)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import ADMIN_ID
from ..database import (
    get_settings,
    update_settings,
    get_total_purchases,
    count_users,
    get_recent_purchases,
)
from ..services.token_service import generate_token, compute_expiration_str
from ..services.api_client import create_subscription_token

log = logging.getLogger(__name__)
router = Router(name="admin")

PLAN_LABELS = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id == ADMIN_ID


class AdminFSM(StatesGroup):
    waiting_price_rub = State()
    waiting_price_stars = State()
    waiting_discount_pct = State()


@router.message(F.text == "/adm")
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    await show_admin_main(message)


async def show_admin_main(target, state: FSMContext | None = None) -> None:
    settings = await get_settings()
    total = await get_total_purchases()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})

    text = (
        "\U0001f6e0 <b>\u041f\u0430\u043d\u0435\u043b\u044c \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430</b>\n\n"
        f"\U0001f4ca \u0412\u0441\u0435\u0433\u043e \u043f\u043e\u043a\u0443\u043f\u043e\u043a: <b>{total}</b>\n\n"
        "\U0001f4b0 \u0422\u0435\u043a\u0443\u0449\u0438\u0435 \u0446\u0435\u043d\u044b:\n"
    )
    for code in ["1m", "2m", "3m", "6m", "forever"]:
        text += f"  {PLAN_LABELS[code]}: {prices_rub.get(code, 0)} \u20bd / {prices_stars.get(code, 0)} \u2b50\n"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f511 \u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0442\u043e\u043a\u0435\u043d", callback_data="adm:create_token")],
        [InlineKeyboardButton(text="\U0001f4b0 \u041d\u0430\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u0446\u0435\u043d\u044b", callback_data="adm:prices")],
        [InlineKeyboardButton(text="\U0001f3c6 \u0410\u043a\u0446\u0438\u044f / \u041f\u0440\u043e\u043c\u043e", callback_data="adm:promo")],
        [InlineKeyboardButton(text="\U0001f4c8 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430", callback_data="adm:stats")],
        [InlineKeyboardButton(text="\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438", callback_data="adm:settings")],
    ])
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb)
    else:
        await target.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:create_token")
async def adm_create_token(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"adm:token:{code}")]
        for code, label in PLAN_LABELS.items()
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="\u21a9\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="adm:back")])
    await call.message.edit_text("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0434\u043b\u044f \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438 \u0442\u043e\u043a\u0435\u043d\u0430:", reply_markup=kb)


@router.callback_query(F.data.startswith("adm:token:"))
async def adm_generate_token(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    plan_code = call.data.split(":", 2)[2]
    days = PLAN_DAYS.get(plan_code)
    token = generate_token()
    exp_str = compute_expiration_str(plan_code, days)

    try:
        await create_subscription_token(
            key_part2=token,
            is_public=True,
            subscription_expiration=exp_str,
        )
        await call.message.answer(
            f"\u2705 \u0422\u043e\u043a\u0435\u043d \u0441\u043e\u0437\u0434\u0430\u043d:\n\n"
            f"\u0422\u0430\u0440\u0438\u0444: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
            f"\u0422\u043e\u043a\u0435\u043d: <code>{token}</code>\n"
            f"\u0421\u0440\u043e\u043a: {exp_str or '\u0411\u0435\u0441\u0441\u0440\u043e\u0447\u043d\u043e'}"
        )
    except Exception as exc:
        await call.message.answer(f"\u274c \u041e\u0448\u0438\u0431\u043a\u0430: {exc}")


@router.callback_query(F.data == "adm:prices")
async def adm_prices(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})

    text = "\U0001f4b0 <b>\u0422\u0435\u043a\u0443\u0449\u0438\u0435 \u0446\u0435\u043d\u044b</b>\n\n"
    for code in ["1m", "2m", "3m", "6m", "forever"]:
        text += f"{PLAN_LABELS[code]}: {prices_rub.get(code, 0)} \u20bd / {prices_stars.get(code, 0)} \u2b50\n"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"\u0418\u0437\u043c. {PLAN_LABELS[c]}", callback_data=f"adm:setprice:{c}")]
        for c in ["1m", "2m", "3m", "6m", "forever"]
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="\u21a9\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="adm:back")])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("adm:setprice:"))
async def adm_set_price(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    plan_code = call.data.split(":", 2)[2]
    await state.update_data(plan_code=plan_code)
    await state.set_state(AdminFSM.waiting_price_rub)
    await call.message.answer(
        f"\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u043d\u043e\u0432\u0443\u044e \u0446\u0435\u043d\u0443 (\u20bd) \u0434\u043b\u044f <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>:\n\u0422\u043e\u043b\u044c\u043a\u043e \u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e."
    )


@router.message(AdminFSM.waiting_price_rub, F.text)
async def adm_save_price_rub(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        new_price = int(message.text.strip())
    except ValueError:
        await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e.")
        return
    data = await state.get_data()
    plan_code = data.get("plan_code", "1m")
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_rub[plan_code] = new_price
    await update_settings({"prices_rub": prices_rub})
    await state.update_data(rub_price=new_price)
    await state.set_state(AdminFSM.waiting_price_stars)
    await message.answer(
        f"\u2705 \u0426\u0435\u043d\u0430 (\u20bd) \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430: {new_price} \u20bd.\n\n"
        f"\u0422\u0435\u043f\u0435\u0440\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0446\u0435\u043d\u0443 \u0432 \u2b50 \u0434\u043b\u044f <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>:"
    )


@router.message(AdminFSM.waiting_price_stars, F.text)
async def adm_save_price_stars(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        new_price = int(message.text.strip())
    except ValueError:
        await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e.")
        return
    data = await state.get_data()
    plan_code = data.get("plan_code", "1m")
    rub_price = data.get("rub_price", "?")
    settings = await get_settings()
    prices_stars = settings.get("prices_stars", {})
    prices_stars[plan_code] = new_price
    await update_settings({"prices_stars": prices_stars})
    await state.clear()
    await message.answer(
        f"\u2705 \u0426\u0435\u043d\u044b \u0434\u043b\u044f {PLAN_LABELS[plan_code]} \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b:\n"
        f"{rub_price} \u20bd / {new_price} \u2b50"
    )


@router.callback_query(F.data == "adm:promo")
async def adm_promo(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    promotion = settings.get("promotion", {})

    text = (
        "\U0001f3c6 <b>\u0410\u043a\u0446\u0438\u0438 \u0438 \u0441\u043a\u0438\u0434\u043a\u0438</b>\n\n"
        f"\u0421\u043a\u0438\u0434\u043a\u0430: {'\u0412\u041a\u041b' if discounts.get('enabled') else '\u0412\u042b\u041a\u041b'} ({discounts.get('percentage', 0)}%)\n"
        f"\u041f\u0440\u043e\u043c\u043e: {'\u0412\u041a\u041b' if promotion.get('enabled') else '\u0412\u042b\u041a\u041b'}\n"
        f"\u0422\u0435\u043a\u0441\u0442: {promotion.get('text', '\u2014')}"
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f504 \u0421\u043a\u0438\u0434\u043a\u0430 " + ("\u0412\u041a\u041b" if discounts.get('enabled') else "\u0412\u042b\u041a\u041b"), callback_data="adm:toggle_discount")],
        [InlineKeyboardButton(text="\U0001f504 \u041f\u0440\u043e\u043c\u043e " + ("\u0412\u041a\u041b" if promotion.get('enabled') else "\u0412\u042b\u041a\u041b"), callback_data="adm:toggle_promo")],
        [InlineKeyboardButton(text="\U0001f4c8 \u0423\u0441\u0442. % \u0441\u043a\u0438\u0434\u043a\u0438", callback_data="adm:set_discount_pct")],
        [InlineKeyboardButton(text="\u21a9\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="adm:back")],
    ])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:toggle_discount")
async def adm_toggle_discount(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    discounts["enabled"] = not discounts.get("enabled", False)
    await update_settings({"discounts": discounts})
    await call.answer("\u0421\u043a\u0438\u0434\u043a\u0430 " + ("\u0432\u043a\u043b\u044e\u0447\u0435\u043d\u0430" if discounts["enabled"] else "\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d\u0430"))
    await adm_promo(call)


@router.callback_query(F.data == "adm:toggle_promo")
async def adm_toggle_promo(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    settings = await get_settings()
    promo = settings.get("promotion", {})
    promo["enabled"] = not promo.get("enabled", False)
    await update_settings({"promotion": promo})
    await call.answer("\u041f\u0440\u043e\u043c\u043e " + ("\u0432\u043a\u043b\u044e\u0447\u0435\u043d" if promo["enabled"] else "\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d"))
    await adm_promo(call)


@router.callback_query(F.data == "adm:set_discount_pct")
async def adm_set_discount_pct(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await state.set_state(AdminFSM.waiting_discount_pct)
    await call.message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0446\u0435\u043d\u0442 \u0441\u043a\u0438\u0434\u043a\u0438 (\u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e, \u043d\u0430\u043f\u0440. 10):")


@router.message(AdminFSM.waiting_discount_pct, F.text)
async def adm_save_discount_pct(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        pct = int(message.text.strip())
        if pct < 0 or pct > 100:
            raise ValueError
    except ValueError:
        await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0447\u0438\u0441\u043b\u043e \u043e\u0442 0 \u0434\u043e 100.")
        return
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    discounts["percentage"] = pct
    await update_settings({"discounts": discounts})
    await state.clear()
    await message.answer(f"\u2705 \u041f\u0440\u043e\u0446\u0435\u043d\u0442 \u0441\u043a\u0438\u0434\u043a\u0438 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d: {pct}%")


@router.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    total = await get_total_purchases()
    recent = await get_recent_purchases(5)

    text = f"\U0001f4c8 <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430</b>\n\n\u0412\u0441\u0435\u0433\u043e \u043f\u043e\u043a\u0443\u043f\u043e\u043a: <b>{total}</b>\n\n"
    if recent:
        text += "\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u043f\u043e\u043a\u0443\u043f\u043a\u0438:\n"
        for r in recent:
            paid_at_raw = r.get('paid_at', '')
            if paid_at_raw:
                try:
                    dt = datetime.fromisoformat(paid_at_raw)
                    paid_at_str = dt.strftime('%d.%m.%Y | %H:%M')
                except Exception:
                    paid_at_str = paid_at_raw[:16]
            else:
                paid_at_str = '?'
            text += f"  {r.get('plan_code', '?')} | {r.get('payment_method', '?')} | {paid_at_str}\n"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u21a9\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="adm:back")],
    ])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:settings")
async def adm_settings(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    settings = await get_settings()
    highlighted = settings.get("highlighted_tariff", "3m")

    text = f"\u2699\ufe0f <b>\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438</b>\n\n\u0412\u044b\u0434\u0435\u043b\u0435\u043d\u043d\u044b\u0439 \u0442\u0430\u0440\u0438\u0444: <b>{PLAN_LABELS.get(highlighted, highlighted)}</b>"
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'\u2705 ' if highlighted == c else ''}{PLAN_LABELS[c]}", callback_data=f"adm:set_highlight:{c}")]
        for c in ["1m", "2m", "3m", "6m", "forever"]
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="\u21a9\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="adm:back")])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("adm:set_highlight:"))
async def adm_set_highlight(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    code = call.data.split(":", 2)[2]
    await update_settings({"highlighted_tariff": code})
    await call.answer(f"\u0412\u044b\u0434\u0435\u043b\u0451\u043d\u043d\u044b\u0439 \u0442\u0430\u0440\u0438\u0444: {PLAN_LABELS.get(code, code)}")
    await adm_settings(call)


@router.callback_query(F.data == "adm:back")
async def adm_back(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await state.clear()
    await call.answer()
    await show_admin_main(call.message, call)


@router.callback_query(F.data.startswith("adm:ok:") | F.data.startswith("adm:no:"))
async def on_admin_decision(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    from ..database import get_pending, mark_pending_status
    from ..services.delivery import deliver_purchase

    parts = call.data.split(":", 2)
    if len(parts) != 3:
        return
    _, decision, payment_id = parts

    pending = await get_pending(payment_id)
    if pending is None:
        await call.answer("\u0417\u0430\u044f\u0432\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430", show_alert=True)
        return
    if pending.get("status") != "pending":
        await call.answer(f"\u0423\u0436\u0435 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e: {pending.get('status')}", show_alert=True)
        if call.message is not None:
            await call.message.edit_reply_markup(reply_markup=None)
        return

    if decision == "ok":
        plan_labels = {"1m": "1 \u043c\u0435\u0441\u044f\u0446", "2m": "2 \u043c\u0435\u0441\u044f\u0446\u0430", "3m": "3 \u043c\u0435\u0441\u044f\u0446\u0430", "6m": "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", "forever": "Forever"}
        plan_days = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}
        await deliver_purchase(
            call.bot,
            user_id=pending["user_id"],
            username=pending.get("username"),
            plan_code=pending["plan_code"],
            plan_label=plan_labels.get(pending["plan_code"], pending["plan_code"]),
            days=plan_days.get(pending["plan_code"]),
            payment_method="requisites",
        )
        await mark_pending_status(payment_id, "completed")
        await call.answer("\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e \u2705")
        if call.message is not None:
            await call.message.edit_text(call.message.html_text + "\n\n<b>\u2705 \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e</b>")
    elif decision == "no":
        await mark_pending_status(payment_id, "rejected")
        try:
            await call.bot.send_message(
                pending["user_id"],
                "\u274c \u0417\u0430\u044f\u0432\u043a\u0430 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u0430. \u0421\u0432\u044f\u0436\u0438\u0442\u0435\u0441\u044c \u0441 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u043e\u0439.",
            )
        except Exception:
            pass
        await call.answer("\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e")
        if call.message is not None:
            await call.message.edit_text(call.message.html_text + "\n\n<b>\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e</b>")
