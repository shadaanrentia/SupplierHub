
"""
SupplierHub 2.0 - SKU Eligibility Unit Tests

Tests:
1. Supplier price validation
2. SKU export eligibility
3. Active/inactive variant filtering
4. Invalid and negative prices
5. Negative inventory

These tests use local data only.
No database or Lightspeed API connection is required.
"""

import pytest

from sku_eligibility import (
    missing_price,
    skip_sku,
    eligible_variants,
)


# ============================================================
# 1. SUPPLIER PRICE VALIDATION
# ============================================================

@pytest.mark.parametrize(
    "price,expected",
    [
        (10.00, False),
        (2.49, False),
        (0, True),
        ("-", True),
        ("—", True),
        ("", True),
        (None, True),
    ],
)
def test_missing_price(price, expected):
    assert missing_price(price) is expected


# ============================================================
# 2. SKU EXPORT ELIGIBILITY
# ============================================================

@pytest.mark.parametrize(
    "price,inventory,expected",
    [
        (10, 100, False),
        (10, 1, False),
        (10, 0, False),
        (0, 100, True),
        ("-", 100, True),
        (None, 50, True),
        ("-", 0, True),
    ],
)
def test_skip_sku(price, inventory, expected):
    product = {
        "price": price,
        "inventory": inventory,
    }

    assert skip_sku(product) is expected


# ============================================================
# 3. FILTER ELIGIBLE PRODUCT VARIANTS
# ============================================================

def test_eligible_variants():
    variants = [
        {
            "variant_sku": "SKU001",
            "price": 10,
            "inventory": 100,
            "is_active": True,
        },
        {
            "variant_sku": "SKU002",
            "price": 0,
            "inventory": 100,
            "is_active": True,
        },
        {
            "variant_sku": "SKU003",
            "price": 10,
            "inventory": 0,
            "is_active": True,
        },
        {
            "variant_sku": "SKU004",
            "price": 10,
            "inventory": 50,
            "is_active": False,
        },
    ]

    result = eligible_variants(variants)

    assert len(result) == 2
    assert {row["variant_sku"] for row in result} == {"SKU001", "SKU003"}


# ============================================================
# 4. INVALID SUPPLIER PRICE EDGE CASES
# ============================================================

@pytest.mark.parametrize(
    "price",
    [
        -10,
        "-5.00",
        "invalid",
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_supplier_prices_are_rejected(price):
    assert missing_price(price) is True


# ============================================================
# 5. NEGATIVE INVENTORY EDGE CASES
# ============================================================

@pytest.mark.parametrize(
    "inventory",
    [
        -1,
        -100,
    ],
)
def test_negative_inventory_is_not_exportable(inventory):
    product = {
        "price": 10,
        "inventory": inventory,
    }

    assert skip_sku(product) is True

@pytest.mark.parametrize(
    "inventory",
    [
        None,
        "",
        "invalid",
        float("nan"),
        float("inf"),
    ],
)
def test_invalid_inventory_is_rejected(inventory):
    row = {"price": 10, "inventory": inventory}
    assert skip_sku(row) is True


@pytest.mark.parametrize(
    "price,inventory",
    [
        ("10.50", "100"),
        (2.49, 1),
        ("5.00", "25"),
    ],
)
def test_valid_numeric_values_are_eligible(price, inventory):
    row = {"price": price, "inventory": inventory}
    assert skip_sku(row) is False
