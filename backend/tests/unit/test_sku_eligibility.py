import math

import pytest

from sku_eligibility import (
    eligibility_reason,
    eligible_variants,
    lightspeed_sync_eligible_variants,
    missing_price,
    new_export_eligible_variants,
)


@pytest.mark.parametrize("price", [None, "", "-", "—", 0, -1, "NaN", "Infinity", "not-a-price"])
def test_invalid_prices_are_not_eligible_for_lightspeed(price):
    row = {"id": "v1", "variant_sku": "SKU-1", "price": price, "inventory": 5}
    assert missing_price(price)
    assert eligibility_reason(row) == "price_missing_or_invalid"
    assert lightspeed_sync_eligible_variants([row]) == []


@pytest.mark.parametrize("inventory", [None, "", -1, 1.5, "NaN", "Infinity"])
def test_invalid_inventory_is_not_eligible_for_lightspeed(inventory):
    row = {"id": "v1", "variant_sku": "SKU-1", "price": 10, "inventory": inventory}
    assert lightspeed_sync_eligible_variants([row]) == []


def test_zero_stock_is_retained_as_supplier_data_but_not_exported():
    row = {"id": "v1", "variant_sku": "SKU-1", "price": 10, "inventory": 0}
    assert eligible_variants([row]) == [row]
    assert new_export_eligible_variants([row]) == []
    assert lightspeed_sync_eligible_variants([row]) == []
    assert eligibility_reason(row) == "inventory_zero"


def test_positive_stock_and_price_are_export_eligible():
    row = {"id": "v1", "variant_sku": "SKU-1", "price": 10.5, "inventory": 2}
    assert lightspeed_sync_eligible_variants([row]) == [row]


def test_price_needs_review_blocks_even_when_last_valid_price_is_present():
    row = {"id": "v1", "variant_sku": "SKU-1", "price": 10, "inventory": 2, "price_needs_review": True}
    assert lightspeed_sync_eligible_variants([row]) == []


def test_inactive_variant_is_not_exported():
    row = {"id": "v1", "variant_sku": "SKU-1", "price": 10, "inventory": 2, "is_active": False}
    assert lightspeed_sync_eligible_variants([row]) == []
