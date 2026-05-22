from __future__ import annotations

from ..database import get_settings, update_settings

PLANS_DEF = [
    ("1m", "1 месяц", 30),
    ("2m", "2 месяца", 60),
    ("3m", "3 месяца", 90),
    ("6m", "6 месяцев", 180),
    ("forever", "Forever", None),
]


async def get_plans_from_settings() -> list[dict]:
    settings = await get_settings()
    prices_rub = settings.get("prices_rub", {})
    prices_stars = settings.get("prices_stars", {})
    highlighted = settings.get("highlighted_tariff", "3m")
    descriptions = settings.get("tariff_descriptions", {})

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
        for code, label, days in PLANS_DEF
    ]


async def apply_discount(price: int, discount_pct: int) -> int:
    if discount_pct <= 0:
        return price
    return int(round(price * (100 - discount_pct) / 100))


async def price_with_active_discount(price: int) -> int:
    enabled, pct = await get_active_discount()
    if enabled and pct > 0:
        return await apply_discount(price, pct)
    return price


async def get_active_discount() -> tuple[bool, int]:
    settings = await get_settings()
    discounts = settings.get("discounts", {})
    return discounts.get("enabled", False), discounts.get("percentage", 0)


async def get_promotion_status() -> tuple[bool, str]:
    settings = await get_settings()
    promo = settings.get("promotion", {})
    return promo.get("enabled", False), promo.get("text", "")
