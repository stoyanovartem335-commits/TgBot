"""aiohttp server: WebApp static + Triboote webhook + health + optional admin web panel."""
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
    return web.json_response(plans)


async def site_json_handler(request: web.Request) -> web.Response:
    from .config import site_config_for_webapp, BOT_USERNAME
    data = site_config_for_webapp()
    data["bot_username"] = BOT_USERNAME
    return web.json_response(data)


async def triboote_success_handler(request: web.Request) -> web.Response:
    return web.Response(
        content_type="text/html",
        charset="utf-8",
        text=(
            "<!doctype html><meta charset=\'utf-8\'>"
            "<title>\u041e\u043f\u043b\u0430\u0442\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430</title>"
            "<body style=\'font-family:system-ui;text-align:center;padding:40px\'>"
            "<h2>\u2705 \u041f\u043b\u0430\u0442\u0451\u0436 \u043f\u043e\u043b\u0443\u0447\u0435\u043d</h2>"
            "<p>\u0412\u043e\u0437\u0432\u0440\u0430\u0449\u0430\u0439\u0442\u0435\u0441\u044c \u0432 Telegram \u2014 \u0431\u043e\u0442 \u043f\u0440\u0438\u0448\u043b\u0451\u0442 \u0442\u043e\u043a\u0435\u043d \u0438 \u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u044e.</p>"
            "</body>"
        ),
    )


def _verify_triboote_signature(body: bytes, header_sig: str | None) -> bool:
    if not TRIBOOTE_WEBHOOK_SECRET:
        log.warning("TRIBOOTE_WEBHOOK_SECRET not set \u2014 accepting without verification")
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
async def _ngrok_skip_middleware(request: web.Request, handler):
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers["ngrok-skip-browser-warning"] = "true"
    return resp


def build_app(bot: Bot) -> web.Application:
    app = web.Application(middlewares=[_ngrok_skip_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/index.html", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/plans", plans_json_handler)
    app.router.add_get("/api/site", site_json_handler)
    app.router.add_get("/triboote/success", triboote_success_handler)
    app.router.add_post("/triboote/webhook", make_triboote_webhook_handler(bot))
    app.router.add_static("/static", path=str(WEBAPP_DIR), show_index=False)

    # Optional hidden web admin panel
    if ADMIN_WEB_SECRET_PATH:
        async def web_admin_handler(request: web.Request) -> web.Response:
            from aiohttp import BasicAuth
            from .config import ADMIN_ID
            # Simple auth check
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
                    "<h1>\u041f\u0430\u043d\u0435\u043b\u044c \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430</h1>"
                    "<p>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 /adm \u0432 Telegram \u0434\u043b\u044f \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f.</p>"
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
