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

API_ADMIN_TOKEN: str = _req("API_ADMIN_TOKEN")

WEBAPP_URL: str = _req("WEBAPP_URL").rstrip("/")
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("PORT") or os.getenv("WEB_PORT") or 8080)

TRIBUTE_API_KEY: str = os.getenv("TRIBUTE_API_KEY", "")
TRIBUTE_SUBSCRIPTION_URL: str = (os.getenv("TRIBUTE_SUBSCRIPTION_URL") or "https://t.me/tribute/app?startapp=sYQs").strip()
REQUISITES_CARD: str = (os.getenv("REQUISITES_CARD") or "9112 3801 7082 5501").strip()
FUNPAY_URLS: dict[str, str] = {
    "1m": (os.getenv("FUNPAY_URL_1M") or "https://funpay.com/lots/offer?id=45877171").strip(),
    "3m": (os.getenv("FUNPAY_URL_3M") or "https://funpay.com/lots/offer?id=45877215").strip(),
    "6m": (os.getenv("FUNPAY_URL_6M") or "https://funpay.com/lots/offer?id=45877232").strip(),
    "forever": (os.getenv("FUNPAY_URL_FOREVER") or "https://funpay.com/lots/offer?id=45877250").strip(),
}

_PLAN_ENV_SUFFIXES = {
    "1m": "1M",
    "3m": "3M",
    "6m": "6M",
    "forever": "FOREVER",
}


def _plan_env_map(prefix: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for code, suffix in _PLAN_ENV_SUFFIXES.items():
        value = (os.getenv(f"{prefix}_{suffix}") or "").strip()
        if value:
            result[code] = value
    return result


TRIBUTE_PERIOD_IDS: dict[str, str] = _plan_env_map("TRIBUTE_PERIOD_ID")


def _csv_env(name: str) -> set[str]:
    return {
        item.strip()
        for item in (os.getenv(name) or "").split(",")
        if item.strip()
    }


TRIBUTE_ALLOWED_CHANNEL_IDS: set[str] = _csv_env("TRIBUTE_ALLOWED_CHANNEL_IDS")
TRIBUTE_ALLOWED_CHANNEL_NAMES: set[str] = _csv_env("TRIBUTE_ALLOWED_CHANNEL_NAMES")
TRIBUTE_ALLOWED_SUBSCRIPTION_IDS: set[str] = _csv_env("TRIBUTE_ALLOWED_SUBSCRIPTION_IDS")
TRIBUTE_DEBUG_WEBHOOKS: bool = os.getenv("TRIBUTE_DEBUG_WEBHOOKS", "0").lower() in {"1", "true", "yes", "on"}

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
