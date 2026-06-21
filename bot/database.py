from __future__ import annotations

from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import MONGO_URI

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_settings_cache: dict | None = None
_settings_cache_until: datetime | None = None
_settings_cache_ttl = timedelta(seconds=30)


async def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        raise RuntimeError("MongoDB not initialized")
    return _db


def get_collection(name: str):
    if _db is None:
        raise RuntimeError("MongoDB not initialized")
    return _db.get_collection(name)


async def init_db() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(
        MONGO_URI,
        maxPoolSize=20,
        minPoolSize=0,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=15000,
        retryWrites=True,
    )
    _db = _client.get_database()
    await _db.bot_purchases.create_index("user_id")
    await _db.bot_purchases.create_index("token", unique=True)
    await _db.bot_pending_payments.create_index("payment_id", unique=True)
    await _db.bot_pending_payments.create_index("user_id")
    await _db.bot_pending_payments.create_index("external_ref")
    await _db.bot_pending_payments.create_index([("user_id", 1), ("payment_method", 1), ("status", 1)])
    await _db.bot_gsheets_requests.create_index("user_id")
    existing = await _db.bot_settings.find_one({"_id": "global"})
    if not existing:
        await _db.bot_settings.insert_one({
            "_id": "global",
            "prices_rub": {"1m": 299, "2m": 549, "3m": 799, "6m": 1499, "forever": 4999},
            "prices_stars": {"1m": 150, "2m": 280, "3m": 400, "6m": 750, "forever": 2500},
            "highlighted_tariff": "3m",
            "tariff_descriptions": {
                "1m": "Базовый доступ на 30 дней",
                "2m": "Доступ на 60 дней",
                "3m": "Самый популярный выбор",
                "6m": "Доступ на 180 дней",
                "forever": "Бессрочный доступ"
            },
            "discounts": {"enabled": False, "percentage": 10, "duration_days": 30},
            "promotion": {"enabled": False, "text": "Купи 1 токен → получи 1 токен для друга"},
            "banner_text": "",
            "marketing_text": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })


def compute_expiry(plan_code: str, days: int | None, paid_at: datetime) -> datetime | None:
    if days is None:
        return None
    return paid_at + timedelta(days=days)


async def insert_purchase(
    *,
    user_id: int,
    username: str | None,
    plan_code: str,
    token: str,
    friend_token: str | None,
    payment_method: str,
    expires_at: datetime | None,
) -> tuple[datetime, datetime | None]:
    paid_at = datetime.now(timezone.utc)
    db = await get_db()
    doc = {
        "user_id": user_id,
        "username": username,
        "plan_code": plan_code,
        "token": token,
        "friend_token": friend_token,
        "payment_method": payment_method,
        "paid_at": paid_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    await db.bot_purchases.insert_one(doc)
    return paid_at, expires_at


async def create_pending(
    *,
    payment_id: str,
    user_id: int,
    username: str | None,
    plan_code: str,
    payment_method: str,
    external_ref: str | None = None,
) -> None:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.bot_pending_payments.update_one(
        {"payment_id": payment_id},
        {
            "$setOnInsert": {
                "payment_id": payment_id,
                "status": "pending",
                "created_at": now,
            },
            "$set": {
                "user_id": user_id,
                "username": username,
                "plan_code": plan_code,
                "payment_method": payment_method,
                "external_ref": external_ref,
                "updated_at": now,
            },
        },
        upsert=True,
    )


async def get_pending(payment_id: str) -> dict | None:
    db = await get_db()
    return await db.bot_pending_payments.find_one({"payment_id": payment_id})


async def get_pending_by_external_ref(external_ref: str) -> dict | None:
    db = await get_db()
    return await db.bot_pending_payments.find_one({"external_ref": external_ref})


async def get_latest_pending_for_user(
    *,
    user_id: int,
    payment_method: str,
) -> dict | None:
    db = await get_db()
    return await db.bot_pending_payments.find_one(
        {"user_id": user_id, "payment_method": payment_method, "status": {"$in": ["pending", "processing", "failed"]}},
        sort=[("_id", -1)],
    )


async def mark_pending_processing(payment_id: str) -> bool:
    db = await get_db()
    result = await db.bot_pending_payments.update_one(
        {"payment_id": payment_id, "status": {"$in": ["pending", "failed"]}},
        {"$set": {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return result.modified_count == 1


async def mark_pending_status(payment_id: str, status: str) -> None:
    db = await get_db()
    await db.bot_pending_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )


async def latest_token_for_user(user_id: int) -> str | None:
    db = await get_db()
    doc = await db.bot_purchases.find_one(
        {"user_id": user_id},
        sort=[("_id", -1)],
        projection={"token": 1},
    )
    return doc["token"] if doc else None


async def get_latest_purchase_for_user(
    user_id: int,
    payment_method: str | None = None,
) -> dict | None:
    db = await get_db()
    query = {"user_id": user_id}
    if payment_method:
        query["payment_method"] = payment_method
    return await db.bot_purchases.find_one(query, sort=[("_id", -1)])


async def update_purchase_expiration(
    purchase_id,
    *,
    plan_code: str,
    expires_at: datetime | None,
) -> None:
    db = await get_db()
    await db.bot_purchases.update_one(
        {"_id": purchase_id},
        {
            "$set": {
                "plan_code": plan_code,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "renewed_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


async def update_api_token_expiration(token: str, expiration_str: str | None) -> None:
    db = await get_db()
    await db.loader_keys.update_one(
        {"key_part2": token},
        {"$set": {"subscription_expiration": expiration_str}},
    )


async def insert_gsheets_request(
    *,
    user_id: int,
    username: str | None,
    email: str,
    token: str | None,
) -> int:
    db = await get_db()
    doc = {
        "user_id": user_id,
        "username": username,
        "email": email,
        "token": token,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    result = await db.bot_gsheets_requests.insert_one(doc)
    return result.inserted_id


async def get_settings() -> dict:
    global _settings_cache, _settings_cache_until
    now = datetime.now(timezone.utc)
    if _settings_cache is not None and _settings_cache_until is not None and now < _settings_cache_until:
        return _settings_cache

    db = await get_db()
    settings = await db.bot_settings.find_one({"_id": "global"})
    if not settings:
        await init_db()
        settings = await db.bot_settings.find_one({"_id": "global"})
    settings = settings or {}
    _settings_cache = settings
    _settings_cache_until = now + _settings_cache_ttl
    return settings


async def update_settings(updates: dict) -> dict:
    global _settings_cache, _settings_cache_until
    db = await get_db()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.bot_settings.update_one(
        {"_id": "global"},
        {"$set": updates},
        upsert=True,
    )
    settings = await db.bot_settings.find_one({"_id": "global"}) or {}
    _settings_cache = settings
    _settings_cache_until = datetime.now(timezone.utc) + _settings_cache_ttl
    return settings


async def close_db() -> None:
    global _client, _db, _settings_cache, _settings_cache_until
    if _client is not None:
        _client.close()
    _client = None
    _db = None
    _settings_cache = None
    _settings_cache_until = None


async def count_users() -> int:
    db = await get_db()
    return await db.bot_purchases.count_documents({})


get_total_purchases = count_users


async def get_recent_purchases(limit: int = 10) -> list:
    db = await get_db()
    cursor = db.bot_purchases.find({}, sort=[("paid_at", -1)], limit=limit)
    return await cursor.to_list(length=limit)
