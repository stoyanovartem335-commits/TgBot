from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

from .config import MONGO_URI
from .services.plans import (
    DEFAULT_PRICES_RUB,
    DEFAULT_PRICES_STARS,
    DEFAULT_TARIFF_DESCRIPTIONS,
    PLAN_CODES,
    normalize_plan_map,
)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_settings_cache: dict | None = None
_settings_cache_until: datetime | None = None
_settings_cache_ttl = timedelta(seconds=30)
_manual_cleanup_cache_until: datetime | None = None


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
    await _db.bot_purchases.create_index([("user_id", 1), ("delivery_status", 1)])
    await _db.bot_purchases.create_index("paid_at")
    await _db.bot_purchases.create_index([("payment_method", 1), ("paid_at", -1)])
    await _db.bot_pending_payments.create_index("payment_id", unique=True)
    await _db.bot_pending_payments.create_index("user_id")
    await _db.bot_pending_payments.create_index("external_ref")
    await _db.bot_pending_payments.create_index([("user_id", 1), ("payment_method", 1), ("status", 1)])
    await _db.bot_pending_payments.create_index([("user_id", 1), ("payment_method", 1), ("user_hidden", 1), ("_id", -1)])
    await _db.bot_pending_payments.create_index([("payment_method", 1), ("_id", -1)])
    await _db.bot_pending_payments.create_index([("payment_method", 1), ("created_at", 1)])
    await _db.bot_pending_payments.create_index([("payment_method", 1), ("status", 1), ("_id", -1)])
    await _db.bot_pending_payments.create_index([("user_id", 1), ("payment_method", 1), ("status", 1), ("user_hidden", 1), ("_id", -1)])
    await _db.bot_payment_blocks.create_index([("user_id", 1), ("payment_method", 1)], unique=True)
    await _db.bot_payment_blocks.create_index("expires_at")
    await _db.bot_gsheets_requests.create_index("user_id")
    await _db.bot_gsheets_requests.create_index([("status", 1), ("requested_at", -1)])
    await _db.bot_gsheets_requests.create_index([("user_id", 1), ("status", 1), ("requested_at", -1)])
    existing = await _db.bot_settings.find_one({"_id": "global"})
    if not existing:
        await _db.bot_settings.insert_one({
            "_id": "global",
            "prices_rub": DEFAULT_PRICES_RUB,
            "prices_stars": DEFAULT_PRICES_STARS,
            "highlighted_tariff": "3m",
            "tariff_descriptions": DEFAULT_TARIFF_DESCRIPTIONS,
            "discounts": {
                "enabled": False,
                "percentage": 10,
                "duration_days": 30,
                "plans": {
                    code: {"enabled": False, "percentage": 0}
                    for code in PLAN_CODES
                },
            },
            "promotion": {"enabled": False, "text": "Купи 1 токен → получи 1 токен для друга"},
            "banner_text": "",
            "marketing_text": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        updates = {
            "prices_rub": normalize_plan_map(existing.get("prices_rub", {}), DEFAULT_PRICES_RUB),
            "prices_stars": normalize_plan_map(existing.get("prices_stars", {}), DEFAULT_PRICES_STARS),
            "tariff_descriptions": normalize_plan_map(existing.get("tariff_descriptions", {}), DEFAULT_TARIFF_DESCRIPTIONS),
        }
        if existing.get("highlighted_tariff") not in PLAN_CODES:
            updates["highlighted_tariff"] = "3m"
        if any(existing.get(key) != value for key, value in updates.items()):
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            await _db.bot_settings.update_one({"_id": "global"}, {"$set": updates})


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
    amount_rub: int | None = None,
    amount_stars: int | None = None,
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
        "amount_rub": int(amount_rub) if amount_rub is not None else None,
        "amount_stars": int(amount_stars) if amount_stars is not None else None,
        "paid_at": paid_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "delivery_status": "pending",
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
    full_name: str | None = None,
    initial_status: str = "pending",
    extra: dict | None = None,
) -> None:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    updates = {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "plan_code": plan_code,
        "payment_method": payment_method,
        "external_ref": external_ref,
        "updated_at": now,
    }
    if extra:
        updates.update(extra)
    await db.bot_pending_payments.update_one(
        {"payment_id": payment_id},
        {
            "$setOnInsert": {
                "payment_id": payment_id,
                "status": initial_status,
                "created_at": now,
            },
            "$set": updates,
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


async def update_pending_fields(payment_id: str, updates: dict) -> None:
    db = await get_db()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.bot_pending_payments.update_one({"payment_id": payment_id}, {"$set": updates})


async def get_active_manual_pending(user_id: int) -> dict | None:
    await cleanup_old_manual_requests()
    db = await get_db()
    return await db.bot_pending_payments.find_one(
        {
            "user_id": user_id,
            "payment_method": {"$in": ["funpay", "requisites"]},
            "$or": [
                {"status": "pending_review"},
                {"status": "pending", "proof_file_id": {"$exists": True}},
            ],
            "user_hidden": {"$ne": True},
        },
        sort=[("_id", -1)],
    )


MANUAL_PAYMENT_METHODS = ["funpay", "requisites"]
MANUAL_ACTIVE_STATUSES = ["pending", "pending_review"]
MANUAL_REQUEST_RETENTION_DAYS = 3
MANUAL_RECENT_CLOSED_LIMIT = 20


def _manual_user_filter(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "payment_method": {"$in": MANUAL_PAYMENT_METHODS},
        "user_hidden": {"$ne": True},
    }


def _manual_admin_filter() -> dict:
    return {"payment_method": {"$in": MANUAL_PAYMENT_METHODS}}


def _manual_visible_active_filter() -> dict:
    return {
        "$or": [
            {"status": "pending_review"},
            {"status": "pending", "proof_file_id": {"$exists": True}},
        ],
    }


async def cleanup_old_manual_requests(*, force: bool = False) -> int:
    global _manual_cleanup_cache_until
    now_dt = datetime.now(timezone.utc)
    if not force and _manual_cleanup_cache_until and _manual_cleanup_cache_until > now_dt:
        return 0
    _manual_cleanup_cache_until = now_dt + timedelta(minutes=30)
    cutoff = (now_dt - timedelta(days=MANUAL_REQUEST_RETENTION_DAYS)).isoformat()
    db = await get_db()
    result = await db.bot_pending_payments.delete_many({
        "payment_method": {"$in": MANUAL_PAYMENT_METHODS},
        "created_at": {"$lt": cutoff},
        "$or": [
            {"status": {"$nin": MANUAL_ACTIVE_STATUSES}},
            {"status": "pending", "proof_file_id": {"$exists": False}},
        ],
    })
    return result.deleted_count


async def hide_saved_manual_requests_for_user(user_id: int) -> int:
    db = await get_db()
    result = await db.bot_pending_payments.update_many(
        {
            "user_id": user_id,
            "payment_method": {"$in": MANUAL_PAYMENT_METHODS},
            "status": {"$nin": MANUAL_ACTIVE_STATUSES},
            "user_hidden": {"$ne": True},
        },
        {"$set": {"user_hidden": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return result.modified_count


async def count_manual_requests_for_user(user_id: int) -> int:
    await cleanup_old_manual_requests()
    db = await get_db()
    base_filter = _manual_user_filter(user_id)
    active_count = await db.bot_pending_payments.count_documents({**base_filter, **_manual_visible_active_filter()})
    closed_count = await db.bot_pending_payments.count_documents({**base_filter, "status": {"$nin": MANUAL_ACTIVE_STATUSES}})
    return active_count + min(closed_count, MANUAL_RECENT_CLOSED_LIMIT)


async def list_manual_requests_for_user(user_id: int, *, page: int = 0, limit: int = 10) -> list[dict]:
    await cleanup_old_manual_requests()
    db = await get_db()
    page = max(0, page)
    limit = max(1, min(limit, 50))
    base_filter = _manual_user_filter(user_id)
    offset = page * limit
    active_filter = {**base_filter, **_manual_visible_active_filter()}
    closed_filter = {**base_filter, "status": {"$nin": MANUAL_ACTIVE_STATUSES}}
    active_count = await db.bot_pending_payments.count_documents(active_filter)
    items: list[dict] = []
    if offset < active_count:
        active_cursor = db.bot_pending_payments.find(active_filter, sort=[("_id", -1)]).skip(offset).limit(limit)
        items = await active_cursor.to_list(length=limit)
    closed_offset = max(0, offset - active_count)
    remaining = limit - len(items)
    if remaining > 0 and closed_offset < MANUAL_RECENT_CLOSED_LIMIT:
        closed_limit = min(remaining, MANUAL_RECENT_CLOSED_LIMIT - closed_offset)
        closed_cursor = db.bot_pending_payments.find(closed_filter, sort=[("updated_at", -1), ("_id", -1)]).skip(closed_offset).limit(closed_limit)
        items.extend(await closed_cursor.to_list(length=closed_limit))
    return items


async def count_manual_payment_requests() -> int:
    await cleanup_old_manual_requests()
    db = await get_db()
    base_filter = _manual_admin_filter()
    active_count = await db.bot_pending_payments.count_documents({**base_filter, **_manual_visible_active_filter()})
    closed_count = await db.bot_pending_payments.count_documents({**base_filter, "status": {"$nin": MANUAL_ACTIVE_STATUSES}})
    return active_count + min(closed_count, MANUAL_RECENT_CLOSED_LIMIT)


async def list_manual_payment_requests(*, page: int = 0, limit: int = 10) -> list[dict]:
    await cleanup_old_manual_requests()
    db = await get_db()
    page = max(0, page)
    limit = max(1, min(limit, 50))
    base_filter = _manual_admin_filter()
    offset = page * limit
    active_filter = {**base_filter, **_manual_visible_active_filter()}
    closed_filter = {**base_filter, "status": {"$nin": MANUAL_ACTIVE_STATUSES}}
    active_count = await db.bot_pending_payments.count_documents(active_filter)
    items: list[dict] = []
    if offset < active_count:
        active_cursor = db.bot_pending_payments.find(active_filter, sort=[("_id", -1)]).skip(offset).limit(limit)
        items = await active_cursor.to_list(length=limit)
    closed_offset = max(0, offset - active_count)
    remaining = limit - len(items)
    if remaining > 0 and closed_offset < MANUAL_RECENT_CLOSED_LIMIT:
        closed_limit = min(remaining, MANUAL_RECENT_CLOSED_LIMIT - closed_offset)
        closed_cursor = db.bot_pending_payments.find(closed_filter, sort=[("updated_at", -1), ("_id", -1)]).skip(closed_offset).limit(closed_limit)
        items.extend(await closed_cursor.to_list(length=closed_limit))
    return items


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def get_active_payment_block(user_id: int, payment_method: str) -> dict | None:
    db = await get_db()
    doc = await db.bot_payment_blocks.find_one({"user_id": user_id, "payment_method": payment_method})
    if not doc:
        return None
    expires_at = _parse_iso_dt(doc.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        await db.bot_payment_blocks.delete_one({"_id": doc["_id"]})
        return None
    return doc


async def set_payment_block(
    *,
    user_id: int,
    payment_method: str,
    expires_at: datetime,
    username: str | None,
    full_name: str | None,
    admin_id: int,
) -> None:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.bot_payment_blocks.update_one(
        {"user_id": user_id, "payment_method": payment_method},
        {
            "$set": {
                "user_id": user_id,
                "payment_method": payment_method,
                "username": username,
                "full_name": full_name,
                "admin_id": admin_id,
                "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def delete_payment_block(user_id: int, payment_method: str) -> None:
    db = await get_db()
    await db.bot_payment_blocks.delete_one({"user_id": user_id, "payment_method": payment_method})


async def list_active_payment_blocks(limit: int = 30) -> list[dict]:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    cursor = db.bot_payment_blocks.find({"expires_at": {"$gt": now}}, sort=[("expires_at", 1)], limit=limit)
    return await cursor.to_list(length=limit)


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


async def list_pending_purchase_deliveries_for_user(user_id: int, limit: int = 5) -> list[dict]:
    db = await get_db()
    cursor = db.bot_purchases.find(
        {"user_id": user_id, "delivery_status": {"$in": ["pending", "failed"]}},
        sort=[("_id", 1)],
        limit=limit,
    )
    return await cursor.to_list(length=limit)


async def mark_purchase_delivery_status(purchase_id, status: str) -> None:
    db = await get_db()
    await db.bot_purchases.update_one(
        {"_id": purchase_id},
        {"$set": {"delivery_status": status, "delivery_updated_at": datetime.now(timezone.utc).isoformat()}},
    )


async def mark_purchase_delivery_status_by_token(token: str, status: str) -> None:
    db = await get_db()
    await db.bot_purchases.update_one(
        {"token": token},
        {"$set": {"delivery_status": status, "delivery_updated_at": datetime.now(timezone.utc).isoformat()}},
    )


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
    full_name: str | None = None,
    email: str,
    token: str | None,
) -> str:
    db = await get_db()
    doc = {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "email": email,
        "token": token,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    result = await db.bot_gsheets_requests.insert_one(doc)
    return str(result.inserted_id)


async def get_latest_gsheets_request_for_user(user_id: int) -> dict | None:
    db = await get_db()
    return await db.bot_gsheets_requests.find_one({"user_id": user_id}, sort=[("_id", -1)])


async def count_gsheets_requests() -> int:
    db = await get_db()
    return await db.bot_gsheets_requests.count_documents({})


async def list_gsheets_requests(*, page: int = 0, limit: int = 10) -> list[dict]:
    db = await get_db()
    page = max(0, page)
    limit = max(1, min(limit, 50))
    cursor = db.bot_gsheets_requests.find({}, sort=[("_id", -1)]).skip(page * limit).limit(limit)
    return await cursor.to_list(length=limit)


def _object_id(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_gsheets_request(request_id: str) -> dict | None:
    object_id = _object_id(request_id)
    if object_id is None:
        return None
    db = await get_db()
    return await db.bot_gsheets_requests.find_one({"_id": object_id})


async def update_gsheets_request_status(request_id: str, status: str, admin_id: int) -> dict | None:
    object_id = _object_id(request_id)
    if object_id is None:
        return None
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = await db.bot_gsheets_requests.find_one_and_update(
        {"_id": object_id},
        {"$set": {"status": status, "admin_id": admin_id, "reviewed_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return result


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


async def list_purchases_for_stats(since: datetime | None = None) -> list[dict]:
    db = await get_db()
    query = {}
    if since is not None:
        query["paid_at"] = {"$gte": since.astimezone(timezone.utc).isoformat()}
    cursor = db.bot_purchases.find(
        query,
        {
            "plan_code": 1,
            "payment_method": 1,
            "paid_at": 1,
            "token": 1,
            "friend_token": 1,
            "amount_rub": 1,
            "amount_stars": 1,
        },
        sort=[("paid_at", -1)],
    )
    items = []
    async for row in cursor:
        items.append(row)
    return items


def _parse_loader_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M"):
        try:
            parsed = datetime.strptime(str(value).strip(), fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def get_loader_token_counts() -> tuple[int, int]:
    db = await get_db()
    total = await db.loader_keys.count_documents({})
    now = datetime.now(timezone.utc)
    active = 0
    cursor = db.loader_keys.find({}, {"subscription_expiration": 1})
    async for row in cursor:
        expires_at = _parse_loader_expiration(row.get("subscription_expiration"))
        if expires_at is None or expires_at >= now:
            active += 1
    return total, active
