from __future__ import annotations


class ApiClientError(RuntimeError):
    pass


async def close_session() -> None:
    return None


async def create_subscription_token(
    *,
    key_part2: str,
    client_id: str | None = None,
    is_public: bool = False,
    subscription_expiration: str | None = None,
    hwid: str | None = None,
) -> str:
    try:
        from ..api_server import create_subscription_token_record

        return await create_subscription_token_record(
            key_part2=key_part2,
            client_id=client_id,
            is_public=is_public,
            subscription_expiration=subscription_expiration,
            hwid=hwid,
        )
    except ValueError as exc:
        raise ApiClientError(str(exc)) from exc


async def verify_api_connection() -> bool:
    return True
