from __future__ import annotations

PAYMENT_METHODS_TEXT = "Выберите способ оплаты:"


def selected_plan_text(label: str, price_rub: int | str, price_stars: int | str, icon: str = "💵") -> str:
    return (
        "Вы выбрали:\n\n"
        f"📦 <b>{label}</b>\n"
        f"{icon} Цена: <b>{price_rub} ₽</b> / <b>{price_stars} ⭐</b>\n\n"
        f"{PAYMENT_METHODS_TEXT}"
    )
