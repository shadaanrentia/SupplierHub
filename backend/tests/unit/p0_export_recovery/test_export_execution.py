
"""Test export execution without PostgreSQL or Lightspeed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import export_safety


@pytest.fixture
def export_environment(monkeypatch):
    import pricing_rules
    import export_format
    import single_family

    conn = AsyncMock()
    conn.fetch.return_value = []

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    monkeypatch.setattr(export_safety.deps, "pool", pool)

    async def fake_pricing(conn, product, variants, markup):
        priced = [
            dict(v, retail_price_override=float(v["price"]) + 10)
            for v in variants
        ]
        updated = dict(product, calculated_sale_price=20.0)
        return updated, priced, markup

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        fake_pricing,
    )

    monkeypatch.setattr(
        export_format,
        "inventory_quantity",
        lambda variant: int(variant["inventory"]),
    )

    repair = AsyncMock(return_value={
        "uncertain": False,
        "failed": False,
        "messages": [],
    })
    monkeypatch.setattr(single_family, "repair_assets", repair)

    ls = SimpleNamespace(
        domain_prefix="isolated-test-store",
        create_or_update_product=AsyncMock(
            return_value={
                "success": True,
                "lightspeed_id": "FAKE-LS-001",
            }
        ),
    )

    product = {
        "id": "product-001",
        "supplier_sku": "ATC1000",
        "product_name": "Cotton Tee",
        "base_price": 10.0,
        "brand": "ATC",
        "supplier_name": "SanMar",
        "description": "Cotton T-shirt",
    }

    variants = [
        {
            "id": "v1",
            "variant_sku": "ATC1000-BLK-S",
            "color": "Black",
            "size": "S",
            "price": 10.0,
            "inventory": 25,
            "is_active": True,
        },
        {
            "id": "v2",
            "variant_sku": "ATC1000-BLK-M",
            "color": "Black",
            "size": "M",
            "price": 12.0,
            "inventory": 30,
            "is_active": True,
        },
    ]

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/test.jpg",
        "source_part_ids": ["ATC1000-BLK-S","ATC1000-BLK-M"],
    }]

    return ls, conn, repair, product, variants, images


@pytest.mark.asyncio
async def test_export_preserves_variant_prices_and_details(
    export_environment,
):
    ls, conn, repair, product, variants, images = (
        export_environment
    )

    result = await export_safety._legacy_export_product(
        ls, product, variants, images, 50, "category-001"
    )

    assert result["success"] is True
    assert result["lightspeed_id"] == "FAKE-LS-001"

    ls.create_or_update_product.assert_awaited_once()

    payload = ls.create_or_update_product.await_args.args[0]

    assert payload["product_id"] == "product-001"
    assert payload["brand_name"] == "ATC"
    assert payload["supplier_name"] == "SanMar"
    assert payload["category_id"] == "category-001"
    assert payload["cost_price"] == 10.0
    assert payload["retail_price"] == 20.0

    assert len(payload["variants"]) == 2
    assert {
        v["variant_sku"] for v in payload["variants"]
    } == {
        "ATC1000-BLK-S",
        "ATC1000-BLK-M",
    }

    prices = {
        v["variant_sku"]: v["retail_price_override"]
        for v in payload["variants"]
    }
    assert prices["ATC1000-BLK-S"] == 20.0
    assert prices["ATC1000-BLK-M"] == 22.0

    inventories = {
        v["variant_sku"]: v["inventory"]
        for v in payload["variants"]
    }
    assert inventories["ATC1000-BLK-S"] == 25
    assert inventories["ATC1000-BLK-M"] == 30

    repair.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_handles_lightspeed_failure(
    export_environment,
):
    ls, conn, repair, product, variants, images = (
        export_environment
    )

    ls.create_or_update_product.return_value = {
        "success": False,
        "error": "Simulated Lightspeed failure",
    }

    result = await export_safety._legacy_export_product(
        ls, product, variants, images, 50, "category-001"
    )

    assert result["success"] is False
    assert result["error"] == "Simulated Lightspeed failure"
    assert result["completed_groups"] == []

    repair.assert_not_awaited()
