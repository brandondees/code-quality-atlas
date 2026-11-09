# SPDX-License-Identifier: MIT
def line_total(price_cents: int, quantity: int, discount_pct: int) -> int:
    gross = price_cents * quantity
    discount = round(gross * discount_pct / 100)
    return gross - discount
