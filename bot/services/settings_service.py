from __future__ import annotations

from ..database import get_settings
from .plans import (
    DEFAULT_PRICES_RUB,
    DEFAULT_PRICES_STARS,
    DEFAULT_TARIFF_DESCRIPTIONS,
    PLAN_DEFS,
    normalize_plan_map,
)


async def get_plans_from_settings() -> list[dict]:
    settings = await get_settings()
    prices_rub = normalize_plan_map(settings.get("prices_rub", {}), DEFAULT_PRICES_RUB)
    prices_stars = normalize_plan_map(settings.get("prices_stars", {}), DEFAULT_PRICES_STARS)
    highlighted = settings.get("highlighted_tariff", "3m")
    descriptions = normalize_plan_map(settings.get("tariff_descriptions", {}), DEFAULT_TARIFF_DESCRIPTIONS)

    return [
        {
            "code": code,
            "label": label,
            "days": days,
            "price_rub": prices_rub.get(code, 0),
            "price_stars": prices_stars.get(code, 0),
            "description": descriptions.get(code, ""),
            "highlighted": code == highlighted,
        }
        for code, label, days in PLAN_DEFS
    ]


def apply_discount(price: int, discount_pct: int) -> int:
    if discount_pct <= 0:
        return price
    return int(round(price * (100 - discount_pct) / 100))


async def price_with_active_discount(price: int) -> int:
    enabled, pct = await get_active_discount()
    if enabled and pct > 0:
        return apply_discount(price, pct)
    return price


async def get_active_discount() -> tuple[bool, int]:
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    return discounts.get("enabled", False), discounts.get("percentage", 0)


async def get_promotion_status() -> tuple[bool, str]:
    settings = await get_settings()
    promo = settings.get("promotion", {})
    return promo.get("enabled", False), promo.get("text", "")
