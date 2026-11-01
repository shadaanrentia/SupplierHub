
import pytest

from inventory_verification import (
    InventoryVerificationError,
    verify_inventory_level,
)
from lightspeed_inventory_adapter import (
    normalize_inventory_levels,
)


def test_matching_zero_stock():
    response = {
        "data": [{
            "product_id": "remote-s",
            "location_id": "outlet-1",
            "current_inventory_level": 0,
        }]
    }

    records = normalize_inventory_levels(response)

    assert verify_inventory_level(
        records, "remote-s", "outlet-1", 0
    )


def test_stale_stock_is_rejected():
    response = {
        "data": [{
            "product_id": "remote-s",
            "location_id": "outlet-1",
            "current_inventory_level": 25,
        }]
    }

    records = normalize_inventory_levels(response)

    with pytest.raises(
        InventoryVerificationError, match="mismatch"
    ):
        verify_inventory_level(
            records, "remote-s", "outlet-1", 0
        )


def test_wrong_outlet_is_rejected():
    response = [{
        "product_id": "remote-s",
        "location_id": "other-outlet",
        "current_inventory_level": 0,
    }]

    records = normalize_inventory_levels(response)

    with pytest.raises(InventoryVerificationError):
        verify_inventory_level(
            records, "remote-s", "outlet-1", 0
        )


def test_missing_quantity_is_rejected():
    response = {
        "data": [{
            "product_id": "remote-s",
            "location_id": "outlet-1",
        }]
    }

    with pytest.raises(
        InventoryVerificationError, match="Missing required"
    ):
        normalize_inventory_levels(response)


def test_unknown_response_structure_is_rejected():
    with pytest.raises(
        InventoryVerificationError, match="Unknown"
    ):
        normalize_inventory_levels(
            {"unexpected": []}
        )


def test_duplicate_outlet_records_are_rejected():
    response = {
        "data": [
            {
                "product_id": "remote-s",
                "location_id": "outlet-1",
                "current_inventory_level": 0,
            },
            {
                "product_id": "remote-s",
                "location_id": "outlet-1",
                "current_inventory_level": 0,
            },
        ]
    }

    records = normalize_inventory_levels(response)

    with pytest.raises(
        InventoryVerificationError, match="exactly one"
    ):
        verify_inventory_level(
            records, "remote-s", "outlet-1", 0
        )
