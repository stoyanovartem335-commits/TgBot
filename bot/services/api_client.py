"""HTTP client for the API server."""
from __future__ import annotations

import logging

import aiohttp

from ..config import API_ADMIN_TOKEN, API_SERVER_URL

log = logging.getLogger(__name__)


class ApiClientError(RuntimeError):
    pass


_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session


async def create_subscription_token(
    *,
    key_part2: str,
    client_id: str | None = None,
    is_public: bool = False,
    subscription_expiration: str | None = None,
    hwid: str | None = None,
) -> str:
    """Create a token on the API server."""
    payload = {
        "admin_token": API_ADMIN_TOKEN,
        "key_part2": key_part2,
        "client_id": client_id,
        "public": is_public,
        "subscription_expiration": subscription_expiration,
        "hwid": hwid,
    }
    session = await get_session()
    async with session.post(
        f"{API_SERVER_URL}/api/CreateSubscriptionToken",
        json=payload,
    ) as resp:
        text = await resp.text()
        if resp.status >= 400:
            log.error("API server error: %s %s", resp.status, text)
            raise ApiClientError(f"API server returned {resp.status}: {text[:200]}")
        try:
            data = await resp.json(content_type=None)
        except Exception as exc:
            raise ApiClientError(f"Invalid API response: {exc}") from exc
        if data.get("status") != "ok":
            raise ApiClientError(f"API error: {data.get('message', 'unknown')}")
        return key_part2


async def verify_api_connection() -> bool:
    """Check if API server is reachable."""
    try:
        session = await get_session()
        async with session.get(f"{API_SERVER_URL}/api/health") as resp:
            return resp.status == 200
    except Exception:
        return False
