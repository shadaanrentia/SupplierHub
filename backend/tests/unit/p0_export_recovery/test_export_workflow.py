
"""Export routing and pre-export safety tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import export_safety


def make_variants(count):
    return [
        {
            "id": f"id-{i}",
            "variant_sku": f"SKU-{i}",
            "size": "M",
            "color": f"Color-{i}",
            "price": 10,
            "inventory": 20,
            "is_active": True,
        }
        for i in range(count)
    ]


def make_product():
    return {
        "id": "product-1",
        "supplier_sku": "ATC1000",
        "product_name": "Cotton Tee",
        "base_price": 10,
    }


@pytest.mark.asyncio
async def test_legacy_export_rejects_all_excluded_skus():
    variants = make_variants(1)
    variants[0]["inventory"] = 0

    with pytest.raises(
        ValueError,
        match="All variant SKUs are temporarily excluded",
    ):
        await export_safety._legacy_export_product(
            ls=None,
            product=make_product(),
            variants=variants,
            images=[],
            markup=50,
            category_id="category-1",
        )


@pytest.mark.asyncio
async def test_legacy_export_rejects_duplicate_variants():
    variants = make_variants(2)

    # Different SKUs but identical color/size combinations.
    variants[1]["color"] = variants[0]["color"]

    with pytest.raises(
        ValueError,
        match="colour/size combinations",
    ):
        await export_safety._legacy_export_product(
            ls=None,
            product=make_product(),
            variants=variants,
            images=[],
            markup=50,
            category_id="category-1",
        )


@pytest.mark.asyncio
async def test_201_eligible_variants_use_split_export(
    monkeypatch,
):
    import pricing_rules
    import export_format
    import multi_family
    from routes import media

    ensure_schema = AsyncMock()
    verify_service = MagicMock()
    load_images = AsyncMock(return_value=[])

    split_result = {
        "success": True,
        "destination_ids": ["TEST-1", "TEST-2"],
    }
    split_export = AsyncMock(return_value=split_result)

    monkeypatch.setattr(
        pricing_rules,
        "ensure_pricing_schema",
        ensure_schema,
    )
    monkeypatch.setattr(
        export_format,
        "assert_service_compatible",
        verify_service,
    )
    monkeypatch.setattr(
        media,
        "stored_export_images",
        load_images,
    )
    monkeypatch.setattr(
        multi_family,
        "export_families",
        split_export,
    )

    # Mock the database connection pool.
    conn = AsyncMock()
    conn.fetch.return_value = []

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn

    monkeypatch.setattr(
        export_safety.deps,
        "pool",
        pool,
    )

    variants = make_variants(201)
    ls = SimpleNamespace(domain_prefix="test-store")

    result = await export_safety.export_product(
        ls=ls,
        product=make_product(),
        variants=variants,
        images=[],
        markup=50,
        category_id="category-1",
    )

    assert result == split_result

    split_export.assert_awaited_once()

    args = split_export.await_args.args
    forwarded_variants = args[2]

    assert len(forwarded_variants) == 201
    assert {
        v["variant_sku"] for v in forwarded_variants
    } == {
        v["variant_sku"] for v in variants
    }

    verify_service.assert_called_once_with(ls)
    ensure_schema.assert_awaited_once()
    load_images.assert_awaited_once()

@pytest.mark.asyncio
async def test_existing_split_keeps_zero_stock_variant_for_reconciliation(
    monkeypatch,
):
    """
    Regression requirement:
    An existing split-family product must still send its
    zero-stock variants through inventory reconciliation.

    This test is expected to fail against the current
    eligibility filtering implementation.
    """
    import pricing_rules
    import export_format
    import multi_family
    from routes import media

    monkeypatch.setattr(
        pricing_rules,
        "ensure_pricing_schema",
        AsyncMock(),
    )
    monkeypatch.setattr(
        export_format,
        "assert_service_compatible",
        MagicMock(),
    )
    monkeypatch.setattr(
        media,
        "stored_export_images",
        AsyncMock(return_value=[]),
    )

    split_export = AsyncMock(return_value={
        "success": True,
        "destination_ids": ["EXISTING-LS-1"],
    })

    monkeypatch.setattr(
        multi_family,
        "export_families",
        split_export,
    )

    conn = AsyncMock()
    conn.fetch.return_value = [{
    "id": "existing-group-1",
    "variant_ids": ["id-0", "id-1"],
    "lightspeed_product_id": "EXISTING-LS-1",
}]

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn

    monkeypatch.setattr(
        export_safety.deps,
        "pool",
        pool,
    )

    variants = make_variants(2)

    # SKU-0 already exists remotely, but is now out of stock.
    variants[0]["inventory"] = 0

    ls = SimpleNamespace(
        domain_prefix="isolated-test-store"
    )

    await export_safety.export_product(
        ls=ls,
        product=make_product(),
        variants=variants,
        images=[],
        markup=50,
        category_id="category-1",
    )

    split_export.assert_awaited_once()

    forwarded = split_export.await_args.args[2]

    forwarded_by_sku = {
        row["variant_sku"]: row
        for row in forwarded
    }

    # Both existing variants must be reconciled.
    assert set(forwarded_by_sku) == {
        "SKU-0",
        "SKU-1",
    }

    # The out-of-stock variant must retain its zero quantity.
    assert forwarded_by_sku["SKU-0"]["inventory"] == 0
