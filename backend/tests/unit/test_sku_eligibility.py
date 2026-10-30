
import pytest

from sku_eligibility import (
    missing_price,
    skip_sku,
    eligible_variants,
)


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


@pytest.mark.parametrize(
    "price,inventory,expected",
    [
        (10, 100, False),
        (10, 1, False),
        (10, 0, True),
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

    assert len(result) == 1
    assert result[0]["variant_sku"] == "SKU001"
