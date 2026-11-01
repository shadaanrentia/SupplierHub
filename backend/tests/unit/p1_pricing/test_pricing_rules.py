
"""
SupplierHub 2.0 - Pricing Rules Unit Tests

Tests actual pricing_rules.py functions.
No external API or database operations.
"""

import pytest

from pricing_rules import (
    number,
    cents,
    pricing_policy,
    price_for,
    variant_retail,
    pricing_summary,
    apply_category_policy,
)


# 1. NUMBER VALIDATION

@pytest.mark.parametrize(
    "value,expected",
    [
        (10, 10.0),
        (2.49, 2.49),
        ("15.50", 15.5),
        (0.01, 0.01),
    ],
)
def test_valid_positive_numbers(value, expected):
    assert number(value, "Price") == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "invalid",
        -10,
        0,
        True,
        float("nan"),
        float("inf"),
    ],
)
def test_invalid_numbers(value):
    with pytest.raises(ValueError):
        number(value, "Price")


def test_zero_allowed_for_markup():
    assert number(0, "Markup", allow_zero=True) == 0


# 2. DECIMAL ROUNDING

@pytest.mark.parametrize(
    "value,expected",
    [
        ("10.125", 10.13),
        ("10.124", 10.12),
        ("2.495", 2.50),
        ("10", 10.00),
    ],
)
def test_currency_rounding(value, expected):
    assert cents(value) == expected


# 3. PRICING POLICIES

def test_global_pricing_policy():
    product = {"base_price": 10}
    variants = [{"price": 10}, {"price": 15}]

    result = pricing_policy(product, variants, 50)

    assert result["mode"] == "global"
    assert result["value"] == 50
    assert result["anchor_cost"] == 10


def test_category_percentage_policy():
    product = {
        "category_pricing_mode": "percentage",
        "category_pricing_value": 20,
        "base_price": 10,
    }

    result = pricing_policy(
        product,
        [{"price": 10}],
        global_markup=50,
    )

    assert result["mode"] == "percentage"
    assert result["value"] == 20


def test_direct_pricing_policy():
    product = {
        "category_pricing_mode": "direct",
        "category_pricing_value": 25,
        "base_price": 10,
    }

    result = pricing_policy(
        product,
        [{"price": 10}],
        global_markup=50,
    )

    assert result["mode"] == "direct"
    assert result["value"] == 25


def test_invalid_pricing_mode():
    product = {
        "category_pricing_mode": "unknown",
        "base_price": 10,
    }

    with pytest.raises(ValueError):
        pricing_policy(product, [], 50)


# 4. DIRECT PRICE CALCULATION

def test_direct_price_preserves_surcharge():
    policy = {
        "mode": "direct",
        "value": 25,
        "anchor_cost": 10,
    }

    assert price_for(10, policy) == 25
    assert price_for(12, policy) == 27
    assert price_for(15, policy) == 30


def test_direct_price_rounding():
    policy = {
        "mode": "direct",
        "value": 25,
        "anchor_cost": 10,
    }

    assert price_for(10.125, policy) == 25.13


# 5. RETAIL PRICE OVERRIDE

def test_variant_retail_override():
    variant = {
        "price": 10,
        "retail_price_override": 30,
    }

    assert variant_retail(variant, 50) == 30


def test_invalid_retail_override():
    variant = {
        "price": 10,
        "retail_price_override": -5,
    }

    with pytest.raises(ValueError):
        variant_retail(variant, 50)


# 6. PRICING SUMMARY

def test_direct_pricing_summary():
    product = {
        "base_price": 10,
        "category_pricing_mode": "direct",
        "category_pricing_value": 25,
    }

    variants = [
        {"price": 10},
        {"price": 12},
        {"price": 15},
    ]

    result = pricing_summary(product, variants, 50)

    assert result["pricing_source"] == "category"
    assert result["pricing_anchor_cost"] == 10
    assert result["retail_price_min"] == 25
    assert result["retail_price_max"] == 30
    assert result["calculated_sale_price"] == 25


# 7. CATEGORY POLICY APPLICATION

def test_apply_category_policy():
    product = {
        "supplier_id": "supplier001",
        "base_price": 10,
    }

    policies = {
        ("supplier001", "category001"): {
            "pricing_mode": "direct",
            "pricing_value": 25,
            "weight_lb": 2,
            "length_in": 12,
            "width_in": 8,
            "height_in": 4,
        }
    }

    result = apply_category_policy(
        product,
        "category001",
        policies,
    )

    assert result["category_pricing_mode"] == "direct"
    assert result["category_pricing_value"] == 25
    assert result["category_shipping"]["weight_lb"] == 2
    assert result["category_shipping"]["length_in"] == 12

    # Original input must not be mutated.
    assert "category_pricing_mode" not in product
