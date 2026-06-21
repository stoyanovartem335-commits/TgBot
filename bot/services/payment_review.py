from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

MANUAL_PAYMENT_METHODS = ("funpay", "requisites")
METHOD_LABELS = {
    "funpay": "Fun Pay",
    "requisites": "Реквизиты РБ 🇧🇾 | РФ 🇷🇺",
    "stars": "Telegram Stars",
    "triboote": "Tribute",
}


def user_full_name(user) -> str:
    parts = [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""]
    return " ".join(part for part in parts if part).strip() or getattr(user, "full_name", "") or ""


def user_ref_html(user_id: int, full_name: str | None, username: str | None) -> str:
    name = html.escape((full_name or "").strip() or "Без имени")
    uname = html.escape("@" + username.lstrip("@")) if username else "без username"
    return f"<b>{name}</b> ({uname})\nID: <code>{int(user_id)}</code>"


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method)


def parse_block_duration(text: str) -> tuple[timedelta, str] | None:
    match = re.search(r"^\s*(\d{1,4})\s*([a-zA-Zа-яА-Я]*)", text or "")
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2).casefold()
    if unit.startswith(("h", "ч", "hour")):
        return timedelta(hours=amount), f"{amount} ч."
    if unit.startswith(("d", "д", "day")) or not unit:
        return timedelta(days=amount), f"{amount} дн."
    return None


def format_until(value: str | datetime | None) -> str:
    if value is None:
        return "неизвестно"
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
