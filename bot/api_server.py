from __future__ import annotations

import asyncio
import base64
import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any

import aiohttp
from aiohttp import web
from bson import ObjectId
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from .config import API_ADMIN_TOKEN, MONGO_URI
from .database import get_collection, get_db

log = logging.getLogger(__name__)

LUA_API_CRYPTO_MODE = min(3, max(1, int(os.getenv("LUA_API_CRYPTO_MODE") or "3")))
LUA_API_KEY_ID = os.getenv("LUA_API_KEY_ID") or "kalivan-lua-v1"
LUA_API_SESSION_TTL_MS = int(os.getenv("LUA_API_SESSION_TTL_MS") or str(10 * 60 * 1000))
LUA_API_CLOCK_SKEW_MS = int(os.getenv("LUA_API_CLOCK_SKEW_MS") or str(90 * 1000))
LUA_API_PRIVATE_JWK_B64 = os.getenv("LUA_API_RSA_PRIVATE_JWK_B64") or ""
AVERAGE_PRICES_CACHE_TTL = int(os.getenv("AVERAGE_PRICES_CACHE_TTL") or "60000")

TABLE_CSV_URL = os.getenv("TABLE_CSV_URL") or "https://docs.google.com/spreadsheets/d/1uhTTihRjsZaAv60WlfTrA070ImciZQO7UBkeVtmZkkM/export?format=csv&gid=0"
ANALOGUES_CSV_URL = os.getenv("ANALOGUES_CSV_URL") or "https://docs.google.com/spreadsheets/d/1xF9b1-obvbrB0nZ9jNrjLTGMJnTPwfKxF42Uv1RgPsk/export?format=csv&gid=0"
CARS_CSV_URL = os.getenv("CARS_CSV_URL") or "https://docs.google.com/spreadsheets/d/12rV9gGz3Tmyzsg9SE1ODmDfEs6rnJgTDoBXiz_nQ9ZA/export?format=csv&gid=0"

CFG_SERVER_NAMES = [
    "Vice-City", "Phoenix", "Tucson", "Scottdale", "Chandler", "Brainburg", "Saintrose", "Mesa",
    "Red-Rock", "Yuma", "Surprise", "Prescott", "Glendale", "Kingman", "Winslow", "Payson",
    "Gilbert", "Show-Low", "Casa-Grande", "Page", "Sun-City", "Queen-Creek", "Sedona", "Holiday",
    "Wednesday", "Yava", "Faraway", "Bumble-Bee", "Christmas", "Mirage", "Love", "Drake", "Space",
]

_average_prices_cache: dict[str, Any] = {"json": None, "ts": 0.0, "lock": asyncio.Lock()}
_admin_cache: dict[str, Any] = {"token": None, "value": None, "ts": 0.0}
_token_cache: dict[str, dict[str, Any]] = {}
_lua_sessions: dict[str, dict[str, Any]] = {}
_lua_private_key: rsa.RSAPrivateKey | None = None
_http_session: aiohttp.ClientSession | None = None


def _collection(name: str) -> AsyncIOMotorCollection:
    return get_collection(name)


def _json_default(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _clean_json(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _clean_json(item) for key, item in value.items()}
    return value


def api_json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(
        _clean_json(data),
        status=status,
        dumps=lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default),
    )


async def request_json(request: web.Request) -> dict[str, Any]:
    if "json_body" in request:
        body = request["json_body"]
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
    return body if isinstance(body, dict) else {}


def send_error(status: int, message: str) -> web.Response:
    return api_json({"status": "error", "message": message}, status=status)


def send_success(data: dict[str, Any] | None = None) -> web.Response:
    return api_json({"status": "ok", **(data or {})})


async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(limit=30, ttl_dns_cache=300)
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            connector=connector,
        )
    return _http_session


async def close_api_server() -> None:
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
    _http_session = None


async def ensure_api_indexes() -> None:
    db = await get_db()
    await asyncio.gather(
        db.loader_keys.create_index("key_part2"),
        db.MarketPlace.create_index([("username", 1), ("serverId", 1)]),
        db.MarketPlace.create_index("lastUpdated"),
        db.AveragePrice.create_index("itemName"),
        db.table.create_index("itemKey", unique=True, sparse=True),
        db.CfgTokens.create_index([("updatedAtTs", -1), ("createdAtTs", -1)]),
        db.CfgTokens.create_index("tokens.token"),
    )


def format_date_ddmmyyyy(date: datetime) -> str:
    return date.strftime("%d.%m.%Y")


async def verify_admin(token: str | None) -> bool:
    if not token:
        return False
    if token == API_ADMIN_TOKEN:
        return True
    now = time.monotonic()
    if _admin_cache["token"] == token and now - float(_admin_cache["ts"]) < 30:
        return bool(_admin_cache["value"])
    admin_record = await _collection("Admin_Key").find_one()
    result = bool(admin_record and admin_record.get("Admin_Token") and token == admin_record.get("Admin_Token"))
    _admin_cache.update({"token": token, "value": result, "ts": now})
    return result


def _parse_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        day, month, year = [int(part) for part in value.split(".")]
        return datetime(year, month, day)
    except Exception:
        return None


def _delete_token_cache(token: str) -> None:
    prefix = f"{token}:"
    for key in list(_token_cache.keys()):
        if key.startswith(prefix):
            _token_cache.pop(key, None)


async def verify_token(token: str | None, hwid: str | None) -> dict[str, Any]:
    if not token:
        return {"error": "Missing token"}

    cache_key = f"{token}:{hwid or ''}"
    now = time.monotonic()
    cached = _token_cache.get(cache_key)
    if cached and now - float(cached["ts"]) < 15:
        return cached["result"]

    record = await _collection("loader_keys").find_one({"key_part2": token})
    if not record:
        result = {"error": "Invalid token"}
        _token_cache[cache_key] = {"result": result, "ts": now}
        return result

    is_public = bool(record.get("public"))
    expiration_to_use = record.get("subscription_expiration") or None
    if not expiration_to_use:
        expiration_to_use = format_date_ddmmyyyy(datetime.now() + timedelta(days=7))
        if is_public or not record.get("hwid"):
            await _collection("loader_keys").update_one(
                {"key_part2": token},
                {"$set": {"subscription_expiration": expiration_to_use}},
            )
            _delete_token_cache(token)

    expiration = _parse_expiration(expiration_to_use)
    if expiration and datetime.now() > expiration:
        result = {"error": "Subscription expired", "subscription_expiration": expiration_to_use}
        _token_cache[cache_key] = {"result": result, "ts": now}
        return result

    if is_public:
        result = {"ok": True, "subscription_expiration": expiration_to_use}
        _token_cache[cache_key] = {"result": result, "ts": now}
        return result

    if not hwid:
        return {"error": "Missing HWID"}

    if not record.get("hwid"):
        await _collection("loader_keys").update_one(
            {"key_part2": token},
            {"$set": {"hwid": hwid, "subscription_expiration": expiration_to_use}},
        )
        _delete_token_cache(token)
        return {"ok": True, "subscription_expiration": expiration_to_use}

    if record.get("hwid") != hwid:
        return {"error": "HWID mismatch"}

    result = {"ok": True, "subscription_expiration": expiration_to_use}
    _token_cache[cache_key] = {"result": result, "ts": now}
    return result


async def create_subscription_token_record(
    *,
    key_part2: str,
    client_id: str | None = None,
    is_public: bool = False,
    subscription_expiration: str | None = None,
    hwid: str | None = None,
) -> str:
    if not key_part2:
        raise ValueError("Missing key_part2")
    existing = await _collection("loader_keys").find_one({"key_part2": key_part2})
    if existing:
        raise ValueError("Token already exists")
    await _collection("loader_keys").insert_one({
        "client_id": client_id or None,
        "key_part2": key_part2,
        "public": bool(is_public),
        "hwid": hwid or None,
        "subscription_expiration": subscription_expiration or None,
        "issue_date": format_date_ddmmyyyy(datetime.now()),
    })
    return key_part2


def b64url_to_bytes(value: str | bytes | None) -> bytes:
    if isinstance(value, bytes):
        text = value.decode("ascii")
    else:
        text = str(value or "")
    text = text.replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    return base64.b64decode(text)


def bytes_to_b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _jwk_int(jwk: dict[str, str], key: str) -> int:
    return int.from_bytes(b64url_to_bytes(jwk.get(key)), "big")


def get_lua_private_key() -> rsa.RSAPrivateKey | None:
    global _lua_private_key
    if _lua_private_key is not None:
        return _lua_private_key
    if not LUA_API_PRIVATE_JWK_B64:
        return None
    jwk = json.loads(base64.b64decode(LUA_API_PRIVATE_JWK_B64).decode("utf-8"))
    public_numbers = rsa.RSAPublicNumbers(_jwk_int(jwk, "e"), _jwk_int(jwk, "n"))
    private_numbers = rsa.RSAPrivateNumbers(
        p=_jwk_int(jwk, "p"),
        q=_jwk_int(jwk, "q"),
        d=_jwk_int(jwk, "d"),
        dmp1=_jwk_int(jwk, "dp"),
        dmq1=_jwk_int(jwk, "dq"),
        iqmp=_jwk_int(jwk, "qi"),
        public_numbers=public_numbers,
    )
    _lua_private_key = private_numbers.private_key()
    return _lua_private_key


def is_encrypted_lua_body(body: Any) -> bool:
    return bool(isinstance(body, dict) and body.get("__enc") == 1 and body.get("sid") and body.get("iv") and body.get("ct") and body.get("tag"))


def is_lua_crypto_path(path: str) -> bool:
    return path in {
        "/api/checkToken",
        "/api/getTable",
        "/api/getAveragePrices",
        "/api/getAnalogues",
        "/api/getCars",
        "/api/sendTelegram",
        "/api/insertMarketplace",
        "/api/redeemCfgToken",
        "/api/marketplace",
    } or re.fullmatch(r"/api/marketplace/[^/]+", path) is not None


def cleanup_lua_sessions() -> None:
    now = int(time.time() * 1000)
    for sid, session in list(_lua_sessions.items()):
        if not session or int(session["expiresAt"]) <= now:
            _lua_sessions.pop(sid, None)


def lua_aad(prefix: str, request: web.Request, sid: str, seq: int, ts: int) -> bytes:
    return f"{prefix}\n{request.method}\n{request.path}\n{sid}\n{seq}\n{ts}".encode("utf-8")


def decrypt_lua_payload(session: dict[str, Any], aad: bytes, envelope: dict[str, Any]) -> bytes:
    aesgcm = AESGCM(session["key"])
    nonce = b64url_to_bytes(envelope.get("iv"))
    ciphertext = b64url_to_bytes(envelope.get("ct")) + b64url_to_bytes(envelope.get("tag"))
    return aesgcm.decrypt(nonce, ciphertext, aad)


def encrypt_lua_payload(session: dict[str, Any], aad: bytes, plain_text: str) -> dict[str, Any]:
    nonce = os.urandom(12)
    aesgcm = AESGCM(session["key"])
    encrypted = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), aad)
    return {
        "__enc": 1,
        "v": 1,
        "sid": session["sid"],
        "seq": session["lastSeq"],
        "ts": int(time.time() * 1000),
        "iv": bytes_to_b64url(nonce),
        "ct": bytes_to_b64url(encrypted[:-16]),
        "tag": bytes_to_b64url(encrypted[-16:]),
    }


@web.middleware
async def lua_crypto_middleware(request: web.Request, handler):
    if not is_lua_crypto_path(request.path):
        return await handler(request)

    body = await request_json(request)
    encrypted = is_encrypted_lua_body(body)
    if LUA_API_CRYPTO_MODE == 1:
        if encrypted:
            return api_json({"status": "error", "message": "lua_crypto_disabled"}, status=403)
        return await handler(request)

    if not encrypted:
        if LUA_API_CRYPTO_MODE == 2:
            return api_json({"status": "error", "message": "lua_crypto_required"}, status=403)
        return await handler(request)

    try:
        cleanup_lua_sessions()
        envelope = body
        session = _lua_sessions.get(str(envelope.get("sid")))
        if not session or int(session["expiresAt"]) <= int(time.time() * 1000):
            return api_json({"status": "error", "message": "crypto_session_expired"}, status=401)

        seq = int(envelope.get("seq") or 0)
        ts = int(envelope.get("ts") or 0)
        if seq <= 0 or seq in session["seenSeqs"]:
            return api_json({"status": "error", "message": "crypto_replay_detected"}, status=409)
        if abs(int(time.time() * 1000) - ts) > LUA_API_CLOCK_SKEW_MS:
            return api_json({"status": "error", "message": "crypto_clock_skew"}, status=400)

        plain = decrypt_lua_payload(session, lua_aad("REQ", request, session["sid"], seq, ts), envelope)
        request["json_body"] = json.loads(plain.decode("utf-8")) if plain else {}
        session["seenSeqs"].add(seq)
        session["seenSeqOrder"].append(seq)
        while len(session["seenSeqOrder"]) > 2048:
            old_seq = session["seenSeqOrder"].pop(0)
            session["seenSeqs"].discard(old_seq)
        session["lastSeq"] = max(session["lastSeq"], seq)
        session["expiresAt"] = int(time.time() * 1000) + LUA_API_SESSION_TTL_MS
        request["lua_crypto"] = {"session": session, "seq": seq}

        response = await handler(request)
        body_bytes = getattr(response, "body", b"") or b""
        plain_text = body_bytes.decode("utf-8") if isinstance(body_bytes, bytes) else str(body_bytes)
        response_ts = int(time.time() * 1000)
        aad = f"RESP\n{request.method}\n{request.path}\n{session['sid']}\n{seq}\n{response_ts}".encode("utf-8")
        envelope_out = encrypt_lua_payload(session, aad, plain_text)
        envelope_out["seq"] = seq
        envelope_out["ts"] = response_ts
        return api_json(envelope_out, status=response.status)
    except Exception:
        log.exception("Lua crypto request error")
        return api_json({"status": "error", "message": "invalid_crypto_payload"}, status=400)


async def lua_crypto_handshake(request: web.Request) -> web.Response:
    try:
        if LUA_API_CRYPTO_MODE == 1:
            return api_json({"status": "error", "message": "lua_crypto_disabled"}, status=403)
        key = get_lua_private_key()
        if not key:
            return api_json({"status": "error", "message": "lua_crypto_key_missing"}, status=503)
        body = await request_json(request)
        if body.get("kid") != LUA_API_KEY_ID or not body.get("k"):
            return api_json({"status": "error", "message": "invalid_crypto_handshake"}, status=400)

        decrypted = key.decrypt(
            b64url_to_bytes(body.get("k")),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        payload = json.loads(decrypted.decode("utf-8"))
        now = int(time.time() * 1000)
        ts = int(payload.get("ts") or 0)
        if abs(now - ts) > LUA_API_CLOCK_SKEW_MS:
            return api_json({"status": "error", "message": "crypto_clock_skew"}, status=400)

        aes_key = b64url_to_bytes(payload.get("aesKey"))
        if len(aes_key) != 32:
            return api_json({"status": "error", "message": "invalid_crypto_key"}, status=400)

        result = await verify_token(payload.get("token"), payload.get("hwid"))
        if result.get("error"):
            return api_json(
                {"status": "error", "message": result["error"], "subscription_expiration": result.get("subscription_expiration")},
                status=401,
            )

        cleanup_lua_sessions()
        sid = bytes_to_b64url(os.urandom(24))
        expires_at = now + LUA_API_SESSION_TTL_MS
        _lua_sessions[sid] = {
            "sid": sid,
            "key": aes_key,
            "token": payload.get("token"),
            "hwid": payload.get("hwid"),
            "lastSeq": 0,
            "seenSeqs": set(),
            "seenSeqOrder": [],
            "expiresAt": expires_at,
        }
        return api_json({"status": "ok", "sid": sid, "expiresAt": expires_at, "serverTime": now, "mode": LUA_API_CRYPTO_MODE})
    except Exception:
        log.exception("Lua crypto handshake error")
        return api_json({"status": "error", "message": "invalid_crypto_handshake"}, status=400)


def parse_csv_rows(csv_content: str) -> list[list[str]]:
    return list(csv.reader(StringIO(csv_content)))


def parse_analogues_csv(csv_content: str) -> list[dict[str, Any]]:
    rows = parse_csv_rows(csv_content)
    if len(rows) <= 1:
        return []
    out = []
    for row in rows[1:]:
        item_raw = (row[0] if len(row) > 0 else "").strip()
        analogues_raw = (row[1] if len(row) > 1 else "").strip()
        if not item_raw:
            continue
        item_raw = re.sub(r"\(\s*(\d+)\s*слот\s*\)", r"(\1 слот)", item_raw, flags=re.IGNORECASE)
        analogues = [
            item.strip()
            for item in analogues_raw.strip("[]").replace('"', "").split(",")
            if item.strip()
        ]
        out.append({"item": item_raw, "analogues": analogues})
    return out


def parse_cars_csv(csv_content: str) -> list[dict[str, Any]]:
    rows = parse_csv_rows(csv_content)
    if len(rows) <= 1:
        return []
    out = []
    for row in rows[1:]:
        name = (row[0] if len(row) > 0 else "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "liquid": (row[1] if len(row) > 1 else "").strip(),
            "price": (row[2] if len(row) > 2 else "").strip(),
            "date": (row[3] if len(row) > 3 else "").strip(),
        })
    return out


def to_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value if value is not None else default).replace(" ", ""))
    except Exception:
        return default


def normalize_marketplace_side(items_raw: Any, counts_raw: Any, prices_raw: Any) -> dict[str, list[Any]]:
    items = to_array(items_raw)
    counts = to_array(counts_raw)
    prices = to_array(prices_raw)
    out = {"items": [], "counts": [], "prices": []}
    for index, raw_item in enumerate(items):
        item = str(raw_item or "").strip()
        count = parse_int(counts[index] if index < len(counts) else 1, 1)
        price = parse_int(prices[index] if index < len(prices) else 0, 0)
        if not item or count <= 0 or price <= 0:
            continue
        out["items"].append(item)
        out["counts"].append(count)
        out["prices"].append(price)
    return out


def normalize_marketplace_payload(body: Any) -> dict[str, Any] | None:
    data = body[0] if isinstance(body, list) and body else body
    if not isinstance(data, dict):
        return None
    username = str(data.get("username") or "").strip()
    server_id = parse_int(data.get("serverId"), -1)
    if not username or server_id < 0:
        return None
    sell = normalize_marketplace_side(data.get("items_sell"), data.get("count_sell"), data.get("price_sell"))
    buy = normalize_marketplace_side(data.get("items_buy"), data.get("count_buy"), data.get("price_buy"))
    return {
        "username": username,
        "serverId": server_id,
        "enabled": data.get("enabled") is not False,
        "LavkaUid": parse_int(data.get("LavkaUid"), 0),
        "items_sell": sell["items"],
        "count_sell": sell["counts"],
        "price_sell": sell["prices"],
        "items_buy": buy["items"],
        "count_buy": buy["counts"],
        "price_buy": buy["prices"],
    }


def normalize_cfg_token(token: Any) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("cfgtoken:") else f"cfgtoken:{raw}"


def normalize_cfg_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        count = parse_int(item.get("count", item.get("continue", 1)), 1)
        price = parse_int(item.get("price", item.get("price_vc", 10)), 10)
        price_vc = parse_int(item.get("price_vc", item.get("price", 10)), 10)
        if not name or count <= 0:
            continue
        out.append({
            "name": name,
            "enabled": item.get("enabled") is not False,
            "count": count,
            "continue": parse_int(item.get("continue", count), count) or count,
            "price": price if price > 0 else 10,
            "price_vc": price_vc if price_vc > 0 else (price if price > 0 else 10),
            "maximum": False,
            "count_maximum": 0,
        })
    return out


def cfg_doc_to_client(doc: dict[str, Any], include_tokens: bool = True) -> dict[str, Any]:
    tokens = doc.get("tokens") if isinstance(doc.get("tokens"), list) else []
    unused_tokens = [token for token in tokens if not token.get("used")]
    server_id = doc.get("serverId") if isinstance(doc.get("serverId"), int) else 0
    out = {
        "id": str(doc.get("_id")),
        "name": doc.get("name") or "",
        "budget": int(doc.get("budget") or 0),
        "serverId": server_id,
        "serverName": doc.get("serverName") or CFG_SERVER_NAMES[server_id] or "Vice-City",
        "items": doc.get("items") if isinstance(doc.get("items"), list) else [],
        "createdAt": doc.get("createdAt") or "",
        "updatedAt": doc.get("updatedAt") or doc.get("createdAt") or "",
        "unusedTokensCount": len(unused_tokens),
    }
    if include_tokens:
        out["tokens"] = [{"token": token.get("token"), "createdAt": token.get("createdAt") or "", "used": bool(token.get("used"))} for token in tokens]
    return out


def get_cfg_object_id(id_value: Any) -> ObjectId | None:
    text = str(id_value or "")
    return ObjectId(text) if ObjectId.is_valid(text) else None


def parse_marketplace_server_param(value: str | None) -> int | None | bool:
    if value in {None, "", "-1"}:
        return None
    server_id = parse_int(value, -1)
    if server_id < 0 or server_id > 32:
        return False
    return server_id


async def send_marketplace(request: web.Request) -> web.Response:
    try:
        server_param = request.match_info.get("serverId")
        server_id = parse_marketplace_server_param(server_param)
        if server_id is False:
            return send_error(400, "Invalid serverId")
        filter_doc = {} if server_id is None else {"serverId": server_id}
        players = await _collection("MarketPlace").find(filter_doc, {"_id": 0, "lastUpdated": 0}).to_list(length=None)
        return api_json(players)
    except Exception as exc:
        return send_error(500, str(exc))


async def add_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        key_part2 = body.get("key_part2")
        old_key_part2 = body.get("old_key_part2")
        if not key_part2 and not old_key_part2:
            return send_error(400, "Missing key_part2")
        target_key = old_key_part2 or key_part2
        existing = await _collection("loader_keys").find_one({"key_part2": target_key})
        if not existing:
            await _collection("loader_keys").insert_one({
                "client_id": body.get("client_id") or None,
                "key_part2": key_part2,
                "public": body.get("public") if isinstance(body.get("public"), bool) else False,
                "hwid": None,
                "subscription_expiration": body.get("subscription_expiration") or None,
                "issue_date": body.get("issue_date") or format_date_ddmmyyyy(datetime.now()),
            })
            return send_success({"message": "Token created"})
        update: dict[str, Any] = {}
        if key_part2:
            update["key_part2"] = key_part2
        if body.get("client_id") not in {None, ""}:
            update["client_id"] = body.get("client_id")
        if isinstance(body.get("public"), bool):
            update["public"] = body.get("public")
        if body.get("subscription_expiration") not in {None, ""}:
            update["subscription_expiration"] = body.get("subscription_expiration")
        if body.get("issue_date") not in {None, ""}:
            update["issue_date"] = body.get("issue_date")
        elif not existing.get("issue_date"):
            update["issue_date"] = format_date_ddmmyyyy(datetime.now())
        if update:
            await _collection("loader_keys").update_one({"_id": existing["_id"]}, {"$set": update})
        _delete_token_cache(str(target_key))
        return send_success({"message": "Token updated"})
    except Exception as exc:
        return send_error(500, str(exc))


async def delete_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        key_part2 = str(body.get("key_part2") or "")
        await _collection("loader_keys").delete_one({"key_part2": key_part2})
        _delete_token_cache(key_part2)
        return send_success({"message": "Token deleted"})
    except Exception as exc:
        return send_error(500, str(exc))


async def get_token_table(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        tokens = await _collection("loader_keys").find({}, {"hwid": 0}).to_list(length=None)
        return send_success({"table": tokens})
    except Exception as exc:
        return send_error(500, str(exc))


async def get_cfg_configs(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        docs = await _collection("CfgTokens").find({}).sort([("updatedAtTs", -1), ("createdAtTs", -1)]).to_list(length=None)
        configs = [cfg_doc_to_client(doc, True) for doc in docs]
        active_count = len([cfg for cfg in configs if cfg.get("unusedTokensCount", 0) > 0])
        return send_success({"configs": configs, "activeCount": active_count})
    except Exception as exc:
        return send_error(500, str(exc))


async def save_cfg_config(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        clean_name = str(body.get("name") or "").strip()
        if not clean_name:
            return send_error(400, "Missing config name")
        sid = parse_int(body.get("serverId"), 0)
        normalized_server_id = sid if 0 <= sid <= 32 else 0
        budget = parse_int(body.get("budget"), 0)
        now = datetime.now()
        payload = {
            "name": clean_name,
            "serverId": normalized_server_id,
            "serverName": str(body.get("serverName") or CFG_SERVER_NAMES[normalized_server_id] or "Vice-City"),
            "budget": budget if budget > 0 else 2_000_000_000,
            "items": normalize_cfg_items(body.get("items")),
            "updatedAt": format_date_ddmmyyyy(now),
            "updatedAtTs": now,
        }
        object_id = get_cfg_object_id(body.get("id"))
        if object_id:
            await _collection("CfgTokens").update_one(
                {"_id": object_id},
                {"$set": payload, "$setOnInsert": {"createdAt": format_date_ddmmyyyy(now), "createdAtTs": now, "tokens": []}},
                upsert=True,
            )
            doc = await _collection("CfgTokens").find_one({"_id": object_id})
            return send_success({"config": cfg_doc_to_client(doc or {}, True)})
        doc = {**payload, "createdAt": format_date_ddmmyyyy(now), "createdAtTs": now, "tokens": []}
        result = await _collection("CfgTokens").insert_one(doc)
        saved = await _collection("CfgTokens").find_one({"_id": result.inserted_id})
        return send_success({"config": cfg_doc_to_client(saved or {}, True)})
    except Exception as exc:
        return send_error(500, str(exc))


async def delete_cfg_config(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        object_id = get_cfg_object_id(body.get("id"))
        if not object_id:
            return send_error(400, "Invalid config id")
        await _collection("CfgTokens").delete_one({"_id": object_id})
        return send_success({"message": "Config deleted"})
    except Exception as exc:
        return send_error(500, str(exc))


async def create_cfg_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        object_id = get_cfg_object_id(body.get("id"))
        if not object_id:
            return send_error(400, "Invalid config id")
        cfg_token = normalize_cfg_token(body.get("token"))
        if not cfg_token or cfg_token == "cfgtoken:":
            return send_error(400, "Missing cfg token")
        duplicate = await _collection("CfgTokens").find_one({"tokens.token": cfg_token})
        if duplicate:
            return api_json({"status": "error", "message": "Cfg token already exists"})
        now = datetime.now()
        await _collection("CfgTokens").update_one(
            {"_id": object_id},
            {
                "$push": {"tokens": {"token": cfg_token, "createdAt": format_date_ddmmyyyy(now), "createdAtTs": now, "used": False}},
                "$set": {"updatedAt": format_date_ddmmyyyy(now), "updatedAtTs": now},
            },
        )
        doc = await _collection("CfgTokens").find_one({"_id": object_id})
        return send_success({"config": cfg_doc_to_client(doc or {}, True)})
    except Exception as exc:
        return send_error(500, str(exc))


async def delete_cfg_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        object_id = get_cfg_object_id(body.get("id"))
        if not object_id:
            return send_error(400, "Invalid config id")
        cfg_token = normalize_cfg_token(body.get("token"))
        now = datetime.now()
        await _collection("CfgTokens").update_one(
            {"_id": object_id},
            {"$pull": {"tokens": {"token": cfg_token}}, "$set": {"updatedAt": format_date_ddmmyyyy(now), "updatedAtTs": now}},
        )
        doc = await _collection("CfgTokens").find_one({"_id": object_id})
        return send_success({"config": cfg_doc_to_client(doc or {}, True)})
    except Exception as exc:
        return send_error(500, str(exc))


async def redeem_cfg_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        cfg_token = normalize_cfg_token(body.get("cfg_token"))
        if not cfg_token or cfg_token == "cfgtoken:":
            return api_json({"status": "error", "message": "Missing cfg token"})
        now = datetime.now()
        doc = await _collection("CfgTokens").find_one_and_update(
            {"tokens": {"$elemMatch": {"token": cfg_token, "used": {"$ne": True}}}},
            {"$pull": {"tokens": {"token": cfg_token}}, "$set": {"updatedAt": format_date_ddmmyyyy(now), "updatedAtTs": now}},
            return_document=ReturnDocument.BEFORE,
        )
        if not doc:
            return api_json({"status": "error", "message": "Cfg token not found or already used"})
        return api_json({"status": "ok", "config": cfg_doc_to_client(doc, False)})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


async def admin_get_table(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        table = await _collection("table").find({}).sort("position", 1).to_list(length=None)
        return send_success({"table": table})
    except Exception as exc:
        return send_error(500, str(exc))


async def admin_get_average_prices(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        average_prices = await _collection("AveragePrice").find({}).to_list(length=None)
        return send_success({"averagePrices": average_prices})
    except Exception as exc:
        return send_error(500, str(exc))


async def check_token(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"], "subscription_expiration": result.get("subscription_expiration")})
        return api_json({"status": "ok", "message": "Token verified", "subscription_expiration": result.get("subscription_expiration")})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


async def send_telegram(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        bot_token = body.get("botToken")
        chat_id = body.get("chatId")
        text = body.get("text")
        if not bot_token or not chat_id or not text:
            return api_json({"status": "error", "message": "Incomplete data"})
        session = await get_http_session()
        async with session.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": text}) as response:
            if response.status >= 400:
                return api_json({"status": "error", "message": await response.text()})
        return api_json({"status": "ok", "message": "Notification sent"})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


async def get_table(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        table_data = await _collection("table").find({}).to_list(length=None)
        return api_json({"status": "ok", "table": table_data})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


async def get_free_table(request: web.Request) -> web.Response:
    try:
        data = await _collection("table_free").find({}).to_list(length=None)
        return api_json({"status": "ok", "table": data})
    except Exception as exc:
        return send_error(500, str(exc))


async def get_analogues(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        data = await _collection("AnaloguesAks").find({}).to_list(length=None)
        return api_json({"status": "ok", "analogues": data})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


async def get_cars(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        data = await _collection("Cars").find({}).to_list(length=None)
        return api_json({"status": "ok", "cars": data})
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


def parse_any_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except Exception:
            continue
    return None


async def save_average_prices(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        data = body.get("data")
        if not isinstance(data, dict):
            return send_error(400, "Invalid data format")
        cutoff_date = datetime.now() - timedelta(days=60)
        item_names = list(data.keys())
        existing_items = await _collection("AveragePrice").find({"itemName": {"$in": item_names}}).to_list(length=None) if item_names else []
        existing_map = {item.get("itemName"): item.get("history") or [] for item in existing_items}
        operations = []
        for item_name in item_names:
            history_map: dict[str, Any] = {}
            for entry in existing_map.get(item_name, []):
                entry_date = parse_any_date(entry.get("date") if isinstance(entry, dict) else None)
                if entry_date and entry_date >= cutoff_date:
                    history_map[str(entry.get("date"))] = entry
            for entry in data.get(item_name) or []:
                if not isinstance(entry, dict):
                    continue
                entry_date = parse_any_date(entry.get("date"))
                if entry_date and entry_date >= cutoff_date:
                    history_map[str(entry.get("date"))] = entry
            merged = sorted(history_map.values(), key=lambda item: parse_any_date(item.get("date")) or datetime.min, reverse=True)
            operations.append({"update_one": {"filter": {"itemName": item_name}, "update": {"$set": {"history": merged}}, "upsert": True}})
        if operations:
            await _collection("AveragePrice").bulk_write([_bulk_op(op) for op in operations])
        invalidate_average_prices_cache()
        return api_json({"status": "ok", "message": "Average prices updated"})
    except Exception as exc:
        log.exception("saveAveragePrices error")
        return send_error(500, str(exc))


def _bulk_op(operation: dict[str, Any]) -> Any:
    from pymongo import UpdateOne
    update_one = operation["update_one"]
    return UpdateOne(update_one["filter"], update_one["update"], upsert=update_one.get("upsert", False))


def invalidate_average_prices_cache() -> None:
    _average_prices_cache["json"] = None
    _average_prices_cache["ts"] = 0.0


async def get_average_prices_json() -> str:
    now = time.monotonic() * 1000
    cached = _average_prices_cache.get("json")
    if cached and now - float(_average_prices_cache["ts"]) < AVERAGE_PRICES_CACHE_TTL:
        return str(cached)
    async with _average_prices_cache["lock"]:
        cached = _average_prices_cache.get("json")
        now = time.monotonic() * 1000
        if cached and now - float(_average_prices_cache["ts"]) < AVERAGE_PRICES_CACHE_TTL:
            return str(cached)
        average_prices = await _collection("AveragePrice").find({}).to_list(length=None)
        payload = json.dumps({"status": "ok", "averagePrices": _clean_json(average_prices)}, ensure_ascii=False, separators=(",", ":"))
        _average_prices_cache["json"] = payload
        _average_prices_cache["ts"] = now
        return payload


async def get_average_prices(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        result = await verify_token(body.get("token"), body.get("hwid"))
        if result.get("error"):
            return api_json({"status": "error", "message": result["error"]})
        return web.Response(text=await get_average_prices_json(), content_type="application/json", charset="utf-8")
    except Exception as exc:
        return api_json({"status": "error", "message": str(exc)})


def normalize_table_key_part(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def build_table_item_key(item: dict[str, Any]) -> str:
    return "|".join([
        normalize_table_key_part(item.get("item")),
        normalize_table_key_part(item.get("upgrade")),
        normalize_table_key_part(item.get("transfer_1")),
        normalize_table_key_part(item.get("transfer_2")),
        normalize_table_key_part(item.get("patch")),
    ])


def normalize_price_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if match:
        year, month, day = map(int, match.groups())
    else:
        match = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$", raw)
        if not match:
            return ""
        day, month, year = map(int, match.groups())
    try:
        date = datetime(year, month, day)
    except ValueError:
        return ""
    return date.strftime("%Y-%m-%d")


def merge_table_price_history(existing_history: Any, item: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    history_map: dict[str, dict[str, Any]] = {}
    for entry in existing_history if isinstance(existing_history, list) else []:
        if not isinstance(entry, dict):
            continue
        date = normalize_price_date(entry.get("date"))
        if not date or datetime.fromisoformat(f"{date}T00:00:00+00:00") < cutoff:
            continue
        history_map[date] = {
            "date": date,
            "price_buy": entry.get("price_buy") if isinstance(entry.get("price_buy"), (int, float)) else "",
            "price_sell": entry.get("price_sell") if isinstance(entry.get("price_sell"), (int, float)) else "",
            "price_sell_out_three": entry.get("price_sell_out_three") if isinstance(entry.get("price_sell_out_three"), (int, float)) else "",
        }
    current_date = normalize_price_date(item.get("updateDate"))
    if current_date and datetime.fromisoformat(f"{current_date}T00:00:00+00:00") >= cutoff:
        history_map[current_date] = {
            "date": current_date,
            "price_buy": item.get("price_buy"),
            "price_sell": item.get("price_sell"),
            "price_sell_out_three": item.get("price_sell_out_three"),
        }
    return sorted(history_map.values(), key=lambda entry: entry["date"], reverse=True)


def parse_table_number(value: Any) -> int | str:
    parsed = parse_int(value, 0)
    return parsed if parsed else ""


def parse_table_row(row: list[str], index: int) -> dict[str, Any]:
    values = [*row, "", "", "", "", "", "", ""]
    full_name, transfer, patch, liquid, buy, sell, sell_out_three, date = values[:8]
    item_name = full_name.strip()
    upgrade = ""
    video_match = re.match(r"^(Видеокарта)\s*\((\d+)\s*LVL\)", item_name, flags=re.IGNORECASE)
    if video_match:
        item_name = "Видеокарта"
        upgrade = f"(Уровень: {video_match.group(2)})"
    else:
        lvl_match = re.search(r"\((\d+)\s*LVL\)", item_name, flags=re.IGNORECASE)
        if lvl_match:
            item_name = re.sub(r"\(\d+\s*LVL\)", f"(Уровень: {lvl_match.group(1)})", item_name, flags=re.IGNORECASE)
        upgrade_match = re.search(r"\+\d+(?:[-/]\d+)?", item_name)
        if upgrade_match:
            upgrade = upgrade_match.group(0)
            item_name = item_name.replace(upgrade, "").strip()
    transfer_1 = ""
    transfer_2 = ""
    if transfer:
        parts = transfer.split("+")
        transfer_1 = parts[0].strip() if len(parts) > 0 else ""
        transfer_2 = parts[1].strip() if len(parts) > 1 else ""
    item = {
        "item": item_name,
        "upgrade": upgrade,
        "transfer_1": transfer_1,
        "transfer_2": transfer_2,
        "patch": patch.strip(),
        "liquid": liquid.strip(),
        "price_buy": parse_table_number(buy),
        "price_sell": parse_table_number(sell),
        "price_sell_out_three": parse_table_number(sell_out_three),
        "updateDate": date.strip(),
        "position": index + 1,
    }
    item["itemKey"] = build_table_item_key(item)
    return item


async def fetch_text(url: str) -> str:
    session = await get_http_session()
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def sort_table(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        rows = parse_csv_rows(await fetch_text(TABLE_CSV_URL))
        if len(rows) <= 1:
            return api_json({"status": "error", "message": "CSV is empty"})
        items = [parse_table_row(row, index) for index, row in enumerate(rows[1:]) if row and row[0].strip()]
        item_keys = [item["itemKey"] for item in items if item.get("itemKey")]
        existing_items = await _collection("table").find({"itemKey": {"$in": item_keys}}).to_list(length=None) if item_keys else []
        existing_map = {item.get("itemKey"): item for item in existing_items}
        from pymongo import UpdateOne
        operations = []
        for item in items:
            existing = existing_map.get(item["itemKey"])
            operations.append(UpdateOne(
                {"itemKey": item["itemKey"]},
                {"$set": {**item, "priceHistory": merge_table_price_history(existing.get("priceHistory") if existing else None, item)}},
                upsert=True,
            ))
        if operations:
            await _collection("table").bulk_write(operations, ordered=False)
        await _collection("table").delete_many({"itemKey": {"$nin": item_keys}})

        try:
            analogues_items = parse_analogues_csv(await fetch_text(ANALOGUES_CSV_URL))
            await _collection("AnaloguesAks").delete_many({})
            if analogues_items:
                await _collection("AnaloguesAks").insert_many(analogues_items)
        except Exception:
            log.exception("Failed to update analogues")

        try:
            cars_items = parse_cars_csv(await fetch_text(CARS_CSV_URL))
            await _collection("Cars").delete_many({})
            if cars_items:
                await _collection("Cars").insert_many(cars_items)
        except Exception:
            log.exception("Failed to update cars")

        return api_json({"status": "ok", "message": "Tables updated", "itemsCount": len(items)})
    except Exception as exc:
        log.exception("sortTable error")
        return send_error(500, str(exc))


async def move_table_to_free(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        data = await _collection("table").find({}).to_list(length=None)
        await _collection("table_free").delete_many({})
        if data:
            cleaned = [{key: value for key, value in item.items() if key != "_id"} for item in data]
            await _collection("table_free").insert_many(cleaned)
        return api_json({"status": "ok", "message": "Table moved to table_free", "count": len(data)})
    except Exception as exc:
        return send_error(500, str(exc))


async def insert_marketplace(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        data = normalize_marketplace_payload(body)
        if not data:
            return send_error(400, "Invalid marketplace data")
        is_empty = len(data["items_sell"]) == 0 and len(data["items_buy"]) == 0
        if data["enabled"] is False or is_empty:
            await _collection("MarketPlace").delete_one({"username": data["username"], "serverId": data["serverId"]})
            return api_json({"status": "ok", "message": "User removed from marketplace"})
        await _collection("MarketPlace").update_one(
            {"username": data["username"], "serverId": data["serverId"]},
            {"$set": {**data, "enabled": True, "lastUpdated": datetime.now()}},
            upsert=True,
        )
        return api_json({"status": "ok"})
    except Exception as exc:
        log.exception("insertMarketplace error")
        return send_error(500, str(exc))


async def create_subscription_token_endpoint(request: web.Request) -> web.Response:
    try:
        body = await request_json(request)
        if not await verify_admin(body.get("admin_token")):
            return send_error(403, "Invalid admin token")
        key_part2 = str(body.get("key_part2") or "")
        if not key_part2:
            return send_error(400, "Missing key_part2")
        try:
            await create_subscription_token_record(
                key_part2=key_part2,
                client_id=body.get("client_id"),
                is_public=body.get("public") if isinstance(body.get("public"), bool) else False,
                subscription_expiration=body.get("subscription_expiration"),
                hwid=body.get("hwid"),
            )
        except ValueError as exc:
            return api_json({"status": "error", "message": str(exc)})
        return api_json({"status": "ok", "message": "Token created", "token": key_part2})
    except Exception as exc:
        return send_error(500, str(exc))


async def options_handler(request: web.Request) -> web.Response:
    return web.Response(status=204)


async def cleanup_marketplace_loop(app: web.Application) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            cutoff = datetime.now() - timedelta(minutes=10)
            await _collection("MarketPlace").delete_many({"lastUpdated": {"$lt": cutoff}})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Marketplace cleanup failed")


async def on_api_startup(app: web.Application) -> None:
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is required")
    await ensure_api_indexes()
    app["api_cleanup_task"] = asyncio.create_task(cleanup_marketplace_loop(app))


async def on_api_cleanup(app: web.Application) -> None:
    task = app.get("api_cleanup_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_api_server()


def setup_api_routes(app: web.Application) -> None:
    app.middlewares.append(lua_crypto_middleware)
    app.on_startup.append(on_api_startup)
    app.on_cleanup.append(on_api_cleanup)

    app.router.add_route("OPTIONS", "/api/{tail:.*}", options_handler)
    app.router.add_post("/api/luaCryptoHandshake", lua_crypto_handshake)
    app.router.add_post("/api/AddToken", add_token)
    app.router.add_post("/api/DeleteToken", delete_token)
    app.router.add_post("/api/GetTokenTable", get_token_table)
    app.router.add_post("/api/GetCfgConfigs", get_cfg_configs)
    app.router.add_post("/api/SaveCfgConfig", save_cfg_config)
    app.router.add_post("/api/DeleteCfgConfig", delete_cfg_config)
    app.router.add_post("/api/CreateCfgToken", create_cfg_token)
    app.router.add_post("/api/DeleteCfgToken", delete_cfg_token)
    app.router.add_post("/api/redeemCfgToken", redeem_cfg_token)
    app.router.add_post("/api/AdminGetTable", admin_get_table)
    app.router.add_post("/api/AdminGetAveragePrices", admin_get_average_prices)
    app.router.add_post("/api/checkToken", check_token)
    app.router.add_post("/api/sendTelegram", send_telegram)
    app.router.add_post("/api/getTable", get_table)
    app.router.add_get("/api/getFreeTable", get_free_table)
    app.router.add_post("/api/getAnalogues", get_analogues)
    app.router.add_post("/api/getCars", get_cars)
    app.router.add_post("/api/saveAveragePrices", save_average_prices)
    app.router.add_post("/api/getAveragePrices", get_average_prices)
    app.router.add_post("/api/sortTable", sort_table)
    app.router.add_post("/api/moveTableToFree", move_table_to_free)
    app.router.add_post("/api/insertMarketplace", insert_marketplace)
    app.router.add_get("/api/marketplace", send_marketplace)
    app.router.add_get("/api/marketplace/{serverId}", send_marketplace)
    app.router.add_post("/api/marketplace", send_marketplace)
    app.router.add_post("/api/marketplace/{serverId}", send_marketplace)
    app.router.add_get("/api/testMarketplace", send_marketplace)
    app.router.add_get("/api/testMarketplace/{serverId}", send_marketplace)
    app.router.add_post("/api/CreateSubscriptionToken", create_subscription_token_endpoint)
