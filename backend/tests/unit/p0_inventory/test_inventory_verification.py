
import pytest

from inventory_verification import (
    verify_inventory_level,
    InventoryVerificationError,
)


def record(quantity, outlet="outlet-1", product="remote-s"):
    return {
        "product_id": product,
        "outlet_id": outlet,
        "quantity": quantity,
    }


def test_zero_inventory_verified():
    assert verify_inventory_level(
        [record(0)], "remote-s", "outlet-1", 0
    )


def test_positive_inventory_verified():
    assert verify_inventory_level(
        [record(25)], "remote-s", "outlet-1", 25
    )


def test_inventory_mismatch_rejected():
    with pytest.raises(
        InventoryVerificationError, match="mismatch"
    ):
        verify_inventory_level(
            [record(25)], "remote-s", "outlet-1", 0
        )


def test_wrong_outlet_rejected():
    with pytest.raises(
        InventoryVerificationError,
        match="exactly one",
    ):
        verify_inventory_level(
            [record(0, outlet="other-outlet")],
            "remote-s",
            "outlet-1",
            0,
        )


def test_wrong_product_rejected():
    with pytest.raises(InventoryVerificationError):
        verify_inventory_level(
            [record(0, product="another-product")],
            "remote-s",
            "outlet-1",
            0,
        )


def test_duplicate_records_rejected():
    with pytest.raises(
        InventoryVerificationError, match="exactly one"
    ):
        verify_inventory_level(
            [record(0), record(0)],
            "remote-s",
            "outlet-1",
            0,
        )


@pytest.mark.parametrize(
    "quantity",
    [None, "", "invalid", float("nan"), float("inf"), -1, True],
)
def test_invalid_remote_quantities_rejected(quantity):
    with pytest.raises(InventoryVerificationError):
        verify_inventory_level(
            [record(quantity)], "remote-s", "outlet-1", 0
        )


def test_missing_inventory_record_rejected():
    with pytest.raises(InventoryVerificationError):
        verify_inventory_level(
            [], "remote-s", "outlet-1", 0
        )
