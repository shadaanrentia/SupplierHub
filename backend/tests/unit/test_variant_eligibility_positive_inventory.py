
import pytest

from sku_eligibility import (
    eligibility_reason,
    eligible_variants,
    invalid_inventory,
    new_export_eligible_variants,
    skip_sku,
)


@pytest.mark.parametrize(
    "value",
    [None, "", "-", -1, float("nan"), float("inf"), 1.5, True],
)
def test_invalid_inventory_is_rejected(value):
    assert invalid_inventory(value) is True


@pytest.mark.parametrize("value", [0, 1, 2, "3", 25])
def test_valid_inventory_includes_zero(value):
    assert invalid_inventory(value) is False


def test_zero_inventory_is_retained_for_inventory_reconciliation():
    variants = [
        {
            "variant_sku": "IN-STOCK",
            "price": 10,
            "inventory": 2,
            "is_active": True,
        },
        {
            "variant_sku": "OUT-OF-STOCK",
            "price": 10,
            "inventory": 0,
            "is_active": True,
        },
    ]

    eligible = eligible_variants(variants)

    assert [row["variant_sku"] for row in eligible] == [
        "IN-STOCK",
        "OUT-OF-STOCK",
    ]

    assert len(variants) == 2
    assert skip_sku(variants[1]) is False


def test_zero_inventory_is_excluded_from_new_product_creation():
    variants = [
        {
            "variant_sku": "IN-STOCK",
            "price": 10,
            "inventory": 2,
            "is_active": True,
        },
        {
            "variant_sku": "OUT-OF-STOCK",
            "price": 10,
            "inventory": 0,
            "is_active": True,
        },
    ]

    eligible = new_export_eligible_variants(variants)

    assert [row["variant_sku"] for row in eligible] == ["IN-STOCK"]
    assert eligibility_reason(variants[1]) == "inventory_zero"


def test_invalid_price_is_not_export_eligible():
    row = {"price": 0, "inventory": 4}

    assert eligibility_reason(row) == "price_missing_or_invalid"
    assert skip_sku(row) is True
    assert new_export_eligible_variants([row]) == []


def test_price_needs_review_blocks_new_export():
    row = {
        "price": 12.5,
        "price_needs_review": True,
        "inventory": 4,
    }

    assert eligibility_reason(row) == "price_missing_or_invalid"
    assert new_export_eligible_variants([row]) == []


def test_inactive_variant_is_not_export_eligible():
    row = {
        "price": 12.5,
        "inventory": 4,
        "is_active": False,
    }

    assert eligibility_reason(row) == "inactive"
    assert new_export_eligible_variants([row]) == []
