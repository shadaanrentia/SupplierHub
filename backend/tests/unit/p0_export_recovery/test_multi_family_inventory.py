
"""Existing split-family inventory reconciliation tests.

Uses fake database and Lightspeed objects only.
No real API calls or persistent database writes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import multi_family


@pytest.fixture
def existing_family_environment(monkeypatch):
    import export_format
    import pricing_rules

    monkeypatch.setattr(
        export_format,
        "assert_service_compatible",
        lambda ls: None,
    )

    product = {
        "id": "product-1",
        "supplier_id": "supplier-1",
        "supplier_sku": "ATC1000",
        "product_name": "Cotton Tee",
        "base_price": 10.0,
    }

    variants = [
        {
            "id": "variant-s",
            "variant_sku": "SKU-S",
            "size": "S",
            "color": "Black",
            "price": 10.0,
            "inventory": 0,
            "is_active": True,
        },
        {
            "id": "variant-m",
            "variant_sku": "SKU-M",
            "size": "M",
            "color": "Black",
            "price": 12.0,
            "inventory": 20,
            "is_active": True,
        },
    ]

    group = {
        "id": "group-1",
        "group_number": 1,
        "export_sku": "ATC1000-G01",
        "variant_ids": ["variant-s", "variant-m"],
        "lightspeed_product_id": "remote-s",
        "export_mode": "size_families",
        "state": "done",
    }

    conn = AsyncMock()
    conn.fetchval.return_value = True
    conn.fetch.return_value = [group]

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    monkeypatch.setattr(multi_family.deps, "pool", pool)

    async def fake_prepare(conn, product, variants, markup):
        return (
            dict(product),
            [
                dict(v, retail_price_override=float(v["price"]) + 10)
                for v in variants
            ],
            markup,
        )

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        fake_prepare,
    )

    family = {
        "id": "family-1",
        "name": "Cotton Tee",
        "products": [
            {
                "id": "remote-s",
                "sku": "SKU-S",
                "active": {"in_store": True, "ecwid": True},
            },
            {
                "id": "remote-m",
                "sku": "SKU-M",
                "active": {"in_store": True, "ecwid": True},
            },
        ],
    }

    # Fake remote calls are deliberately synchronous where
    # production uses asyncio.to_thread().
    ls = SimpleNamespace(
        domain_prefix="test-store",
        remote_product_deleted=MagicMock(return_value=False),
        remote_family=MagicMock(return_value=family),
        lookup_skus=MagicMock(return_value={}),
        _ensure_variant_attributes=MagicMock(
            return_value={"Color": "attr-color", "Size": "attr-size"}
        ),
        _get_inventory_outlet_id=MagicMock(
            return_value="test-outlet"
        ),
        update_family_metadata=MagicMock(return_value=family),
        _sync_existing_variants=AsyncMock(),
    )

    repair = AsyncMock(return_value={
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "uncertain": 0,
        "messages": [],
    })

    monkeypatch.setattr(multi_family, "repair_assets", repair)

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/test.jpg",
        "source_part_ids": ["SKU-S","SKU-M"],
    }]

    return ls, conn, product, variants, images, repair


@pytest.mark.asyncio
async def test_existing_family_forwards_zero_inventory(
    existing_family_environment,
):
    ls, conn, product, variants, images, repair = (
        existing_family_environment
    )

    result = await multi_family.export_families(
        ls, product, variants, images, 50, "category-1"
    )

    assert result["success"] is True, result

    ls._sync_existing_variants.assert_awaited_once()

    args = ls._sync_existing_variants.await_args.args
    forwarded = args[1]

    by_sku = {
        v["variant_sku"]: v
        for v in forwarded
    }

    assert set(by_sku) == {"SKU-S", "SKU-M"}
    assert by_sku["SKU-S"]["inventory"] == 0
    assert by_sku["SKU-M"]["inventory"] == 20

    # An existing family must not create a second product.
    assert ls.lookup_skus.call_count == 0
    repair.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_family_does_not_recreate_product(
    existing_family_environment,
):
    ls, conn, product, variants, images, repair = (
        existing_family_environment
    )

    result = await multi_family.export_families(
        ls, product, variants, images, 50, "category-1"
    )

    assert result["success"] is True, result

    # Existing verified destinations should be updated in place.
    assert ls.remote_family.call_count >= 1
    ls._sync_existing_variants.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_inventory_blocks_export(
    existing_family_environment,
):
    ls, conn, product, variants, images, repair = (
        existing_family_environment
    )

    variants[0]["inventory"] = "invalid"

    with pytest.raises(
        ValueError,
        match="Missing or invalid variant inventory",
    ):
        await multi_family.export_families(
            ls, product, variants, images, 50, "category-1"
        )

    ls._sync_existing_variants.assert_not_awaited()
