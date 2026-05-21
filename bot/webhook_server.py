from __future__ import annotations

import hmac
import json
import logging
from hashlib import sha256

from aiogram import Bot
from aiohttp import web

from .config import (
    ADMIN_WEB_SECRET_PATH,
    TRIBOOTE_WEBHOOK_SECRET,
    WEB_HOST,
    WEB_PORT,
    WEBAPP_DIR,
)
from .database import get_settings
from .handlers.triboote import complete_from_webhook
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
    return web.json_response({"status": "ok", "service": "telegram-bot"})


async def plans_json_handler(request: web.Request) -> web.Response:
    plans = await get_plans_from_settings()
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    return web.json_response({
        "plans": plans,
        "discount": {
            "enabled": discounts.get("enabled", False),
            "percentage": discounts.get("percentage", 0)
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


def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    from urllib.parse import parse_qsl
    try:
        parsed = dict(parse_qsl(init_data))
        if "hash" not in parsed:
            return None
        
        received_hash = parsed.pop("hash")
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

    from .services.settings_service import get_plans_from_settings, get_active_discount, apply_discount
    plans = await get_plans_from_settings()
    plan = next((p for p in plans if p["code"] == plan_code), None)
    if not plan:
        return web.json_response({"ok": False, "error": "invalid plan code"}, status=400)

    discount_enabled, discount_pct = await get_active_discount()
    price_rub = plan["price_rub"]
    price_stars = plan["price_stars"]
    if discount_enabled and discount_pct > 0:
        price_rub = await apply_discount(price_rub, discount_pct)
        price_stars = await apply_discount(price_stars, discount_pct)

    from .keyboards import payment_methods_kb
    text = (
        "Вы выбрали:\n\n"
        f"📦 <b>{plan['label']}</b>\n"
        f"💵 Цена: <b>{price_rub} ₽</b> / <b>{price_stars} ⭐</b>\n\n"
        "Выберите способ оплаты:"
    )

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


def _verify_triboote_signature(body: bytes, header_sig: str | None) -> bool:
    if not TRIBOOTE_WEBHOOK_SECRET:
        log.warning("TRIBOOTE_WEBHOOK_SECRET not set — accepting without verification")
        return True
    if not header_sig:
        return False
    expected = hmac.new(
        TRIBOOTE_WEBHOOK_SECRET.encode("utf-8"), body, sha256
    ).hexdigest()
    candidate = header_sig.split("=", 1)[1] if "=" in header_sig else header_sig
    return hmac.compare_digest(expected, candidate.strip())


def make_triboote_webhook_handler(bot: Bot):
    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        sig = request.headers.get("X-Triboote-Signature") or request.headers.get("X-Signature")
        if not _verify_triboote_signature(body, sig):
            log.warning("Triboote webhook bad signature")
            return web.Response(status=401, text="bad signature")

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return web.Response(status=400, text="invalid json")

        status = (data.get("status") or data.get("event") or "").lower()
        payment_id = (
            data.get("external_id")
            or data.get("payment_id")
            or data.get("id")
            or ""
        )
        if not payment_id:
            return web.Response(status=400, text="missing payment id")

        if status in {"paid", "succeeded", "success", "completed", "payment.success"}:
            ok = await complete_from_webhook(bot, str(payment_id))
            return web.Response(status=200 if ok else 404, text="ok" if ok else "unknown")

        log.info("Triboote webhook ignored status=%s id=%s", status, payment_id)
        return web.Response(status=200, text="ignored")

    return handler


@web.middleware
async def _performance_middleware(request: web.Request, handler):
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers["ngrok-skip-browser-warning"] = "true"
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000"
    return resp


def build_app(bot: Bot) -> web.Application:
    app = web.Application(middlewares=[_performance_middleware])
    app["bot"] = bot
    app.router.add_get("/", index_handler)
    app.router.add_get("/index.html", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/plans", plans_json_handler)
    app.router.add_get("/api/site", site_json_handler)
    app.router.add_post("/api/select-plan", select_plan_api_handler)
    app.router.add_get("/triboote/success", triboote_success_handler)
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
    log.info("Web server listening on http://%s:%s", WEB_HOST, WEB_PORT)
    return runner
