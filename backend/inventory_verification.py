
"""Verify normalized inventory readback without performing writes."""

import math


class InventoryVerificationError(ValueError):
    """The remote inventory cannot be safely confirmed."""


def verify_inventory_level(
    records,
    product_id,
    outlet_id,
    expected_quantity,
):
    """
    Expected normalized record:
    {
    "product_id": "remote-s",
    "outlet_id": "test-outlet",
    "quantity": 0,
    }

    Do not pass raw Lightspeed responses directly.
    """
    if not isinstance(records, list):
        raise InventoryVerificationError(
            "Inventory records must be a list"
        )

    try:
        expected = float(expected_quantity)
    except (TypeError, ValueError, OverflowError):
        raise InventoryVerificationError(
            "Invalid expected inventory"
        )

    if not math.isfinite(expected) or expected < 0:
        raise InventoryVerificationError(
            "Invalid expected inventory"
        )

    matches = [
        row
        for row in records
        if isinstance(row, dict)
        and str(row.get("product_id")) == str(product_id)
        and str(row.get("outlet_id")) == str(outlet_id)
    ]

    if len(matches) != 1:
        raise InventoryVerificationError(
            "Expected exactly one inventory record "
            "for the product and outlet"
        )

    quantity = matches[0].get("quantity")

    if isinstance(quantity, bool):
        raise InventoryVerificationError(
            "Invalid remote inventory quantity"
        )

    try:
        actual = float(quantity)
    except (TypeError, ValueError, OverflowError):
        raise InventoryVerificationError(
            "Invalid remote inventory quantity"
        )

    if not math.isfinite(actual) or actual < 0:
        raise InventoryVerificationError(
            "Invalid remote inventory quantity"
        )

    if actual != expected:
        raise InventoryVerificationError(
            f"Inventory mismatch: expected {expected:g}, "
            f"received {actual:g}"
        )

    return True
