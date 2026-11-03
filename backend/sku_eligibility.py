
"""
SupplierHub 2.0 - SKU Export Eligibility

Validates supplier price and inventory for new exports.

Supplier records are never deleted by these functions.
"""

import math


def missing_price(value):
    """Return True when the supplier price is unusable."""
    if value is None:
        return True

    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "—"):
            return True

    try:
        price = float(value)
    except (ValueError, TypeError, OverflowError):
        return True

    return not math.isfinite(price) or price <= 0


def invalid_inventory(value):
    """Reject missing, malformed, non-finite or negative or fractional stock."""
    if value is None or isinstance(value, bool):
        return True

    try:
        inventory = float(value)
    except (ValueError, TypeError, OverflowError):
        return True

    return not math.isfinite(inventory) or inventory < 0 or not inventory.is_integer()


def skip_sku(row):
    """Skip a SKU when either price or stock is invalid."""
    return (
        missing_price(row.get("price"))
        or invalid_inventory(row.get("inventory"))
    )


def eligible_variants(rows):
    """Return active variants eligible for new export."""
    return [
        dict(row)
        for row in rows
        if row.get("is_active") is not False
        and not skip_sku(row)
    ]
