from __future__ import annotations

from ..database import get_settings
from .plans import (
    DEFAULT_PRICES_RUB,
    DEFAULT_PRICES_STARS,
    DEFAULT_TARIFF_DESCRIPTIONS,
    PLAN_CODES,
    PLAN_DEFS,
    normalize_plan_map,
)


def _is_true(value) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on", "вкл")
    return bool(value)


def _pct(value) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(parsed, 100))


def normalize_discounts(discounts: dict | None) -> dict:
    source = discounts or {}
    plans_source = source.get("plans")
    if not isinstance(plans_source, dict):
        plans_source = {}
    plans = {}
    for code in PLAN_CODES:
        raw = plans_source.get(code, {})
        if not isinstance(raw, dict):
            raw = {"enabled": False, "percentage": raw}
        plans[code] = {
            "enabled": _is_true(raw.get("enabled", False)),
            "percentage": _pct(raw.get("percentage", 0)),
        }
    return {
        "enabled": _is_true(source.get("enabled", False)),
        "percentage": _pct(source.get("percentage", 0)),
        "duration_days": source.get("duration_days", 30),
        "plans": plans,
    }


def apply_discount(price: int, discount_pct: int) -> int:
    if discount_pct <= 0:
        return int(price or 0)
    return int(round(int(price or 0) * (100 - discount_pct) / 100))


def effective_discount_for_plan_from_settings(settings: dict, plan_code: str) -> tuple[bool, int, str]:
    discounts = normalize_discounts(settings.get("discounts", {}))
    plan_discount = discounts["plans"].get(plan_code, {"enabled": False, "percentage": 0})
    if _is_true(plan_discount.get("enabled", False)) and _pct(plan_discount.get("percentage", 0)) > 0:
        return True, _pct(plan_discount.get("percentage", 0)), "plan"
    if _is_true(discounts.get("enabled", False)) and _pct(discounts.get("percentage", 0)) > 0:
        return True, _pct(discounts.get("percentage", 0)), "global"
    return False, 0, "none"


async def get_effective_discount_for_plan(plan_code: str) -> tuple[bool, int, str]:
    settings = await get_settings()
    return effective_discount_for_plan_from_settings(settings, plan_code)


async def get_active_discount() -> tuple[bool, int]:
    settings = await get_settings()
    discounts = normalize_discounts(settings.get("discounts", {}))
    return discounts["enabled"], discounts["percentage"]


async def price_with_active_discount(price: int, plan_code: str | None = None) -> int:
    if plan_code:
        enabled, pct, _ = await get_effective_discount_for_plan(plan_code)
        return apply_discount(price, pct) if enabled else int(price or 0)
    enabled, pct = await get_active_discount()
    return apply_discount(price, pct) if enabled and pct > 0 else int(price or 0)


async def get_plans_from_settings() -> list[dict]:
    settings = await get_settings()
    prices_rub = normalize_plan_map(settings.get("prices_rub", {}), DEFAULT_PRICES_RUB)
    prices_stars = normalize_plan_map(settings.get("prices_stars", {}), DEFAULT_PRICES_STARS)
    highlighted = settings.get("highlighted_tariff", "3m")
    descriptions = normalize_plan_map(settings.get("tariff_descriptions", {}), DEFAULT_TARIFF_DESCRIPTIONS)

    plans = []
    for code, label, days in PLAN_DEFS:
        discount_enabled, discount_pct, discount_source = effective_discount_for_plan_from_settings(settings, code)
        rub = int(prices_rub.get(code, 0) or 0)
        stars = int(prices_stars.get(code, 0) or 0)
        plans.append({
            "code": code,
            "label": label,
            "days": days,
            "price_rub": rub,
            "price_stars": stars,
            "discount_enabled": discount_enabled,
            "discount_percentage": discount_pct,
            "discount_source": discount_source,
            "discounted_price_rub": apply_discount(rub, discount_pct) if discount_enabled else rub,
            "discounted_price_stars": apply_discount(stars, discount_pct) if discount_enabled else stars,
            "description": descriptions.get(code, ""),
            "highlighted": code == highlighted,
        })
    return plans


async def get_promotion_status() -> tuple[bool, str]:
    settings = await get_settings()
    promo = settings.get("promotion", {})
    return promo.get("enabled", False), promo.get("text", "")
