
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
    """Reject missing, malformed, non-finite, zero, negative or fractional stock."""
    if value is None or isinstance(value, bool):
        return True

    try:
        inventory = float(value)
    except (ValueError, TypeError, OverflowError):
        return True

    return not math.isfinite(inventory) or inventory <= 0 or not inventory.is_integer()


def eligibility_reason(row):
    """Explain why a stored supplier variant cannot be exported to Lightspeed."""
    if row.get("is_active") is False:
        return "inactive"
    if row.get("price_needs_review") or missing_price(row.get("price")):
        return "price_missing_or_invalid"
    if invalid_inventory(row.get("inventory")):
        try:
            quantity = float(row.get("inventory"))
        except (TypeError, ValueError, OverflowError):
            return "inventory_missing_or_invalid"
        return "inventory_zero" if math.isfinite(quantity) and quantity == 0 else "inventory_missing_or_invalid"
    return None


def skip_sku(row):
    """Keep the source row in SupplierHub, but block export when ineligible."""
    return eligibility_reason(row) is not None


def eligible_variants(rows):
    """Return active variants eligible for new export."""
    return [
        dict(row)
        for row in rows
        if row.get("is_active") is not False
        and not skip_sku(row)
    ]
