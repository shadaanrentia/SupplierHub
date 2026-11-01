
"""Validate real Lightspeed variant-update payload construction.

No network, database or production credentials.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    # Empty credentials: never authenticate against Lightspeed.
    ls = LightspeedService()

    family = {
        "id": "family-test",
        "track_inventory": True,
        "products": [
            {"id": "remote-s", "sku": "SKU-S"},
            {"id": "remote-m", "sku": "SKU-M"},
        ],
    }

    monkeypatch.setattr(
        ls,
        "_get_inventory_outlet_id",
        MagicMock(return_value="test-outlet"),
    )

    monkeypatch.setattr(
        ls,
        "_sync_single_variant",
        AsyncMock(return_value={"success": True}),
    )

    return ls, family


@pytest.mark.asyncio
async def test_zero_inventory_reaches_lightspeed_payload(
    service,
):
    ls, family = service

    variants = [
        {
            "variant_sku": "SKU-S",
            "price": 10.0,
            "inventory": 0,
            "retail_price_override": 20.0,
        },
        {
            "variant_sku": "SKU-M",
            "price": 12.0,
            "inventory": 25,
            "retail_price_override": 22.0,
        },
    ]

    await ls._sync_existing_variants(
        product_id="remote-s",
        supplier_variants=variants,
        retail_price=20.0,
        product_name="Cotton Tee",
        supplier_id=None,
        enable_inventory_tracking=False,
        effective_markup_percentage=50,
        remote_snapshot=family,
    )

    assert ls._sync_single_variant.await_count == 2

    captured = {}

    for call in ls._sync_single_variant.await_args_list:
        remote_id, sku, payload = call.args[:3]
        captured[sku] = {
            "remote_id": remote_id,
            "details": payload["details"],
        }

    assert set(captured) == {"SKU-S", "SKU-M"}

    zero_stock = captured["SKU-S"]

    assert zero_stock["remote_id"] == "remote-s"
    assert zero_stock["details"]["inventory"][0][
        "current_amount"
    ] == 0
    assert zero_stock["details"]["inventory"][0][
        "outlet_id"
    ] == "test-outlet"
    assert zero_stock["details"]["price_excluding_tax"] == 20.0

    positive_stock = captured["SKU-M"]

    assert positive_stock["remote_id"] == "remote-m"
    assert positive_stock["details"]["inventory"][0][
        "current_amount"
    ] == 25
    assert positive_stock["details"]["price_excluding_tax"] == 22.0


@pytest.mark.asyncio
async def test_failed_variant_sync_raises_error(service):
    ls, family = service

    ls._sync_single_variant.return_value = {
        "success": False,
        "sku": "SKU-S",
        "error": "Simulated API failure",
    }

    variants = [{
        "variant_sku": "SKU-S",
        "price": 10.0,
        "inventory": 0,
        "retail_price_override": 20.0,
    }]

    with pytest.raises(
        ValueError,
        match="Incomplete variant sync",
    ):
        await ls._sync_existing_variants(
            product_id="remote-s",
            supplier_variants=variants,
            retail_price=20.0,
            product_name="Cotton Tee",
            supplier_id=None,
            enable_inventory_tracking=False,
            effective_markup_percentage=50,
            remote_snapshot=family,
        )
