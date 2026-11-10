
"""
SupplierHub 2.0 - SKU Eligibility

Separates supplier/inventory validity from eligibility for creating
a new Lightspeed product.

Zero inventory is valid for existing-product inventory reconciliation,
but is not eligible when creating a new Lightspeed product.
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
    """
    Reject missing, malformed, negative, fractional, or non-finite stock.

    Zero is valid: it represents a genuine out-of-stock variant.
    """
    if value is None or isinstance(value, bool):
        return True

    try:
        inventory = float(value)
    except (ValueError, TypeError, OverflowError):
        return True

    return (
        not math.isfinite(inventory)
        or inventory < 0
        or not inventory.is_integer()
    )


def eligibility_reason(row):
    """
    Explain why a variant cannot be included in a NEW Lightspeed product.

    New product variants require positive inventory.
    """
    if row.get("is_active") is False:
        return "inactive"

    if row.get("price_needs_review") or missing_price(row.get("price")):
        return "price_missing_or_invalid"

    if invalid_inventory(row.get("inventory")):
        return "inventory_missing_or_invalid"

    try:
        quantity = float(row.get("inventory"))
    except (TypeError, ValueError, OverflowError):
        return "inventory_missing_or_invalid"

    if quantity == 0:
        return "inventory_zero"

    return None


def skip_sku(row):
    """
    Generic supplier/inventory validity check.

    Zero inventory is retained for existing-product reconciliation.
    """
    if row.get("is_active") is False:
        return True

    if row.get("price_needs_review") or missing_price(row.get("price")):
        return True

    return invalid_inventory(row.get("inventory"))


def eligible_variants(rows):
    """
    Return variants valid for supplier/inventory processing.

    Includes zero-stock variants.
    """
    return [
        dict(row)
        for row in rows
        if not skip_sku(row)
    ]


def new_export_eligible_variants(rows):
    """
    Return variants eligible for creating a NEW Lightspeed product.

    Requires valid price and positive integer inventory.
    """
    return [
        dict(row)
        for row in rows
        if eligibility_reason(row) is None
    ]
