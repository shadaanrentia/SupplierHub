
from product_readiness import evaluate


def make_product(**overrides):
    product = {
        "id": "PRODUCT-1",
        "product_name": "Test Product",
        "supplier_sku": "TEST100",
        "base_price": 10.0,
        "price_needs_review": False,
    }
    product.update(overrides)
    return product


def make_variant(variant_id, sku, inventory, **overrides):
    variant = {
        "id": variant_id,
        "variant_sku": sku,
        "price": 10.0,
        "inventory": inventory,
        "is_active": True,
        "color": "Black",
        "size": variant_id,
        "price_needs_review": False,
    }
    variant.update(overrides)
    return variant


def make_group(variant_ids, destination=None, state="planned"):
    return {
        "variant_ids": variant_ids,
        "lightspeed_product_id": destination,
        "state": state,
        "export_mode": "size_families",
    }


def evaluate_product(product, variants, groups=None):
    return evaluate(
        product=product,
        variants=variants,
        images=[
            {
                "media_type": "image",
                "url": "https://example.invalid/test.jpg",
            }
        ],
        groups=groups or [],
        category_id="CATEGORY-1",
    )


def test_new_product_excludes_zero_inventory():
    product = make_product()
    variants = [
        make_variant("V1", "SKU-1", 10),
        make_variant("V2", "SKU-2", 0),
    ]

    result = evaluate_product(product, variants)

    assert result["is_valid"] is True
    assert result["variants_count"] == 1
    assert result["skipped_variants_count"] == 1
    assert [v["variant_sku"] for v in result["variants"]] == ["SKU-1"]


def test_new_product_with_only_zero_inventory_is_excluded():
    product = make_product()
    variants = [
        make_variant("V1", "SKU-1", 0),
    ]

    result = evaluate_product(product, variants)

    assert result["is_valid"] is False
    assert result["excluded_from_queue"] is True
    assert result["variants_count"] == 0
    assert any(
        "All variant SKUs are temporarily excluded" in error
        for error in result["validation_errors"]
    )


def test_existing_single_product_retains_zero_inventory():
    product = make_product(
        lightspeed_product_id="LS-PRODUCT-1",
    )
    variants = [
        make_variant("V1", "SKU-1", 0),
        make_variant("V2", "SKU-2", 10),
    ]

    result = evaluate_product(product, variants)

    assert result["is_valid"] is True
    assert result["variants_count"] == 2
    assert result["skipped_variants_count"] == 0
    assert {v["variant_sku"] for v in result["variants"]} == {
        "SKU-1",
        "SKU-2",
    }


def test_existing_split_group_retains_zero_inventory():
    product = make_product()
    variants = [
        make_variant("V1", "SKU-1", 0),
        make_variant("V2", "SKU-2", 10),
    ]
    groups = [
        make_group(
            ["V1", "V2"],
            destination="LS-GROUP-1",
            state="done",
        )
    ]

    result = evaluate_product(product, variants, groups)

    assert result["is_valid"] is True
    assert result["variants_count"] == 2
    assert result["plan_ready"] is True


def test_uncreated_split_group_excludes_zero_inventory():
    product = make_product()
    variants = [
        make_variant("V1", "SKU-1", 0),
        make_variant("V2", "SKU-2", 10),
    ]
    groups = [
        make_group(
            ["V1", "V2"],
            destination=None,
            state="planned",
        )
    ]

    result = evaluate_product(product, variants, groups)

    assert result["is_valid"] is False
    assert any(
        "Uncreated export group contains ineligible SKU SKU-1"
        in error
        for error in result["validation_errors"]
    )


def test_mixed_existing_and_uncreated_groups_use_separate_rules():
    product = make_product()
    variants = [
        make_variant("V1", "SKU-1", 0),
        make_variant("V2", "SKU-2", 10),
    ]
    groups = [
        make_group(
            ["V1"],
            destination="LS-GROUP-1",
            state="done",
        ),
        make_group(
            ["V2"],
            destination=None,
            state="planned",
        ),
    ]

    result = evaluate_product(product, variants, groups)

    assert result["is_valid"] is True
    assert result["variants_count"] == 2
    assert result["plan_ready"] is True
