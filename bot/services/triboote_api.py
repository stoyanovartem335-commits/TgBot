from __future__ import annotations

import logging
from dataclasses import dataclass
from json import JSONDecodeError
from urllib.parse import urljoin

import aiohttp

from ..config import (
    TRIBUTE_API_KEY,
    TRIBUTE_API_URL,
    TRIBUTE_CURRENCY,
    TRIBUTE_PRODUCT_URLS,
    WEBAPP_URL,
)

log = logging.getLogger(__name__)


@dataclass
class TribootePayment:
    payment_id: str
    pay_url: str
    webapp_pay_url: str | None = None


class TribooteError(RuntimeError):
    pass


class TributeShopNotFoundError(TribooteError):
    pass


_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=30, ttl_dns_cache=300)
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            connector=connector,
        )
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
    user_id: int | None = None,
    plan_code: str | None = None,
    title: str | None = None,
) -> TribootePayment:
    if not TRIBUTE_API_URL or not TRIBUTE_API_KEY:
        raise TribooteError(
            "Tribute Shop API не сконфигурирован (TRIBUTE_API_URL / TRIBUTE_API_KEY)"
        )

    endpoint = urljoin(f"{TRIBUTE_API_URL.rstrip('/')}/", "shop/orders")
    payload = {
        "amount": amount_rub * 100,
        "currency": TRIBUTE_CURRENCY,
        "title": title or description[:100],
        "description": description,
        "successUrl": f"{WEBAPP_URL}/triboote/success",
        "failUrl": f"{WEBAPP_URL}/triboote/fail",
        "customerId": str(user_id or ""),
        "comment": f"payment_id={payment_id};plan={plan_code or ''}",
        "period": "onetime",
    }
    headers = {
        "Api-Key": TRIBUTE_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    session = await get_session()
    async with session.post(
        endpoint,
        json=payload,
        headers=headers,
    ) as resp:
        text = await resp.text()
        if resp.status >= 400:
            log.error("Tribute error: %s %s", resp.status, text)
            try:
                error_data = await resp.json(content_type=None)
            except (JSONDecodeError, ValueError, TypeError):
                error_data = {}
            code = str(error_data.get("code") or "")
            message = str(error_data.get("message") or text[:200])
            request_id = str(error_data.get("requestId") or "")
            if resp.status == 404 and code == "error_not_found" and "shop not found" in message.lower():
                raise TributeShopNotFoundError(
                    "Shop API недоступен: Tribute не нашёл активный магазин для этого API-ключа "
                    "(shop not found). Нужно активировать магазин в разделе «Товары»/Shop API "
                    "или использовать ссылки инфопродуктов. "
                    f"requestId={request_id or 'unknown'}"
                )
            raise TribooteError(f"Tribute вернул {resp.status}: {message[:200]}")
        try:
            data = await resp.json(content_type=None)
        except Exception as exc:
            raise TribooteError(f"Невалидный ответ Triboote: {exc}") from exc

    pay_url = data.get("webappPaymentUrl") or data.get("paymentUrl")
    webapp_pay_url = data.get("webappPaymentUrl")
    ext_id = data.get("uuid") or data.get("id") or data.get("payment_id") or payment_id
    if not pay_url:
        raise TribooteError("Triboote не вернул ссылку на оплату")
    return TribootePayment(payment_id=str(ext_id), pay_url=str(pay_url), webapp_pay_url=webapp_pay_url)


def get_product_payment_url(plan_code: str) -> str | None:
    return TRIBUTE_PRODUCT_URLS.get(plan_code)


def get_product_ref(plan_code: str) -> str | None:
    return TRIBUTE_PRODUCT_URLS.get(plan_code)
