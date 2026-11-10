import pytest

from sku_eligibility import eligibility_reason, eligible_variants, invalid_inventory, skip_sku


@pytest.mark.parametrize("value", [None, "", "-", 0, -1, float("nan"), float("inf"), 1.5, True])
def test_invalid_inventory_is_not_export_eligible(value):
    assert invalid_inventory(value) is True


@pytest.mark.parametrize("value", [1, 2, "3", 25])
def test_positive_integer_inventory_is_export_eligible(value):
    assert invalid_inventory(value) is False


def test_zero_inventory_variant_is_retained_in_supplier_data_but_excluded_from_export():
    variants = [
        {"variant_sku": "IN-STOCK", "price": 10, "inventory": 2, "is_active": True},
        {"variant_sku": "OUT-OF-STOCK", "price": 10, "inventory": 0, "is_active": True},
    ]

    eligible = eligible_variants(variants)

    assert [row["variant_sku"] for row in eligible] == ["IN-STOCK"]
    assert len(variants) == 2
    assert eligibility_reason(variants[1]) == "inventory_zero"
    assert skip_sku(variants[1]) is True


def test_invalid_price_is_not_export_eligible_even_with_positive_inventory():
    row = {"price": 0, "inventory": 4}
    assert eligibility_reason(row) == "price_missing_or_invalid"
    assert skip_sku(row) is True


def test_price_needs_review_blocks_export_even_when_last_valid_price_is_retained():
    row = {"price": 12.5, "price_needs_review": True, "inventory": 4}
    assert eligibility_reason(row) == "price_missing_or_invalid"
