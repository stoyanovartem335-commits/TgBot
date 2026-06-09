from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return int(raw)


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Plan:
    code: str
    label: str
    days: int | None
    price_rub: int
    price_stars: int

    @property
    def is_forever(self) -> bool:
        return self.days is None


BOT_TOKEN: str = _req("BOT_TOKEN")
ADMIN_ID: int = _int("ADMIN_ID")
SUPPORT_USERNAME: str = (os.getenv("SUPPORT_USERNAME") or "").lstrip("@")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "TestKeyBot_bot")

MONGO_URI: str = _req("MONGO_URI")

API_SERVER_URL: str = _req("API_SERVER_URL").rstrip("/")
API_ADMIN_TOKEN: str = _req("API_ADMIN_TOKEN")

WEBAPP_URL: str = _req("WEBAPP_URL").rstrip("/")
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("PORT") or os.getenv("WEB_PORT") or 8080)

REQUISITES_TEXT: str = os.getenv("REQUISITES_TEXT", "")
REQUISITES_CARD: str = os.getenv("REQUISITES_CARD", "")
REQUISITES_NAME: str = os.getenv("REQUISITES_NAME", "")

TRIBOOTE_API_URL: str = (os.getenv("TRIBOOTE_API_URL") or "").rstrip("/")
TRIBOOTE_API_KEY: str = os.getenv("TRIBOOTE_API_KEY", "")
TRIBOOTE_WEBHOOK_SECRET: str = os.getenv("TRIBOOTE_WEBHOOK_SECRET", "")

TRIBUTE_API_URL: str = _env_first(
    "TRIBUTE_API_URL",
    "TRIBOOTE_API_URL",
    default="https://tribute.tg/api/v1",
).rstrip("/")
TRIBUTE_API_KEY: str = _env_first("TRIBUTE_API_KEY", "TRIBOOTE_API_KEY")
TRIBUTE_WEBHOOK_SECRET: str = _env_first(
    "TRIBUTE_WEBHOOK_SECRET",
    "TRIBOOTE_WEBHOOK_SECRET",
    "TRIBUTE_API_KEY",
    "TRIBOOTE_API_KEY",
)
TRIBUTE_PAYMENT_MODE: str = _env_first("TRIBUTE_PAYMENT_MODE", "TRIBOOTE_PAYMENT_MODE", default="auto").lower()
TRIBUTE_CURRENCY: str = _env_first("TRIBUTE_CURRENCY", "TRIBOOTE_CURRENCY", default="rub").lower()

_PLAN_ENV_SUFFIXES = {
    "1m": "1M",
    "2m": "2M",
    "3m": "3M",
    "6m": "6M",
    "forever": "FOREVER",
}


def _plan_env_map(kind: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for code, suffix in _PLAN_ENV_SUFFIXES.items():
        value = _env_first(
            f"TRIBUTE_PRODUCT_{kind}_{suffix}",
            f"TRIBOOTE_PRODUCT_{kind}_{suffix}",
            f"TRIBUTE_{suffix}_{kind}",
            f"TRIBOOTE_{suffix}_{kind}",
        ).strip()
        if value:
            result[code] = value
    return result


TRIBUTE_PRODUCT_URLS: dict[str, str] = _plan_env_map("URL")
TRIBUTE_PRODUCT_IDS: dict[str, str] = _plan_env_map("ID")
TRIBUTE_PRODUCT_NAMES: dict[str, str] = _plan_env_map("NAME")

TG_CHANNEL_URL: str = os.getenv("TG_CHANNEL_URL", "https://t.me/KalivanVC")

ZIP_FILE_PATH: Path = Path(os.getenv("ZIP_FILE_PATH", "./Price_by_KALYVAN.zip"))

ADMIN_WEB_SECRET_PATH: str = os.getenv("ADMIN_WEB_SECRET_PATH", "")

BASE_DIR: Path = Path(__file__).resolve().parent.parent
WEBAPP_DIR: Path = BASE_DIR / "webapp"


def support_url() -> str:
    if SUPPORT_USERNAME:
        return f"https://t.me/{SUPPORT_USERNAME}"
    return f"tg://user?id={ADMIN_ID}"


def plans_for_webapp(plans_list: list) -> list[dict]:
    return [
        {"code": p.code, "label": p.label, "price_rub": p.price_rub}
        for p in plans_list
    ]


def site_config_for_webapp() -> dict:
    return {
        "title": "Таблица Калывана",
        "tg_channel_url": TG_CHANNEL_URL,
    }
