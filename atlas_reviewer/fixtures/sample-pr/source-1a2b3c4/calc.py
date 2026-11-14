# SPDX-License-Identifier: MIT
def line_total(price_cents: int, quantity: int, discount_pct: int) -> int:
    return price_cents * quantity * (100 - discount_pct) // 100
