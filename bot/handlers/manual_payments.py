from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import ADMIN_ID, FUNPAY_URLS, REQUISITES_CARD
from ..database import (
    create_pending,
    get_active_manual_pending,
    get_active_payment_block,
    get_pending,
    get_settings,
    list_manual_requests_for_user,
    mark_pending_status,
    set_payment_block,
    update_pending_fields,
)
from ..keyboards import BTN_MY_REQUESTS, BTN_PAY_FUNPAY, BTN_PAY_REQUISITES, main_menu_kb
from ..services.delivery import deliver_purchase
from ..services.payment_review import format_until, method_label, parse_block_duration, user_full_name, user_ref_html
from ..services.plans import PLAN_DAYS, PLAN_LABELS, plan_code_by_label
from ..services.settings_service import price_with_active_discount

router = Router(name="manual_payments")


class ManualPaymentFSM(StatesGroup):
    waiting_funpay_screenshot = State()
    waiting_requisites_payer = State()
    waiting_requisites_screenshot = State()
    waiting_block_duration = State()


def _plan_code_from_payment_text(text: str, prefix: str) -> str | None:
    raw = text.removeprefix(prefix).strip()
    if raw.startswith("—"):
        raw = raw[1:].strip()
    return plan_code_by_label(raw)


def _manual_paid_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"manual:paid:{payment_id}")],
        [InlineKeyboardButton(text="↩️ Отменить заявку", callback_data=f"manual:cancel:{payment_id}")],
    ])


def _admin_review_kb(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"manual:ok:{payment_id}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"manual:no:{payment_id}"),
        ],
        [InlineKeyboardButton(text="⛔ Заблокировать способ", callback_data=f"manual:block:{payment_id}")],
    ])


async def _plan_price_rub(plan_code: str) -> int:
    settings = await get_settings()
    prices = settings.get("prices_rub", {})
    return await price_with_active_discount(int(prices.get(plan_code, 0) or 0))


async def _active_pending_text(user_id: int) -> str | None:
    pending = await get_active_manual_pending(user_id)
    if not pending:
        return None
    plan = PLAN_LABELS.get(pending.get("plan_code"), pending.get("plan_code", "?"))
    method = method_label(pending.get("payment_method", "?"))
    return (
        "У вас уже есть заявка на проверке.\n\n"
        f"Способ: <b>{method}</b>\n"
        f"Тариф: <b>{plan}</b>\n\n"
        "Дождитесь решения администратора или отмените прошлую заявку, если она ещё не отправлена на проверку."
    )


async def _block_text(user_id: int, method: str) -> str | None:
    block = await get_active_payment_block(user_id, method)
    if not block:
        return None
    return (
        f"Способ оплаты <b>{method_label(method)}</b> временно заблокирован.\n\n"
        f"Блокировка действует до: <b>{format_until(block.get('expires_at'))}</b>"
    )


def _request_title(item: dict) -> str:
    method = method_label(item.get("payment_method", "?"))
    plan = PLAN_LABELS.get(item.get("plan_code"), item.get("plan_code", "?"))
    status = _status_label(item.get("status", "?"))
    return f"{method} | {plan} | {status}"


def _request_detail_text(item: dict) -> str:
    method = item.get("payment_method", "?")
    plan_code = item.get("plan_code", "?")
    text = (
        "🧾 <b>Заявка на оплату</b>\n\n"
        f"Способ: <b>{method_label(method)}</b>\n"
        f"Тариф: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
        f"Сумма: <b>{item.get('amount_rub', 0)} ₽</b>\n"
        f"Статус: <b>{_status_label(item.get('status', '?'))}</b>\n"
        f"ID: <code>{html.escape(item.get('payment_id', ''))}</code>"
    )
    if item.get("payer_name"):
        text += f"\nПлательщик: <b>{html.escape(item.get('payer_name'))}</b>"
    return text


async def _show_my_requests(target: Message, user_id: int, *, notice: str | None = None) -> None:
    items = await list_manual_requests_for_user(user_id)
    text = ""
    if notice:
        text += f"{notice}\n\n"
    text += "🧾 <b>Мои заявки</b>\n\n"
    if not items:
        await target.answer(text + "Заявок пока нет.", reply_markup=main_menu_kb())
        return
    rows = [
        [InlineKeyboardButton(text=_request_title(item), callback_data=f"manual:view:{item['payment_id']}")]
        for item in items
    ]
    await target.answer(text + "Выберите заявку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _show_request_detail(call: CallbackQuery, item: dict) -> None:
    payment_id = item["payment_id"]
    status = item.get("status")
    rows = []
    if status in {"pending", "pending_review"}:
        rows.append([InlineKeyboardButton(text="✏️ Изменить скриншот", callback_data=f"manual:edit:{payment_id}")])
        rows.append([InlineKeyboardButton(text="↩️ Отменить заявку", callback_data=f"manual:cancel:{payment_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🗑 Скрыть из списка", callback_data=f"manual:hide:{payment_id}")])
    rows.append([InlineKeyboardButton(text="↩️ К моим заявкам", callback_data="manual:my")])
    if call.message:
        await call.message.edit_text(_request_detail_text(item), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == BTN_MY_REQUESTS)
async def on_my_requests_message(message: Message) -> None:
    if message.from_user is None:
        return
    await _show_my_requests(message, message.from_user.id)


@router.callback_query(F.data == "manual:my")
async def on_my_requests_callback(call: CallbackQuery) -> None:
    if call.from_user is None:
        return
    await call.answer()
    if call.message:
        items = await list_manual_requests_for_user(call.from_user.id)
        text = "🧾 <b>Мои заявки</b>\n\n"
        if not items:
            await call.message.edit_text(text + "Заявок пока нет.")
            return
        rows = [
            [InlineKeyboardButton(text=_request_title(item), callback_data=f"manual:view:{item['payment_id']}")]
            for item in items
        ]
        await call.message.edit_text(text + "Выберите заявку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("manual:view:"))
async def on_my_request_detail(call: CallbackQuery) -> None:
    if call.from_user is None:
        return
    payment_id = call.data.split(":", 2)[2]
    item = await get_pending(payment_id)
    if item is None or item.get("user_id") != call.from_user.id or item.get("user_hidden") is True:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    await call.answer()
    await _show_request_detail(call, item)


@router.callback_query(F.data.startswith("manual:hide:"))
async def on_my_request_hide(call: CallbackQuery) -> None:
    if call.from_user is None:
        return
    payment_id = call.data.split(":", 2)[2]
    item = await get_pending(payment_id)
    if item is None or item.get("user_id") != call.from_user.id:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if item.get("status") in {"pending", "pending_review"}:
        await call.answer("Сначала отмените активную заявку", show_alert=True)
        return
    await update_pending_fields(payment_id, {"user_hidden": True})
    await call.answer("Скрыто")
    if call.message:
        await call.message.edit_text("Заявка скрыта из вашего списка.")


@router.callback_query(F.data.startswith("manual:edit:"))
async def on_my_request_edit(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None:
        return
    payment_id = call.data.split(":", 2)[2]
    item = await get_pending(payment_id)
    if item is None or item.get("user_id") != call.from_user.id:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if item.get("status") not in {"pending", "pending_review"}:
        await call.answer("Эту заявку уже нельзя редактировать", show_alert=True)
        return
    await update_pending_fields(payment_id, {"status": "pending"})
    await state.update_data(payment_id=payment_id)
    await call.answer()
    if item.get("payment_method") == "requisites" and not item.get("payer_name"):
        await state.set_state(ManualPaymentFSM.waiting_requisites_payer)
        if call.message:
            await call.message.answer("Напишите имя и фамилию плательщика.")
        return
    if item.get("payment_method") == "requisites":
        await state.set_state(ManualPaymentFSM.waiting_requisites_screenshot)
    else:
        await state.set_state(ManualPaymentFSM.waiting_funpay_screenshot)
    if call.message:
        await call.message.answer("Пришлите новый скриншот оплаты одним изображением.")


def _status_label(status: str) -> str:
    return {
        "pending": "ожидает скриншот",
        "pending_review": "на проверке",
        "completed": "принята",
        "rejected": "отклонена",
        "canceled": "отменена",
        "failed": "ошибка",
    }.get(status, status or "?")


async def _start_manual_payment(message: Message, user, method: str, plan_code: str) -> None:
    if user is None:
        return

    block_text = await _block_text(user.id, method)
    if block_text:
        await message.answer(block_text, reply_markup=main_menu_kb())
        return

    pending_text = await _active_pending_text(user.id)
    if pending_text:
        await message.answer(pending_text, reply_markup=main_menu_kb())
        return

    amount = await _plan_price_rub(plan_code)
    label = PLAN_LABELS.get(plan_code, plan_code)
    payment_id = f"mp{uuid.uuid4().hex}"

    await create_pending(
        payment_id=payment_id,
        user_id=user.id,
        username=user.username,
        full_name=user_full_name(user),
        plan_code=plan_code,
        payment_method=method,
        extra={"amount_rub": amount},
    )

    if method == "funpay":
        url = FUNPAY_URLS.get(plan_code, "")
        text = (
            "🛒 <b>Оплата через FunPay</b>\n\n"
            f"Тариф: <b>{label}</b>\n"
            f"Сумма в боте: <b>{amount} ₽</b>\n\n"
            "1. Перейдите по ссылке:\n"
            f"{html.escape(url)}\n"
            "2. Оплатите лот на FunPay.\n"
            "3. Вернитесь в бот и нажмите «Я оплатил».\n"
            "4. Пришлите скриншот оплаты."
        )
    else:
        text = (
            "💳 <b>Оплата по реквизитам РБ 🇧🇾 | РФ 🇷🇺</b>\n\n"
            "<b>Работает оплата из Беларуси и РФ.</b>\n\n"
            f"Тариф: <b>{label}</b>\n"
            f"Сумма: <b>{amount} ₽</b>\n"
            f"Карта: <code>{html.escape(REQUISITES_CARD)}</code>\n\n"
            "1. Переведите сумму на карту.\n"
            "2. Нажмите «Я оплатил».\n"
            "3. Укажите имя и фамилию плательщика.\n"
            "4. Пришлите скриншот перевода."
        )

    await message.answer(text, reply_markup=_manual_paid_kb(payment_id), disable_web_page_preview=True)


@router.message(F.text.startswith(BTN_PAY_FUNPAY))
async def on_funpay_selected(message: Message) -> None:
    if not message.text:
        return
    plan_code = _plan_code_from_payment_text(message.text, BTN_PAY_FUNPAY)
    if plan_code is None:
        await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return
    await _start_manual_payment(message, message.from_user, "funpay", plan_code)


@router.callback_query(F.data.startswith("pay:funpay:"))
async def on_funpay_selected_inline(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return
    plan_code = call.data.split(":", 2)[2]
    await call.answer()
    await _start_manual_payment(call.message, call.from_user, "funpay", plan_code)


@router.message(F.text.startswith(BTN_PAY_REQUISITES))
async def on_requisites_selected(message: Message) -> None:
    if not message.text:
        return
    plan_code = _plan_code_from_payment_text(message.text, BTN_PAY_REQUISITES)
    if plan_code is None:
        await message.answer("Тариф не найден. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return
    await _start_manual_payment(message, message.from_user, "requisites", plan_code)


@router.callback_query(F.data.startswith("pay:requisites:"))
async def on_requisites_selected_inline(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return
    plan_code = call.data.split(":", 2)[2]
    await call.answer()
    await _start_manual_payment(call.message, call.from_user, "requisites", plan_code)


@router.callback_query(F.data.startswith("manual:cancel:"))
async def on_manual_cancel(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None:
        return
    payment_id = call.data.split(":", 2)[2]
    pending = await get_pending(payment_id)
    if pending is None or pending.get("user_id") != call.from_user.id:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") not in {"pending", "pending_review"}:
        await call.answer("Эта заявка уже обработана", show_alert=True)
        return
    await mark_pending_status(payment_id, "canceled")
    await state.clear()
    await call.answer("Заявка отменена")
    if call.message:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer("Заявка отменена. Можно выбрать тариф заново.", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("manual:paid:"))
async def on_manual_paid(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None:
        return
    payment_id = call.data.split(":", 2)[2]
    pending = await get_pending(payment_id)
    if pending is None or pending.get("user_id") != call.from_user.id:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") != "pending":
        await call.answer("Заявка уже обработана или находится на проверке", show_alert=True)
        return

    method = pending.get("payment_method")
    if method not in {"funpay", "requisites"}:
        await call.answer("Неизвестный способ оплаты", show_alert=True)
        return
    block_text = await _block_text(call.from_user.id, method)
    if block_text:
        await call.answer("Этот способ оплаты заблокирован", show_alert=True)
        if call.message:
            await call.message.answer(block_text, reply_markup=main_menu_kb())
        return

    await state.update_data(payment_id=payment_id)
    await call.answer()
    if method == "funpay":
        await state.set_state(ManualPaymentFSM.waiting_funpay_screenshot)
        if call.message:
            await call.message.answer("Пришлите скриншот оплаты FunPay одним изображением.")
    else:
        await state.set_state(ManualPaymentFSM.waiting_requisites_payer)
        if call.message:
            await call.message.answer("Напишите имя и фамилию плательщика, с которого был перевод.")


@router.message(ManualPaymentFSM.waiting_requisites_payer, F.text)
async def on_requisites_payer(message: Message, state: FSMContext) -> None:
    payer_name = (message.text or "").strip()
    if len(payer_name) < 3:
        await message.answer("Напишите имя и фамилию плательщика текстом.")
        return
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if payment_id:
        await update_pending_fields(payment_id, {"payer_name": payer_name})
    await state.update_data(payer_name=payer_name)
    await state.set_state(ManualPaymentFSM.waiting_requisites_screenshot)
    await message.answer("Теперь пришлите скриншот перевода одним изображением.")


@router.message(ManualPaymentFSM.waiting_funpay_screenshot, F.photo)
async def on_funpay_screenshot(message: Message, state: FSMContext) -> None:
    await _submit_manual_proof(message, state, "funpay")


@router.message(ManualPaymentFSM.waiting_requisites_screenshot, F.photo)
async def on_requisites_screenshot(message: Message, state: FSMContext) -> None:
    await _submit_manual_proof(message, state, "requisites")


@router.message(ManualPaymentFSM.waiting_funpay_screenshot)
@router.message(ManualPaymentFSM.waiting_requisites_screenshot)
async def on_manual_waiting_not_photo(message: Message) -> None:
    await message.answer("Нужно прислать именно изображение со скриншотом оплаты.")


async def _submit_manual_proof(message: Message, state: FSMContext, method: str) -> None:
    data = await state.get_data()
    payment_id = data.get("payment_id")
    pending = await get_pending(payment_id) if payment_id else None
    if pending is None or pending.get("user_id") != (message.from_user.id if message.from_user else None):
        await state.clear()
        await message.answer("Заявка не найдена. Откройте витрину и выберите тариф заново.", reply_markup=main_menu_kb())
        return
    if pending.get("status") != "pending":
        await state.clear()
        await message.answer("Эта заявка уже находится на проверке или обработана.", reply_markup=main_menu_kb())
        return

    photo_id = message.photo[-1].file_id
    await update_pending_fields(payment_id, {"proof_file_id": photo_id, "status": "pending_review"})
    await state.clear()
    await message.answer("Скриншот отправлен администратору. Дождитесь проверки.", reply_markup=main_menu_kb())
    await _send_admin_review(message, pending, photo_id)


async def _send_admin_review(message: Message, pending: dict, photo_id: str) -> None:
    payment_id = pending["payment_id"]
    method = pending.get("payment_method", "?")
    plan_code = pending.get("plan_code", "?")
    payer_name = pending.get("payer_name") or ""
    user_id = int(pending.get("user_id", 0))
    user_ref = user_ref_html(user_id, pending.get("full_name"), pending.get("username"))
    caption = (
        "🧾 <b>Новая заявка на ручную оплату</b>\n\n"
        f"Способ: <b>{method_label(method)}</b>\n"
        f"Тариф: <b>{PLAN_LABELS.get(plan_code, plan_code)}</b>\n"
        f"Сумма: <b>{pending.get('amount_rub', 0)} ₽</b>\n"
        f"Пользователь: {user_ref}\n"
    )
    if payer_name:
        caption += f"Плательщик: <b>{html.escape(payer_name)}</b>\n"
    caption += f"Payment ID: <code>{html.escape(payment_id)}</code>"
    await message.bot.send_photo(ADMIN_ID, photo_id, caption=caption, reply_markup=_admin_review_kb(payment_id))


async def _edit_review_message(message: Message | None, suffix: str) -> None:
    if message is None:
        return
    base = message.html_text or message.caption or ""
    text = f"{base}\n\n{suffix}" if base else suffix
    if message.photo:
        await message.edit_caption(caption=text, reply_markup=None)
    else:
        await message.edit_text(text, reply_markup=None)


@router.callback_query(F.data.startswith("manual:ok:"))
async def on_manual_approve(call: CallbackQuery) -> None:
    if not call.from_user or call.from_user.id != ADMIN_ID:
        return
    payment_id = call.data.split(":", 2)[2]
    pending = await get_pending(payment_id)
    if pending is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") != "pending_review":
        await call.answer(f"Статус заявки: {pending.get('status')}", show_alert=True)
        return
    plan_code = pending.get("plan_code")
    await deliver_purchase(
        call.bot,
        user_id=pending["user_id"],
        username=pending.get("username"),
        plan_code=plan_code,
        plan_label=PLAN_LABELS.get(plan_code, plan_code),
        days=PLAN_DAYS.get(plan_code),
        payment_method=pending.get("payment_method", "manual"),
    )
    await mark_pending_status(payment_id, "completed")
    await call.answer("Принято")
    await _edit_review_message(call.message, "✅ <b>Заявка принята, токен выдан.</b>")


@router.callback_query(F.data.startswith("manual:no:"))
async def on_manual_reject(call: CallbackQuery) -> None:
    if not call.from_user or call.from_user.id != ADMIN_ID:
        return
    payment_id = call.data.split(":", 2)[2]
    pending = await get_pending(payment_id)
    if pending is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") not in {"pending", "pending_review"}:
        await call.answer(f"Статус заявки: {pending.get('status')}", show_alert=True)
        return
    await mark_pending_status(payment_id, "rejected")
    try:
        await call.bot.send_message(pending["user_id"], "❌ Заявка отклонена. Если это ошибка, напишите в поддержку.", reply_markup=main_menu_kb())
    except Exception:
        pass
    await call.answer("Отклонено")
    await _edit_review_message(call.message, "❌ <b>Заявка отклонена.</b>")


@router.callback_query(F.data.startswith("manual:block:"))
async def on_manual_block_start(call: CallbackQuery, state: FSMContext) -> None:
    if not call.from_user or call.from_user.id != ADMIN_ID:
        return
    payment_id = call.data.split(":", 2)[2]
    pending = await get_pending(payment_id)
    if pending is None:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    if pending.get("status") not in {"pending", "pending_review"}:
        await call.answer(f"Статус заявки: {pending.get('status')}", show_alert=True)
        return
    await state.update_data(
        payment_id=payment_id,
        review_chat_id=call.message.chat.id if call.message else None,
        review_message_id=call.message.message_id if call.message else None,
        review_text=(call.message.html_text or call.message.caption or "") if call.message else "",
    )
    await state.set_state(ManualPaymentFSM.waiting_block_duration)
    await call.answer()
    if call.message:
        await call.message.answer("Введите срок блокировки: например <code>6ч</code>, <code>12h</code>, <code>2д</code> или <code>3d</code>.")


@router.message(ManualPaymentFSM.waiting_block_duration, F.text)
async def on_manual_block_duration(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    parsed = parse_block_duration(message.text or "")
    if parsed is None:
        await message.answer("Введите срок в формате <code>6ч</code>, <code>12h</code>, <code>2д</code> или <code>3d</code>.")
        return
    delta, label = parsed
    data = await state.get_data()
    payment_id = data.get("payment_id")
    pending = await get_pending(payment_id) if payment_id else None
    if pending is None:
        await state.clear()
        await message.answer("Заявка не найдена.")
        return
    if pending.get("status") not in {"pending", "pending_review"}:
        await state.clear()
        await message.answer(f"Заявка уже обработана. Статус: <b>{pending.get('status')}</b>.")
        return

    expires_at = datetime.now(timezone.utc) + delta
    await set_payment_block(
        user_id=pending["user_id"],
        payment_method=pending.get("payment_method", "manual"),
        expires_at=expires_at,
        username=pending.get("username"),
        full_name=pending.get("full_name"),
        admin_id=message.from_user.id,
    )
    await mark_pending_status(payment_id, "rejected")
    try:
        await message.bot.send_message(
            pending["user_id"],
            f"⛔ Заявка отклонена. Способ оплаты <b>{method_label(pending.get('payment_method', '?'))}</b> заблокирован на <b>{label}</b>.",
            reply_markup=main_menu_kb(),
        )
    except Exception:
        pass

    review_chat_id = data.get("review_chat_id")
    review_message_id = data.get("review_message_id")
    review_text = data.get("review_text") or ""
    if review_chat_id and review_message_id:
        await message.bot.edit_message_caption(
            chat_id=review_chat_id,
            message_id=review_message_id,
            caption=f"{review_text}\n\n⛔ <b>Заявка отклонена, способ заблокирован на {html.escape(label)}.</b>",
            reply_markup=None,
        )
    await state.clear()
    await message.answer(f"⛔ Блокировка установлена до <b>{format_until(expires_at)}</b>.")
