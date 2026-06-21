from __future__ import annotations

PLAN_DEFS = (
    ("1m", "1 месяц", 30),
    ("3m", "3 месяца", 90),
    ("6m", "6 месяцев", 180),
    ("forever", "Навсегда", None),
)

PLAN_CODES = tuple(code for code, _, _ in PLAN_DEFS)
PLAN_LABELS = {code: label for code, label, _ in PLAN_DEFS}
PLAN_DAYS = {code: days for code, _, days in PLAN_DEFS}

DEFAULT_PRICES_RUB = {"1m": 299, "3m": 799, "6m": 1499, "forever": 4999}
DEFAULT_PRICES_STARS = {"1m": 150, "3m": 400, "6m": 750, "forever": 2500}
DEFAULT_TARIFF_DESCRIPTIONS = {
    "1m": "Базовый доступ на 30 дней",
    "3m": "Самый популярный выбор",
    "6m": "Доступ на 180 дней",
    "forever": "Бессрочный доступ",
}


def normalize_plan_map(values: dict | None, defaults: dict) -> dict:
    source = values or {}
    return {code: source.get(code, defaults.get(code, 0)) for code in PLAN_CODES}


def plan_code_by_label(label: str) -> str | None:
    normalized = (label or "").strip().casefold()
    aliases = {
        "forever": "forever",
        "навсегда": "forever",
        "бессрочно": "forever",
    }
    if normalized in aliases:
        return aliases[normalized]
    for code, plan_label in PLAN_LABELS.items():
        if normalized == plan_label.casefold():
            return code
    return None
