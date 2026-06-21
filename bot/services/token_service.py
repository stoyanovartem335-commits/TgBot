from __future__ import annotations

import logging
import secrets

from .api_client import ApiClientError, create_subscription_token

log = logging.getLogger(__name__)


class TokenGenerationError(RuntimeError):
    pass


def generate_token() -> str:
    return secrets.token_hex(24)


def compute_expiration_str(plan_code: str, days: int | None) -> str | None:
    from datetime import datetime, timedelta
    if days is None:
        return None
    expires = datetime.now() + timedelta(days=days)
    return expires.strftime("%d.%m.%Y")


async def issue_tokens(
    plan_code: str,
    days: int | None,
    count: int = 2,
    expires_at=None,
) -> list[str]:
    tokens = []
    expiration_str = expires_at.strftime("%d.%m.%Y") if expires_at else compute_expiration_str(plan_code, days)

    for i in range(count):
        token = generate_token()
        try:
            await create_subscription_token(
                key_part2=token,
                is_public=True,
                subscription_expiration=expiration_str,
            )
            tokens.append(token)
        except ApiClientError as exc:
            log.error("Failed to create token %d/%d: %s", i + 1, count, exc)
            if tokens:
                log.warning("Partial token generation: %d/%d succeeded", len(tokens), count)
            raise TokenGenerationError(f"Failed to generate token {i+1}/{count}: {exc}")

    if len(tokens) < count:
        raise TokenGenerationError(f"Expected {count} tokens, got {len(tokens)}")

    return tokens
