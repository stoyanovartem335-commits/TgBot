from __future__ import annotations

import hmac
import html
import json
import logging
import os
import base64
import time
from hashlib import sha256

_START_TIME = time.monotonic()

from aiogram import Bot
from aiohttp import web

from .config import (
    ADMIN_ID,
    ADMIN_WEB_SECRET_PATH,
    TRIBUTE_API_KEY,
    TRIBUTE_DEBUG_WEBHOOKS,
    WEB_HOST,
    WEB_PORT,
    WEBAPP_DIR,
)
from .api_server import setup_api_routes
from .database import get_settings
from .handlers.triboote import complete_from_tribute_event
from .services.payment_flow import selected_plan_text
from .services.settings_service import get_plans_from_settings

log = logging.getLogger(__name__)


async def index_handler(request: web.Request) -> web.StreamResponse:
    index = WEBAPP_DIR / "index.html"
    if not index.exists():
        return web.Response(status=500, text="webapp/index.html missing")
    resp = web.FileResponse(index)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def health_handler(request: web.Request) -> web.Response:
    uptime = int(time.monotonic() - _START_TIME)
    log.info("Health check from %s", request.remote)
    return web.json_response({"status": "ok", "uptime": uptime, "service": "telegram-bot"})


async def nosleep_handler(request: web.Request) -> web.Response:
    log.info("Ping from %s", request.remote)
    return web.Response(text="OK")


async def plans_json_handler(request: web.Request) -> web.Response:
    plans = await get_plans_from_settings()
    settings = await get_settings()
    from .services.settings_service import normalize_discounts
    discounts = normalize_discounts(settings.get("discounts", {}))
    return web.json_response({
        "plans": plans,
        "discount": {
            "enabled": discounts.get("enabled", False),
            "percentage": discounts.get("percentage", 0),
            "plans": discounts.get("plans", {}),
        }
    })


async def site_json_handler(request: web.Request) -> web.Response:
    from .config import site_config_for_webapp, BOT_USERNAME
    data = site_config_for_webapp()
    data["bot_username"] = BOT_USERNAME
    data["bot_url"] = f"https://t.me/{BOT_USERNAME}"
    settings = await get_settings()
    promo = settings.get("promotion", {})
    enabled = promo.get("enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes", "on", "вкл")
    data["promo_enabled"] = bool(enabled)
    data["promo_text"] = promo.get("text", "")
    return web.json_response(data)


async def images_json_handler(request: web.Request) -> web.Response:
    images_dir = WEBAPP_DIR / "images"
    if not images_dir.exists():
        return web.json_response({"images": []})
    valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    images = sorted([
        f"/static/images/{f.name}"
        for f in images_dir.iterdir()
        if f.is_file() and f.suffix.lower() in valid_extensions
    ])
    return web.json_response({"images": images})


def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    from urllib.parse import parse_qsl
    try:
        parsed = dict(parse_qsl(init_data))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        
        import hashlib
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        
        if hmac.compare_digest(received_hash, expected_hash):
            user_data = parsed.get("user")
            if user_data:
                return json.loads(user_data)
        return None
    except Exception as exc:
        log.warning("verify_telegram_init_data error: %s", exc)
        return None


async def select_plan_api_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    init_data = data.get("initData")
    plan_code = data.get("plan")

    if not init_data or not plan_code:
        return web.json_response({"ok": False, "error": "missing initData or plan"}, status=400)

    from .config import BOT_TOKEN
    user_data = verify_telegram_init_data(init_data, BOT_TOKEN)
    if not user_data:
        return web.json_response({"ok": False, "error": "invalid initData"}, status=403)

    user_id = user_data.get("id")
    if not user_id:
        return web.json_response({"ok": False, "error": "missing user id"}, status=400)

    from .services.settings_service import get_plans_from_settings
    plans = await get_plans_from_settings()
    plan = next((p for p in plans if p["code"] == plan_code), None)
    if not plan:
        return web.json_response({"ok": False, "error": "invalid plan code"}, status=400)

    from .keyboards import payment_methods_kb
    text = selected_plan_text(plan["label"], plan["discounted_price_rub"], plan["discounted_price_stars"])

    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"ok": False, "error": "bot instance not found"}, status=500)

    try:
        await bot.send_message(user_id, text, reply_markup=payment_methods_kb(plan_code))
        from .config import BOT_USERNAME
        return web.json_response({"ok": True, "bot_url": f"https://t.me/{BOT_USERNAME}"})
    except Exception as exc:
        log.error("Failed to send plan selection to user %s: %s", user_id, exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def triboote_success_handler(request: web.Request) -> web.Response:
    return web.Response(
        content_type="text/html",
        charset="utf-8",
        text=(
            "<!doctype html><meta charset=\'utf-8\'>"
            "<title>Оплата завершена</title>"
            "<body style=\'font-family:system-ui;text-align:center;padding:40px\'>"
            "<h2>✅ Платёж получен</h2>"
            "<p>Возвращайтесь в Telegram — бот пришлёт токен и инструкцию.</p>"
            "</body>"
        ),
    )


async def triboote_fail_handler(request: web.Request) -> web.Response:
    return web.Response(
        content_type="text/html",
        charset="utf-8",
        text=(
            "<!doctype html><meta charset='utf-8'>"
            "<title>Оплата не завершена</title>"
            "<body style='font-family:system-ui;text-align:center;padding:40px'>"
            "<h2>Оплата не завершена</h2>"
            "<p>Вернитесь в Telegram и попробуйте оплатить ещё раз или выберите другой способ оплаты.</p>"
            "</body>"
        ),
    )


def _verify_triboote_signature(body: bytes, header_sig: str | None) -> bool:
    if not TRIBUTE_API_KEY:
        log.error("TRIBUTE_API_KEY is not configured")
        return False
    if not header_sig:
        return False
    digest = hmac.new(TRIBUTE_API_KEY.encode("utf-8"), body, sha256).digest()
    expected_hex = digest.hex()
    expected_b64 = base64.b64encode(digest).decode("ascii")
    candidate = header_sig.split("=", 1)[1] if "=" in header_sig else header_sig
    candidate = candidate.strip()
    return (
        hmac.compare_digest(expected_hex, candidate.lower())
        or hmac.compare_digest(expected_b64, candidate)
    )


def _is_tribute_test_event(data: dict) -> bool:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    name = str(data.get("name") or data.get("event") or "").lower()
    if name in {"test", "ping", "webhook_test", "test_webhook"}:
        return True
    if data.get("test_event") == "test_event" or payload.get("test_event") == "test_event":
        return True
    if data.get("test") is True or payload.get("test") is True:
        return True
    sample_markers = (
        str(payload.get("telegram_user_id") or "") == "12321321",
        str(payload.get("trb_user_id") or "") == "T-31326",
        str(payload.get("product_id") or "") == "456",
        str(payload.get("purchase_id") or "") == "78901",
        str(payload.get("transaction_id") or "") == "234567",
    )
    return sum(1 for marker in sample_markers if marker) >= 2


async def _send_admin_webhook_dump(bot: Bot, data: dict, reason: str) -> None:
    try:
        dump = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        prefix = f"<b>Tribute webhook</b>\n{html.escape(reason)}\n\n"
        max_chunk = 3200
        chunks = [dump[i:i + max_chunk] for i in range(0, len(dump), max_chunk)] or ["{}"]
        for index, chunk in enumerate(chunks, start=1):
            title = prefix if index == 1 else f"<b>Tribute webhook</b> chunk {index}/{len(chunks)}\n\n"
            await bot.send_message(ADMIN_ID, f"{title}<pre>{html.escape(chunk)}</pre>")
    except Exception:
        log.exception("Failed to send Tribute webhook dump to admin")


def _debug_body_for_rejected_webhook(body: bytes, sig: str | None) -> dict:
    try:
        parsed = json.loads(body.decode("utf-8") or "{}")
        payload = parsed if isinstance(parsed, dict) else {"_payload": parsed}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {
            "_invalid_json": True,
            "_body_preview": body[:2000].decode("utf-8", errors="replace"),
        }
    payload["_debug"] = {
        "signature_header_present": bool(sig),
        "body_size": len(body),
    }
    return payload


def make_triboote_webhook_handler(bot: Bot):
    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        sig = (
            request.headers.get("trbt-signature")
            or request.headers.get("X-Tribute-Signature")
            or request.headers.get("X-Triboote-Signature")
            or request.headers.get("X-Signature")
        )
        if not _verify_triboote_signature(body, sig):
            log.warning("Tribute webhook bad signature")
            if TRIBUTE_DEBUG_WEBHOOKS:
                await _send_admin_webhook_dump(
                    bot,
                    _debug_body_for_rejected_webhook(body, sig),
                    "REJECTED: bad signature. Check TRIBUTE_API_KEY in Render and Tribute.",
                )
            return web.Response(status=401, text="bad signature")

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return web.Response(status=400, text="invalid json")

        test_event = _is_tribute_test_event(data)
        if TRIBUTE_DEBUG_WEBHOOKS or test_event:
            reason = (
                "TEST webhook only: endpoint/signature OK, no payment data."
                if test_event
                else "VALID signed Tribute webhook payload."
            )
            await _send_admin_webhook_dump(bot, data, reason)
        if test_event:
            return web.json_response({"status": "ok", "mode": "test"})

        try:
            ok = await complete_from_tribute_event(bot, data)
        except Exception:
            log.exception("Tribute webhook processing failed")
            return web.Response(status=500, text="processing failed")
        if not ok:
            await _send_admin_webhook_dump(bot, data, "valid signed request was not matched to this bot")
        return web.json_response({"status": "ok" if ok else "ignored"})

    return handler


@web.middleware
async def _performance_middleware(request: web.Request, handler):
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers["ngrok-skip-browser-warning"] = "true"
        path = request.path
        if path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, trbt-signature, X-Tribute-Signature, X-Triboote-Signature, X-Signature"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if path.startswith("/static/"):
            if path.endswith((".js", ".css", ".html")):
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            else:
                resp.headers["Cache-Control"] = "public, max-age=31536000"
    return resp


def build_app(bot: Bot) -> web.Application:
    async def _ping(request: web.Request) -> web.Response:
        log.info("Ping %s from %s", request.path, request.remote)
        return web.Response(text="OK")

    async def _api_health(request: web.Request) -> web.Response:
        uptime = int(time.monotonic() - _START_TIME)
        log.info("API health check from %s", request.remote)
        return web.json_response({"status": "ok", "uptime": uptime})

    _PING_PATHS = {"/api/health", "/api/ping", "/api/nosleep", "/health"}

    @web.middleware
    async def _ping_middleware(request: web.Request, handler):
        if request.path in _PING_PATHS:
            if request.path == "/api/health":
                return await _api_health(request)
            return await _ping(request)
        return await handler(request)

    app = web.Application(client_max_size=50 * 1024 * 1024, middlewares=[_ping_middleware, _performance_middleware])
    app["bot"] = bot
    setup_api_routes(app)
    app.router.add_get("/", index_handler)
    app.router.add_get("/index.html", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/health", _api_health)
    app.router.add_get("/api/ping", _ping)
    app.router.add_get("/api/nosleep", _ping)
    app.router.add_get("/api/plans", plans_json_handler)
    app.router.add_get("/api/site", site_json_handler)
    app.router.add_get("/api/images", images_json_handler)
    app.router.add_post("/api/select-plan", select_plan_api_handler)
    app.router.add_get("/triboote/success", triboote_success_handler)
    app.router.add_get("/triboote/fail", triboote_fail_handler)
    app.router.add_post("/api/webhook", make_triboote_webhook_handler(bot))
    app.router.add_post("/triboote/webhook", make_triboote_webhook_handler(bot))
    app.router.add_static("/static", path=str(WEBAPP_DIR), show_index=False)

    if ADMIN_WEB_SECRET_PATH:
        async def web_admin_handler(request: web.Request) -> web.Response:
            auth_header = request.headers.get("Authorization")
            if not auth_header:
                return web.Response(
                    status=401,
                    headers={"WWW-Authenticate": 'Basic realm="Admin Panel"'},
                    text="Unauthorized",
                )
            return web.Response(
                content_type="text/html",
                charset="utf-8",
                text=(
                    "<!doctype html><html><head><meta charset=\'utf-8\'><title>Admin</title>"
                    "<style>body{background:#0a0a0a;color:#00ff88;font-family:monospace;padding:40px}</style>"
                    "</head><body>"
                    "<h1>Панель администратора</h1>"
                    "<p>Используйте /adm в Telegram для управления.</p>"
                    "</body></html>"
                ),
            )
        app.router.add_get(f"/{ADMIN_WEB_SECRET_PATH}/admin", web_admin_handler)

    return app


async def start_web_server(bot: Bot) -> web.AppRunner:
    app = build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=WEB_HOST, port=WEB_PORT)
    await site.start()
    log.info("Web server listening on http://%s:%s (PORT env=%s)", WEB_HOST, WEB_PORT, os.getenv("PORT", "not set"))
    return runner
