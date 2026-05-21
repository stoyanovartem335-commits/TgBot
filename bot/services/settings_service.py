"""MongoDB settings service - prices, discounts, tariffs."""
from __future__ import annotations

from ..database import get_settings, update_settings


async def get_plans_from_settings() -> list[dict]:
    """Get current plans from MongoDB settings."""
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})
    highlighted = settings.get("highlighted_tariff", "3m")
    descriptions = settings.get("tariff_descriptions", {})

    plans_def = [
        ("1m", "1 \u043c\u0435\u0441\u044f\u0446", 30),
        ("2m", "2 \u043c\u0435\u0441\u044f\u0446\u0430", 60),
        ("3m", "3 \u043c\u0435\u0441\u044f\u0446\u0430", 90),
        ("6m", "6 \u043c\u0435\u0441\u044f\u0446\u0435\u0432", 180),
        ("forever", "Forever", None),
    ]

    result = []
    for code, label, days in plans_def:
        result.append({
            "code": code,
            "label": label,
            "days": days,
            "price_rub": prices_rub.get(code, 0),
            "price_stars": prices_stars.get(code, 0),
            "description": descriptions.get(code, ""),
            "highlighted": code == highlighted,
        })
    return result


async def apply_discount(price: int, discount_pct: int) -> int:
    """Apply discount and round to integer."""
    if discount_pct <= 0:
        return price
    discounted = price * (100 - discount_pct) / 100
    return int(round(discounted))


async def get_active_discount() -> tuple[bool, int]:
    """Returns (enabled, percentage)."""
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    return discounts.get("enabled", False), discounts.get("percentage", 0)


async def get_promotion_status() -> tuple[bool, str]:
    settings = await get_settings()
    promo = settings.get("promotion", {})
    return promo.get("enabled", False), promo.get("text", "")
