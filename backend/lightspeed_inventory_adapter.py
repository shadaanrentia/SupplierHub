
"""Normalize Lightspeed inventory-level records for verification.

This module makes no network calls and performs no writes.
"""

from inventory_verification import InventoryVerificationError


def normalize_inventory_levels(response):
    """
    Normalize a complete inventory-level collection.

    Supported shapes:
    - A list of inventory-level objects.
    - A response with a 'data' list.

    Reject unknown structures rather than guessing.
    """

    if isinstance(response, list):
        records = response
    elif isinstance(response, dict) and isinstance(
        response.get("data"), list
    ):
        records = response["data"]
    else:
        raise InventoryVerificationError(
            "Unknown Lightspeed inventory response structure"
        )

    normalized = []

    for row in records:
        if not isinstance(row, dict):
            raise InventoryVerificationError(
                "Invalid inventory-level record"
            )

        required = (
            "product_id",
            "location_id",
            "current_inventory_level",
        )

        if any(key not in row for key in required):
            raise InventoryVerificationError(
                "Missing required Lightspeed inventory fields"
            )

        normalized.append({
            "product_id": row["product_id"],
            "outlet_id": row["location_id"],
            "quantity": row["current_inventory_level"],
        })

    return normalized
