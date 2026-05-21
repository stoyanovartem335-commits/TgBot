from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from ..config import TRIBOOTE_API_KEY, TRIBOOTE_API_URL, WEBAPP_URL

log = logging.getLogger(__name__)


@dataclass
class TribootePayment:
    payment_id: str
    pay_url: str


class TribooteError(RuntimeError):
    pass


_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def create_payment(
    *,
    amount_rub: int,
    payment_id: str,
    description: str,
) -> TribootePayment:
    if not TRIBOOTE_API_URL or not TRIBOOTE_API_KEY:
        raise TribooteError(
            "Triboote API \u043d\u0435 \u0441\u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d (TRIBOOTE_API_URL / TRIBOOTE_API_KEY)"
        )

    payload = {
        "amount": amount_rub,
        "currency": "RUB",
        "external_id": payment_id,
        "description": description,
        "webhook_url": f"{WEBAPP_URL}/triboote/webhook",
        "success_url": f"{WEBAPP_URL}/triboote/success",
    }
    headers = {
        "Authorization": f"Bearer {TRIBOOTE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    session = await get_session()
    async with session.post(
        f"{TRIBOOTE_API_URL}/payments",
        json=payload,
        headers=headers,
    ) as resp:
        text = await resp.text()
        if resp.status >= 400:
            log.error("Triboote error: %s %s", resp.status, text)
            raise TribooteError(f"Triboote \u0432\u0435\u0440\u043d\u0443\u043b {resp.status}: {text[:200]}")
        try:
            data = await resp.json(content_type=None)
        except Exception as exc:
            raise TribooteError(f"\u041d\u0435\u0432\u0430\u043b\u0438\u0434\u043d\u044b\u0439 \u043e\u0442\u0432\u0435\u0442 Triboote: {exc}") from exc

    pay_url = data.get("pay_url") or data.get("payment_url") or data.get("url")
    ext_id = data.get("id") or data.get("payment_id") or payment_id
    if not pay_url:
        raise TribooteError("Triboote \u043d\u0435 \u0432\u0435\u0440\u043d\u0443\u043b \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0430 \u043e\u043f\u043b\u0430\u0442\u0443")
    return TribootePayment(payment_id=str(ext_id), pay_url=str(pay_url))
