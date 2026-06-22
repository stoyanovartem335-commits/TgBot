from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import ADMIN_ID
from ..database import (
    count_gsheets_requests,
    count_manual_payment_requests,
    delete_payment_block,
    get_active_payment_block,
    get_gsheets_request,
    get_pending,
    get_recent_purchases,
    get_settings,
    list_active_payment_blocks,
    list_gsheets_requests,
    list_manual_payment_requests,
    set_payment_block,
    get_total_purchases,
    update_gsheets_request_status,
    update_settings,
)
from ..services.api_client import create_subscription_token
from ..services.payment_review import format_until, method_label, parse_block_duration, user_ref_html
from ..services.plans import PLAN_CODES, PLAN_DAYS, PLAN_LABELS
from ..services.settings_service import normalize_discounts
from ..services.token_service import compute_expiration_str, generate_token

log = logging.getLogger(__name__)
router = Router(name="admin")
PAYMENT_REQUESTS_PAGE_SIZE = 10
GSHEETS_REQUESTS_PAGE_SIZE = 10

class AdminFSM(StatesGroup):
    waiting_price_rub = State()
    waiting_discount_pct = State()
    waiting_plan_discount_pct = State()
    waiting_payment_ban_duration = State()


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
        [InlineKeyboardButton(text="🧾 Заявки оплат", callback_data="adm:payment_requests")],
        [InlineKeyboardButton(text="📋 Google Sheets", callback_data="adm:gsheets")],
        [InlineKeyboardButton(text="⛔ Баны оплат", callback_data="adm:payment_bans")],
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


def _safe_page(value: str | int | None) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _pages_count(total: int, page_size: int = PAYMENT_REQUESTS_PAGE_SIZE) -> int:
    return max(1, (max(0, total) + page_size - 1) // page_size)


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


def _plan_discount_label(discounts: dict, code: str) -> str:
    plan_discount = discounts["plans"].get(code, {"enabled": False, "percentage": 0})
    plan_enabled = _is_true(plan_discount.get("enabled", False)) and int(plan_discount.get("percentage", 0) or 0) > 0
    global_enabled = _is_true(discounts.get("enabled", False)) and int(discounts.get("percentage", 0) or 0) > 0
    if plan_enabled:
        return f"своя {plan_discount.get('percentage', 0)}%"
    if global_enabled:
        return f"общая {discounts.get('percentage', 0)}%"
    return "нет"


def _promo_panel_markup(discounts: dict, promo_enabled: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🌐 Выключить общую скидку" if discounts["enabled"] else "🌐 Включить общую скидку",
                callback_data="adm:toggle_discount",
            )
        ],
        [InlineKeyboardButton(text="📈 % общей скидки", callback_data="adm:set_discount_pct")],
    ]
    for code in PLAN_CODES:
        plan_discount = discounts["plans"].get(code, {"enabled": False, "percentage": 0})
        plan_enabled = _is_true(plan_discount.get("enabled", False)) and int(plan_discount.get("percentage", 0) or 0) > 0
        rows.append([
            InlineKeyboardButton(
                text=f"{PLAN_LABELS[code]}: выкл свою" if plan_enabled else f"{PLAN_LABELS[code]}: вкл свою",
                callback_data=f"adm:toggle_plan_discount:{code}",
            ),
            InlineKeyboardButton(text=f"% {PLAN_LABELS[code]}", callback_data=f"adm:set_plan_discount_pct:{code}"),
        ])
    rows.extend([
        [InlineKeyboardButton(text="🎁 Выключить 1+1" if promo_enabled else "🎁 Включить 1+1", callback_data="adm:toggle_promo")],
        [_back_kb()],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _promo_panel_payload(notice: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    settings = await get_settings()
    discounts = normalize_discounts(settings.get("discounts", {}))
    promotion = settings.get("promotion", {})
    promo_enabled = _is_true(promotion.get("enabled", False))
    promo_text = promotion.get("text") or "Купи 1 токен → получи 1 токен для друга"

    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "🎁 <b>Акции и промо</b>\n\n"
        f"Общая скидка: <b>{_status(discounts['enabled'])}</b> ({discounts['percentage']}%)\n\n"
        "Индивидуальные скидки:\n"
    )
    for code in PLAN_CODES:
        text += f"• {PLAN_LABELS[code]}: <b>{_plan_discount_label(discounts, code)}</b>\n"
    text += (
        "\n"
        f"1 токен тебе + 1 другу: <b>{_status(promo_enabled)}</b>\n"
        f"Текст: {promo_text}"
    )
    return text, _promo_panel_markup(discounts, promo_enabled)


async def show_promo_panel(message: Message | None, *, notice: str | None = None) -> None:
    text, kb = await _promo_panel_payload(notice)
    await _edit_or_send(message, text, kb)


async def send_promo_panel(message: Message, *, notice: str | None = None) -> None:
    text, kb = await _promo_panel_payload(notice)
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


def _request_status_label(status: str) -> str:
    return {
        "pending": "ожидает скриншот",
        "pending_review": "на проверке",
        "completed": "принята",
        "rejected": "отклонена",
        "canceled": "отменена",
        "failed": "ошибка",
    }.get(status, status or "?")


def _request_button_title(item: dict) -> str:
    method = method_label(item.get("payment_method", "?"))
    plan = PLAN_LABELS.get(item.get("plan_code"), item.get("plan_code", "?"))
    status = _request_status_label(item.get("status", "?"))
    user = item.get("username") or item.get("full_name") or item.get("user_id")
    return f"{status} | {method} | {plan} | {user}"


async def show_payment_requests_panel(message: Message | None, *, notice: str | None = None, page: int = 0) -> None:
    total = await count_manual_payment_requests()
    pages = _pages_count(total)
    page = min(_safe_page(page), pages - 1)
    items = await list_manual_payment_requests(page=page, limit=PAYMENT_REQUESTS_PAGE_SIZE)
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "🧾 <b>Заявки оплат</b>\n\n"
    if not items:
        text += "Заявок пока нет."
        await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]))
        return
    rows = [
        [InlineKeyboardButton(text=_request_button_title(item), callback_data=f"adm:req:{item['payment_id']}:{page}")]
        for item in items
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="<", callback_data=f"adm:payment_requests:{page - 1}"))
    if (page + 1) * PAYMENT_REQUESTS_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text=">", callback_data=f"adm:payment_requests:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_back_kb()])
    await _edit_or_send(
        message,
        text + f"Страница <b>{page + 1}/{pages}</b>\n\nПоследние заявки:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    return
    items = await list_manual_payment_requests(page=0, limit=PAYMENT_REQUESTS_PAGE_SIZE)
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "🧾 <b>Заявки оплат</b>\n\n"
    if not items:
        text += "Заявок пока нет."
        await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]))
        return
    rows = [
        [InlineKeyboardButton(text=_request_button_title(item), callback_data=f"adm:req:{item['payment_id']}")]
        for item in items
    ]
    rows.append([_back_kb()])
    await _edit_or_send(message, text + "Последние заявки:", InlineKeyboardMarkup(inline_keyboard=rows))


async def show_payment_request_detail(message: Message | None, item: dict, *, notice: str | None = None, page: int = 0) -> None:
    payment_id = item["payment_id"]
    method = item.get("payment_method", "?")
    plan_code = item.get("plan_code", "?")
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "🧾 <b>Заявка оплаты</b>\n\n"
        f"Способ: <b>{method_label(method)}</b>\n"
        f"Тариф: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
        f"Сумма: <b>{item.get('amount_rub', 0)} ₽</b>\n"
        f"Статус: <b>{_request_status_label(item.get('status', '?'))}</b>\n"
        f"Пользователь: {user_ref_html(int(item.get('user_id', 0)), item.get('full_name'), item.get('username'))}\n"
    )
    if item.get("payer_name"):
        text += f"Плательщик: <b>{html.escape(str(item.get('payer_name')))}</b>\n"
    text += f"Payment ID: <code>{html.escape(payment_id)}</code>"

    rows = []
    if item.get("proof_file_id"):
        rows.append([InlineKeyboardButton(text="🖼 Показать скриншот", callback_data=f"adm:req_photo:{payment_id}")])
    if item.get("status") == "pending_review":
        rows.append([
            InlineKeyboardButton(text="✅ Принять", callback_data=f"manual:ok:{payment_id}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"manual:no:{payment_id}"),
        ])
        rows.append([InlineKeyboardButton(text="⛔ Заблокировать способ", callback_data=f"manual:block:{payment_id}")])
    rows.append([InlineKeyboardButton(text="↩️ К заявкам", callback_data=f"adm:payment_requests:{_safe_page(page)}")])
    await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=rows))


def _gsheets_status_label(status: str) -> str:
    return {
        "pending": "на проверке",
        "accepted": "принята",
        "rejected": "отклонена",
    }.get(status, status or "?")


def _gsheets_button_title(item: dict) -> str:
    status = _gsheets_status_label(item.get("status", "?"))
    email = item.get("email", "?")
    user = item.get("username") or item.get("full_name") or item.get("user_id")
    return f"{status} | {email} | {user}"


async def show_gsheets_requests_panel(message: Message | None, *, notice: str | None = None, page: int = 0) -> None:
    total = await count_gsheets_requests()
    pages = _pages_count(total, GSHEETS_REQUESTS_PAGE_SIZE)
    page = min(_safe_page(page), pages - 1)
    items = await list_gsheets_requests(page=page, limit=GSHEETS_REQUESTS_PAGE_SIZE)
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "📋 <b>Заявки Google Sheets</b>\n\n"
    if not items:
        text += "Заявок пока нет."
        await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]))
        return

    rows = [
        [InlineKeyboardButton(text=_gsheets_button_title(item), callback_data=f"adm:gsheets_req:{item['_id']}:{page}")]
        for item in items
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="<", callback_data=f"adm:gsheets:{page - 1}"))
    if (page + 1) * GSHEETS_REQUESTS_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text=">", callback_data=f"adm:gsheets:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_back_kb()])
    await _edit_or_send(
        message,
        text + f"Страница <b>{page + 1}/{pages}</b>\n\nВыберите заявку:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def show_gsheets_request_detail(message: Message | None, item: dict, *, notice: str | None = None, page: int = 0) -> None:
    request_id = str(item["_id"])
    user_id = int(item.get("user_id", 0))
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "📋 <b>Заявка Google Sheets</b>\n\n"
        f"Статус: <b>{_gsheets_status_label(item.get('status', '?'))}</b>\n"
        f"Пользователь: {user_ref_html(user_id, item.get('full_name'), item.get('username'))}\n"
        f"Email: <code>{html.escape(str(item.get('email', '')))}</code>\n"
        f"Токен: <code>{html.escape(str(item.get('token') or '—'))}</code>\n"
        f"Дата: <b>{_format_paid_at(str(item.get('requested_at') or ''))}</b>\n"
        f"ID: <code>{html.escape(request_id)}</code>"
    )
    rows = []
    if item.get("status") == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Принять", callback_data=f"adm:gsheets_accept:{request_id}:{page}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:gsheets_reject:{request_id}:{page}"),
        ])
    rows.append([InlineKeyboardButton(text="↩️ К заявкам", callback_data=f"adm:gsheets:{_safe_page(page)}")])
    await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=rows))


def _block_button_title(block: dict) -> str:
    full_name = (block.get("full_name") or "").strip()
    username = (block.get("username") or "").strip()
    user = full_name or (f"@{username}" if username else str(block.get("user_id", "")))
    return f"{method_label(block.get('payment_method', '?'))} | {user}"


async def show_payment_bans_panel(message: Message | None, *, notice: str | None = None) -> None:
    blocks = await list_active_payment_blocks()
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "⛔ <b>Баны оплат</b>\n\n"
    if not blocks:
        text += "Активных блокировок нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]])
        await _edit_or_send(message, text, kb)
        return

    text += "Выберите пользователя для управления блокировкой:"
    rows = []
    for block in blocks:
        method = block.get("payment_method", "")
        user_id = int(block.get("user_id", 0))
        rows.append([InlineKeyboardButton(text=_block_button_title(block), callback_data=f"adm:ban:{method}:{user_id}")])
    rows.append([_back_kb()])
    await _edit_or_send(message, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def show_payment_ban_detail(message: Message | None, user_id: int, method: str, *, notice: str | None = None) -> None:
    block = await get_active_payment_block(user_id, method)
    if not block:
        await show_payment_bans_panel(message, notice="Блокировка уже не активна.")
        return
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += (
        "⛔ <b>Блокировка оплаты</b>\n\n"
        f"Способ: <b>{method_label(method)}</b>\n"
        f"Пользователь: {user_ref_html(user_id, block.get('full_name'), block.get('username'))}\n"
        f"Действует до: <b>{format_until(block.get('expires_at'))}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕒 Изменить срок", callback_data=f"adm:ban_set:{method}:{user_id}")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data=f"adm:ban_del:{method}:{user_id}")],
        [InlineKeyboardButton(text="↩️ К списку", callback_data="adm:payment_bans")],
    ])
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
    discounts = normalize_discounts(settings.get("discounts", {}))
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
    discounts = normalize_discounts(settings.get("discounts", {}))
    discounts["percentage"] = pct
    await update_settings({"discounts": discounts})
    await state.clear()
    await send_promo_panel(message, notice=f"✅ Процент скидки установлен: <b>{pct}%</b>")


@router.callback_query(F.data.startswith("adm:toggle_plan_discount:"))
async def adm_toggle_plan_discount(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    code = (call.data or "").rsplit(":", 1)[-1]
    if code not in PLAN_CODES:
        await call.answer("Тариф не найден", show_alert=True)
        return
    settings = await get_settings()
    discounts = normalize_discounts(settings.get("discounts", {}))
    plan_discount = discounts["plans"][code]
    current_enabled = _is_true(plan_discount.get("enabled", False)) and int(plan_discount.get("percentage", 0) or 0) > 0
    if current_enabled:
        plan_discount["enabled"] = False
    else:
        if int(plan_discount.get("percentage", 0) or 0) <= 0:
            plan_discount["percentage"] = discounts["percentage"] if int(discounts.get("percentage", 0) or 0) > 0 else 10
        plan_discount["enabled"] = True
    await update_settings({"discounts": discounts})
    await call.answer(f"{PLAN_LABELS.get(code, code)}: {'своя скидка включена' if plan_discount['enabled'] else 'своя скидка выключена'}")
    await show_promo_panel(call.message)


@router.callback_query(F.data.startswith("adm:set_plan_discount_pct:"))
async def adm_set_plan_discount_pct(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    code = (call.data or "").rsplit(":", 1)[-1]
    if code not in PLAN_CODES:
        await call.answer("Тариф не найден", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminFSM.waiting_plan_discount_pct)
    await state.update_data(discount_plan_code=code)
    await _edit_or_send(
        call.message,
        f"Отправьте процент скидки для тарифа <b>{PLAN_LABELS.get(code, code)}</b> (0-100). Если указать 0, своя скидка тарифа выключится:",
        InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]),
    )


@router.message(AdminFSM.waiting_plan_discount_pct, F.text)
async def adm_save_plan_discount_pct(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    data = await state.get_data()
    code = data.get("discount_plan_code")
    if code not in PLAN_CODES:
        await state.clear()
        await message.answer("Тариф не найден.")
        return
    try:
        pct = int((message.text or "").strip())
        if pct < 0 or pct > 100:
            raise ValueError
    except ValueError:
        await message.answer("Отправьте число от 0 до 100.")
        return

    settings = await get_settings()
    discounts = normalize_discounts(settings.get("discounts", {}))
    discounts["plans"][code]["percentage"] = pct
    discounts["plans"][code]["enabled"] = pct > 0
    await update_settings({"discounts": discounts})
    await state.clear()
    if pct > 0:
        notice = f"✅ Для тарифа <b>{PLAN_LABELS.get(code, code)}</b> установлена своя скидка: <b>{pct}%</b>"
    else:
        notice = f"✅ Своя скидка для тарифа <b>{PLAN_LABELS.get(code, code)}</b> выключена"
    await send_promo_panel(message, notice=notice)


@router.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_stats_panel(call.message)


@router.callback_query(F.data == "adm:gsheets")
async def adm_gsheets(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_gsheets_requests_panel(call.message)


@router.callback_query(F.data.startswith("adm:gsheets:"))
async def adm_gsheets_page(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":", 2)
    page = _safe_page(parts[2] if len(parts) > 2 else 0)
    await call.answer()
    await show_gsheets_requests_panel(call.message, page=page)


@router.callback_query(F.data.startswith("adm:gsheets_req:"))
async def adm_gsheets_detail(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":")
    request_id = parts[2] if len(parts) > 2 else ""
    page = _safe_page(parts[3] if len(parts) > 3 else 0)
    item = await get_gsheets_request(request_id)
    if item is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    await call.answer()
    await show_gsheets_request_detail(call.message, item, page=page)


@router.callback_query(F.data.startswith("adm:gsheets_accept:"))
async def adm_gsheets_accept(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":")
    request_id = parts[2] if len(parts) > 2 else ""
    page = _safe_page(parts[3] if len(parts) > 3 else 0)
    item = await update_gsheets_request_status(request_id, "accepted", call.from_user.id)
    if item is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    try:
        await call.bot.send_message(
            int(item["user_id"]),
            "✅ Заявка на доступ к Google Sheets принята.\n\n"
            "Если таблицы еще не открываются, подождите несколько минут и попробуйте снова.",
        )
    except Exception:
        log.exception("Failed to notify user about accepted Google Sheets request")
    await call.answer("Принято")
    await show_gsheets_request_detail(call.message, item, notice="✅ Заявка принята.", page=page)


@router.callback_query(F.data.startswith("adm:gsheets_reject:"))
async def adm_gsheets_reject(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":")
    request_id = parts[2] if len(parts) > 2 else ""
    page = _safe_page(parts[3] if len(parts) > 3 else 0)
    item = await update_gsheets_request_status(request_id, "rejected", call.from_user.id)
    if item is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    try:
        await call.bot.send_message(
            int(item["user_id"]),
            "❌ Заявка на доступ к Google Sheets отклонена.\n\n"
            "Проверьте email и отправьте заявку заново, если допустили ошибку.",
        )
    except Exception:
        log.exception("Failed to notify user about rejected Google Sheets request")
    await call.answer("Отклонено")
    await show_gsheets_request_detail(call.message, item, notice="❌ Заявка отклонена.", page=page)


@router.callback_query(F.data == "adm:payment_requests")
async def adm_payment_requests(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_payment_requests_panel(call.message)


@router.callback_query(F.data.startswith("adm:payment_requests:"))
async def adm_payment_requests_page(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":", 2)
    page = _safe_page(parts[2] if len(parts) > 2 else 0)
    await call.answer()
    await show_payment_requests_panel(call.message, page=page)


@router.callback_query(F.data.startswith("adm:req:"))
async def adm_payment_request_detail(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = (call.data or "").split(":")
    payment_id = parts[2] if len(parts) > 2 else ""
    page = _safe_page(parts[3] if len(parts) > 3 else 0)
    item = await get_pending(payment_id)
    if item is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    await call.answer()
    await show_payment_request_detail(call.message, item, page=page)


@router.callback_query(F.data.startswith("adm:req_photo:"))
async def adm_payment_request_photo(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    payment_id = call.data.split(":", 2)[2]
    item = await get_pending(payment_id)
    if item is None or not item.get("proof_file_id"):
        await call.answer("Скриншот не найден", show_alert=True)
        return
    await call.answer()
    await call.message.answer_photo(
        item["proof_file_id"],
        caption=f"Скриншот по заявке <code>{payment_id}</code>",
    )


@router.callback_query(F.data == "adm:payment_bans")
async def adm_payment_bans(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    await call.answer()
    await show_payment_bans_panel(call.message)


@router.callback_query(F.data.startswith("adm:ban:"))
async def adm_payment_ban_detail(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = call.data.split(":", 3)
    if len(parts) != 4:
        return
    _, _, method, user_id_raw = parts
    await call.answer()
    await show_payment_ban_detail(call.message, int(user_id_raw), method)


@router.callback_query(F.data.startswith("adm:ban_del:"))
async def adm_payment_ban_delete(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = call.data.split(":", 3)
    if len(parts) != 4:
        return
    _, _, method, user_id_raw = parts
    await delete_payment_block(int(user_id_raw), method)
    await call.answer("Разбанен")
    await show_payment_bans_panel(call.message, notice="✅ Блокировка снята.")


@router.callback_query(F.data.startswith("adm:ban_set:"))
async def adm_payment_ban_set(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id if call.from_user else None):
        return
    parts = call.data.split(":", 3)
    if len(parts) != 4:
        return
    _, _, method, user_id_raw = parts
    await state.update_data(payment_ban_method=method, payment_ban_user_id=int(user_id_raw))
    await state.set_state(AdminFSM.waiting_payment_ban_duration)
    await call.answer()
    await _edit_or_send(
        call.message,
        "Введите новый срок блокировки: <code>6ч</code>, <code>12h</code>, <code>2д</code> или <code>3d</code>.",
        InlineKeyboardMarkup(inline_keyboard=[[_back_kb()]]),
    )


@router.message(AdminFSM.waiting_payment_ban_duration, F.text)
async def adm_payment_ban_save_duration(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parsed = parse_block_duration(message.text or "")
    if parsed is None:
        await message.answer("Введите срок в формате <code>6ч</code>, <code>12h</code>, <code>2д</code> или <code>3d</code>.")
        return
    delta, label = parsed
    data = await state.get_data()
    method = data.get("payment_ban_method")
    user_id = int(data.get("payment_ban_user_id") or 0)
    block = await get_active_payment_block(user_id, method)
    if not block:
        await state.clear()
        await show_payment_bans_panel(message, notice="Блокировка уже не активна.")
        return
    expires_at = datetime.now(timezone.utc) + delta
    await set_payment_block(
        user_id=user_id,
        payment_method=method,
        expires_at=expires_at,
        username=block.get("username"),
        full_name=block.get("full_name"),
        admin_id=message.from_user.id,
    )
    await state.clear()
    await show_payment_bans_panel(message, notice=f"✅ Срок блокировки изменён на {label}.")


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
