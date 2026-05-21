from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import ADMIN_ID
from ..database import (
    get_recent_purchases,
    get_settings,
    get_total_purchases,
    update_settings,
)
from ..services.api_client import create_subscription_token
from ..services.token_service import compute_expiration_str, generate_token

log = logging.getLogger(__name__)
router = Router(name="admin")

PLAN_CODES = ["1m", "2m", "3m", "6m", "forever"]
PLAN_LABELS = {"1m": "1 месяц", "2m": "2 месяца", "3m": "3 месяца", "6m": "6 месяцев", "forever": "Forever"}
PLAN_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 180, "forever": None}


class AdminFSM(StatesGroup):
    waiting_price_rub = State()
    waiting_discount_pct = State()


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id == ADMIN_ID


def _is_true(value) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on", "вкл")
    return bool(value)


def _status(value: bool) -> str:
    return "ВКЛ" if value else "ВЫКЛ"


async def _edit_or_send(message: Message | None, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        await message.answer(text, reply_markup=reply_markup)


def _admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Создать токен", callback_data="adm:create_token")],
        [InlineKeyboardButton(text="💰 Настроить цены", callback_data="adm:prices")],
        [InlineKeyboardButton(text="🎁 Акция / Промо", callback_data="adm:promo")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="🏆 Популярный тариф", callback_data="adm:settings")],
    ])


async def _admin_main_text(notice: str | None = None) -> str:
    settings = await get_settings()
    total = await get_total_purchases()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "🛠 <b>Панель администратора</b>\n\n"
        f"📊 Всего покупок: <b>{total}</b>\n\n"
        "💰 Текущие цены:\n"
    )
    for code in PLAN_CODES:
        text += f"  {PLAN_LABELS[code]}: {prices_rub.get(code, 0)} ₽ / {prices_stars.get(code, 0)} ⭐\n"
    return text


async def show_admin_main(target: Message, *, edit: bool = False, notice: str | None = None) -> None:
    text = await _admin_main_text(notice)
    if edit:
        await _edit_or_send(target, text, _admin_main_kb())
        return
    await target.answer(text, reply_markup=_admin_main_kb())


def _back_kb() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="↩️ Назад", callback_data="adm:back")


async def show_create_token_panel(message: Message | None, *, notice: str | None = None) -> None:
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "Выберите тариф для генерации токена:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=PLAN_LABELS[code], callback_data=f"adm:token:{code}")]
        for code in PLAN_CODES
    ])
    kb.inline_keyboard.append([_back_kb()])
    await _edit_or_send(message, text, kb)


async def show_prices_panel(message: Message | None, *, notice: str | None = None) -> None:
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "💰 <b>Текущие цены</b>\n\n"
    for code in PLAN_CODES:
        text += f"{PLAN_LABELS[code]}: {prices_rub.get(code, 0)} ₽ / {prices_stars.get(code, 0)} ⭐\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Изм. {PLAN_LABELS[code]}", callback_data=f"adm:setprice:{code}")]
        for code in PLAN_CODES
    ])
    kb.inline_keyboard.append([_back_kb()])
    await _edit_or_send(message, text, kb)


async def send_prices_panel(message: Message, *, notice: str | None = None) -> None:
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "💰 <b>Текущие цены</b>\n\n"
    for code in PLAN_CODES:
        text += f"{PLAN_LABELS[code]}: {prices_rub.get(code, 0)} ₽ / {prices_stars.get(code, 0)} ⭐\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Изм. {PLAN_LABELS[code]}", callback_data=f"adm:setprice:{code}")]
        for code in PLAN_CODES
    ])
    kb.inline_keyboard.append([_back_kb()])
    await message.answer(text, reply_markup=kb)


async def show_promo_panel(message: Message | None, *, notice: str | None = None) -> None:
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    promotion = settings.get("promotion", {})
    discount_enabled = _is_true(discounts.get("enabled", False))
    promo_enabled = _is_true(promotion.get("enabled", False))
    promo_text = promotion.get("text") or "Купи 1 токен → получи 1 токен для друга"

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "🎁 <b>Акции и промо</b>\n\n"
        f"Скидка: <b>{_status(discount_enabled)}</b> ({discounts.get('percentage', 0)}%)\n"
        f"1 токен тебе + 1 другу: <b>{_status(promo_enabled)}</b>\n"
        f"Текст: {promo_text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Выключить скидку" if discount_enabled else "🔄 Включить скидку", callback_data="adm:toggle_discount")],
        [InlineKeyboardButton(text="🎁 Выключить 1+1" if promo_enabled else "🎁 Включить 1+1", callback_data="adm:toggle_promo")],
        [InlineKeyboardButton(text="📈 Уст. % скидки", callback_data="adm:set_discount_pct")],
        [_back_kb()],
    ])
    await _edit_or_send(message, text, kb)


async def send_promo_panel(message: Message, *, notice: str | None = None) -> None:
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    promotion = settings.get("promotion", {})
    discount_enabled = _is_true(discounts.get("enabled", False))
    promo_enabled = _is_true(promotion.get("enabled", False))
    promo_text = promotion.get("text") or "Купи 1 токен → получи 1 токен для друга"

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "🎁 <b>Акции и промо</b>\n\n"
        f"Скидка: <b>{_status(discount_enabled)}</b> ({discounts.get('percentage', 0)}%)\n"
        f"1 токен тебе + 1 другу: <b>{_status(promo_enabled)}</b>\n"
        f"Текст: {promo_text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Выключить скидку" if discount_enabled else "🔄 Включить скидку", callback_data="adm:toggle_discount")],
        [InlineKeyboardButton(text="🎁 Выключить 1+1" if promo_enabled else "🎁 Включить 1+1", callback_data="adm:toggle_promo")],
        [InlineKeyboardButton(text="📈 Уст. % скидки", callback_data="adm:set_discount_pct")],
        [_back_kb()],
    ])
    await message.answer(text, reply_markup=kb)


def _format_paid_at(value: str) -> str:
    if not value:
        return "?"
    try:
        clean = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(clean).strftime("%d.%m.%Y | %H:%M")
    except Exception:
        try:
            date_part, time_part = value.split("T", 1)
            yyyy, mm, dd = date_part.split("-", 2)
            hh, minute = time_part.split(":", 2)[:2]
            return f"{dd}.{mm}.{yyyy} | {hh}:{minute}"
        except Exception:
            return value[:16]


async def show_stats_panel(message: Message | None) -> None:
    total = await get_total_purchases()
    recent = await get_recent_purchases(5)
    text = f"📈 <b>Статистика</b>\n\nВсего покупок: <b>{total}</b>\n\n"
    if recent:
        text += "Последние покупки:\n"
        for row in recent:
            paid_at = _format_paid_at(row.get("paid_at", ""))
            text += f"  {row.get('plan_code', '?')} | {row.get('payment_method', '?')} | {paid_at}\n"
    else:
        text += "Покупок пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]])
    await _edit_or_send(message, text, kb)


async def show_settings_panel(message: Message | None) -> None:
    settings = await get_settings()
    highlighted = settings.get("highlighted_tariff", "3m")
    text = f"🏆 <b>Популярный тариф</b>\n\nВыделенный тариф: <b>{PLAN_LABELS.get(highlighted, highlighted)}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅ ' if highlighted == code else ''}{PLAN_LABELS[code]}", callback_data=f"adm:set_highlight:{code}")]
        for code in PLAN_CODES
    ])
    kb.inline_keyboard.append([_back_kb()])
    await _edit_or_send(message, text, kb)


@router.message(F.text == "/adm")
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    await show_admin_main(message)


@router.callback_query(F.data == "adm:create_token")
async def adm_create_token(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_create_token_panel(call.message)


@router.callback_query(F.data.startswith("adm:token:"))
async def adm_generate_token(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    plan_code = call.data.split(":", 2)[2]
    token = generate_token()
    exp_str = compute_expiration_str(plan_code, PLAN_DAYS.get(plan_code))

    try:
        await create_subscription_token(
            key_part2=token,
            is_public=True,
            subscription_expiration=exp_str,
        )
    except Exception as exc:
        await show_create_token_panel(call.message, notice=f"❌ Ошибка: {exc}")
        return

    notice = (
        "✅ Токен создан:\n\n"
        f"Тариф: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
        f"Токен: <code>{token}</code>\n"
        f"Срок: {exp_str or 'Бессрочно'}"
    )
    await show_create_token_panel(call.message, notice=notice)


@router.callback_query(F.data == "adm:prices")
async def adm_prices(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_prices_panel(call.message)


@router.callback_query(F.data.startswith("adm:setprice:"))
async def adm_set_price(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    plan_code = call.data.split(":", 2)[2]
    await state.update_data(plan_code=plan_code)
    await state.set_state(AdminFSM.waiting_price_rub)
    await _edit_or_send(
        call.message,
        f"Отправьте новую цену для <b>{PLAN_LABELS.get(plan_code, plan_code)}</b> в формате <code>рубли/звезды</code> (например, <code>199/150</code>):",
        InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]),
    )


@router.message(AdminFSM.waiting_price_rub, F.text)
async def adm_save_price_rub(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    text = (message.text or "").strip()
    if "/" not in text:
        await message.answer("Пожалуйста, отправьте цену в формате <code>рубли/звезды</code>, например: <code>199/150</code>")
        return

    try:
        rub_raw, stars_raw = text.split("/", 1)
        rub = int(rub_raw.strip())
        stars = int(stars_raw.strip())
        if rub < 0 or stars < 0:
            raise ValueError
    except ValueError:
        await message.answer("Обе цены должны быть положительными целыми числами в формате <code>рубли/звезды</code>, например: <code>199/150</code>")
        return

    data = await state.get_data()
    plan_code = data.get("plan_code", "1m")
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})
    prices_rub[plan_code] = rub
    prices_stars[plan_code] = stars
    await update_settings({"prices_rub": prices_rub, "prices_stars": prices_stars})
    await state.clear()

    notice = (
        f"✅ Цены для {PLAN_LABELS.get(plan_code, plan_code)} успешно сохранены:\n"
        f"💵 Рубли: <b>{rub} ₽</b>\n"
        f"⭐ Telegram Stars: <b>{stars} ⭐</b>"
    )
    await send_prices_panel(message, notice=notice)


@router.callback_query(F.data == "adm:promo")
async def adm_promo(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_promo_panel(call.message)


@router.callback_query(F.data == "adm:toggle_discount")
async def adm_toggle_discount(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    discounts["enabled"] = not _is_true(discounts.get("enabled", False))
    await update_settings({"discounts": discounts})
    await call.answer("Скидка " + ("включена" if discounts["enabled"] else "выключена"))
    await show_promo_panel(call.message)


@router.callback_query(F.data == "adm:toggle_promo")
async def adm_toggle_promo(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    settings = await get_settings()
    promo = settings.get("promotion", {})
    promo.setdefault("text", "Купи 1 токен → получи 1 токен для друга")
    promo["enabled"] = not _is_true(promo.get("enabled", False))
    await update_settings({"promotion": promo})
    await call.answer("Промо " + ("включено" if promo["enabled"] else "выключено"))
    await show_promo_panel(call.message)


@router.callback_query(F.data == "adm:set_discount_pct")
async def adm_set_discount_pct(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await state.set_state(AdminFSM.waiting_discount_pct)
    await _edit_or_send(
        call.message,
        "Отправьте новый процент скидки (целое число, напр. 10):",
        InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]),
    )


@router.message(AdminFSM.waiting_discount_pct, F.text)
async def adm_save_discount_pct(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        pct = int((message.text or "").strip())
        if pct < 0 or pct > 100:
            raise ValueError
    except ValueError:
        await message.answer("Отправьте число от 0 до 100.")
        return

    settings = await get_settings()
    discounts = settings.get("discounts", {})
    discounts["percentage"] = pct
    await update_settings({"discounts": discounts})
    await state.clear()
    await send_promo_panel(message, notice=f"✅ Процент скидки установлен: <b>{pct}%</b>")


@router.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_stats_panel(call.message)


@router.callback_query(F.data == "adm:settings")
async def adm_settings(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_settings_panel(call.message)


@router.callback_query(F.data.startswith("adm:set_highlight:"))
async def adm_set_highlight(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    code = call.data.split(":", 2)[2]
    await update_settings({"highlighted_tariff": code})
    await call.answer(f"Выделенный тариф: {PLAN_LABELS.get(code, code)}")
    await show_settings_panel(call.message)


@router.callback_query(F.data == "adm:back")
async def adm_back(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await state.clear()
    await call.answer()
    if call.message:
        await show_admin_main(call.message, edit=True)


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
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") != "pending":
        await call.answer(f"Уже обработано: {pending.get('status')}", show_alert=True)
        if call.message is not None:
            await call.message.edit_reply_markup(reply_markup=None)
        return

    if decision == "ok":
        await deliver_purchase(
            call.bot,
            user_id=pending["user_id"],
            username=pending.get("username"),
            plan_code=pending["plan_code"],
            plan_label=PLAN_LABELS.get(pending["plan_code"], pending["plan_code"]),
            days=PLAN_DAYS.get(pending["plan_code"]),
            payment_method="requisites",
        )
        await mark_pending_status(payment_id, "completed")
        await call.answer("Подтверждено ✅")
        if call.message is not None:
            await call.message.edit_text(call.message.html_text + "\n\n<b>✅ Подтверждено</b>")
    elif decision == "no":
        await mark_pending_status(payment_id, "rejected")
        try:
            await call.bot.send_message(
                pending["user_id"],
                "❌ Заявка отклонена. Свяжитесь с поддержкой.",
            )
        except Exception:
            pass
        await call.answer("Отклонено")
        if call.message is not None:
            await call.message.edit_text(call.message.html_text + "\n\n<b>❌ Отклонено</b>")
