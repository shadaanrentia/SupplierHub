
"""
SupplierHub 2.0 - Export Validation Tests

Checks:
- Supplier prices
- Variant costs
- Duplicate SKUs
- Duplicate color/size combinations
- Missing variant information
- Price review flags
- Basic export helpers
"""

import pytest

from export_safety import (
    positive,
    validate_prices,
    decode,
    image_key,
)


def product():
    return {
        "base_price": 10.00,
        "price_needs_review": False,
    }


def variants():
    return [
        {
            "variant_sku": "SKU-BLK-S",
            "color": "Black",
            "size": "S",
            "price": 10.00,
        },
        {
            "variant_sku": "SKU-BLK-M",
            "color": "Black",
            "size": "M",
            "price": 12.00,
        },
    ]


@pytest.mark.parametrize(
    "value,expected",
    [
        (10, True),
        ("2.49", True),
        (0, False),
        (-5, False),
        (None, False),
        ("invalid", False),
        (float("nan"), False),
        (float("inf"), False),
    ],
)
def test_positive_price_validation(value, expected):
    assert positive(value) is expected


def test_valid_product_and_variants():
    validate_prices(product(), variants())


def test_invalid_base_price():
    item = product()
    item["base_price"] = 0

    with pytest.raises(ValueError, match="Supplier cost"):
        validate_prices(item, variants())


def test_product_price_needs_review():
    item = product()
    item["price_needs_review"] = True

    with pytest.raises(ValueError, match="Supplier cost"):
        validate_prices(item, variants())


def test_invalid_variant_cost():
    rows = variants()
    rows[0]["price"] = 0

    with pytest.raises(ValueError, match="Variant prices"):
        validate_prices(product(), rows)


def test_variant_price_needs_review():
    rows = variants()
    rows[0]["price_needs_review"] = True

    with pytest.raises(ValueError, match="Variant prices"):
        validate_prices(product(), rows)


def test_duplicate_variant_sku():
    rows = variants()
    rows[1]["variant_sku"] = "SKU-BLK-S"

    with pytest.raises(ValueError, match="Variant SKUs"):
        validate_prices(product(), rows)


def test_duplicate_sku_case_insensitive():
    rows = variants()
    rows[1]["variant_sku"] = "sku-blk-s"

    with pytest.raises(ValueError, match="Variant SKUs"):
        validate_prices(product(), rows)


def test_duplicate_color_size_combination():
    rows = variants()
    rows[1]["size"] = "S"

    with pytest.raises(ValueError, match="colour/size"):
        validate_prices(product(), rows)


def test_missing_size():
    rows = variants()
    rows[0]["size"] = ""

    with pytest.raises(ValueError, match="colour/size"):
        validate_prices(product(), rows)


def test_missing_color():
    rows = variants()
    rows[0]["color"] = None

    with pytest.raises(ValueError, match="colour/size"):
        validate_prices(product(), rows)


def test_missing_variant_sku():
    rows = variants()
    rows[0]["variant_sku"] = ""

    with pytest.raises(ValueError, match="Variant SKUs"):
        validate_prices(product(), rows)


def test_json_decode():
    assert decode('["A", "B"]') == ["A", "B"]


def test_decode_existing_list():
    original = ["A", "B"]
    assert decode(original) is original


def test_image_key_is_deterministic():
    image = {"url": "https://example.com/image.jpg"}

    assert image_key(image) == image_key(dict(image))


def test_image_key_changes_with_content():
    first = {"image_base64": "AAA"}
    second = {"image_base64": "BBB"}

    assert image_key(first) != image_key(second)
