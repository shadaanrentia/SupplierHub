
"""
Advanced pricing tests for SupplierHub 2.0.

All database operations are mocked.
No production data or external API calls.
"""

from unittest.mock import AsyncMock

import pytest

import pricing_rules


@pytest.mark.parametrize(
    "cost,markup",
    [
        (10, 0),
        (10, 10),
        (10, 50),
        (2.49, 100),
    ],
)
def test_global_price_uses_sale_price_calculator(
    monkeypatch, cost, markup
):
    calls = []

    def fake_calculate_sale_price(value, percentage):
        calls.append((value, percentage))
        return 19.99

    monkeypatch.setattr(
        pricing_rules.deps,
        "calculate_sale_price",
        fake_calculate_sale_price,
    )

    policy = {
        "mode": "global",
        "value": markup,
        "anchor_cost": cost,
    }

    result = pricing_rules.price_for(cost, policy)

    assert result == 19.99
    assert calls == [(float(cost), markup)]


def test_empty_variants_use_product_base_price():
    product = {"base_price": 10}

    result = pricing_rules.pricing_policy(
        product, [], 25
    )

    assert result["anchor_cost"] == 10
    assert result["mode"] == "global"


def test_missing_category_rule_falls_back_to_global():
    product = {
        "supplier_id": "supplier1",
        "base_price": 10,
    }

    result = pricing_rules.apply_category_policy(
        product, "category1", {}
    )

    assert result["category_pricing_mode"] == "global"
    assert result["category_pricing_value"] is None


@pytest.mark.asyncio
async def test_category_policies_load_from_database():
    conn = AsyncMock()

    conn.fetchrow.return_value = {
        "lightspeed_store_id": "test-store"
    }

    conn.fetch.return_value = [
        {
            "supplier_id": "supplier1",
            "category_id": "category1",
            "pricing_mode": "percentage",
            "pricing_value": 20,
        }
    ]

    result = await pricing_rules.category_policies(conn)

    assert result[
        ("supplier1", "category1")
    ]["pricing_value"] == 20

    assert conn.fetch.await_count == 1


@pytest.mark.asyncio
async def test_category_policies_without_settings():
    conn = AsyncMock()

    conn.fetchrow.return_value = None
    conn.fetch.return_value = []

    result = await pricing_rules.category_policies(conn)

    assert result == {}

    query, store_domain = conn.fetch.await_args.args
    assert store_domain == ""


@pytest.mark.asyncio
async def test_export_pricing_with_category_rule(monkeypatch):
    conn = AsyncMock()

    # Simulated category resolution.
    async def fake_resolve_category(
        connection, supplier_id, supplier_sku
    ):
        return True, "category1", None

    import taxonomy_resolution

    monkeypatch.setattr(
        taxonomy_resolution,
        "resolve_category",
        fake_resolve_category,
    )

    async def fake_category_policies(connection):
        return {
            ("supplier1", "category1"): {
                "pricing_mode": "direct",
                "pricing_value": 25,
            }
        }

    monkeypatch.setattr(
        pricing_rules,
        "category_policies",
        fake_category_policies,
    )

    conn.fetchrow.return_value = {
        "markup_percentage": 50
    }

    product = {
        "supplier_id": "supplier1",
        "supplier_sku": "ATC1000",
        "base_price": 10,
    }

    variants = [
        {"variant_sku": "SKU-S", "price": 10},
        {"variant_sku": "SKU-XL", "price": 12},
    ]

    result_product, result_variants, markup = (
        await pricing_rules.prepare_export_pricing(
            conn, product, variants, 50
        )
    )

    assert result_product["calculated_sale_price"] == 25
    assert result_product["retail_price_max"] == 27
    assert result_variants[0]["retail_price_override"] == 25
    assert result_variants[1]["retail_price_override"] == 27
    assert markup == 0.0


@pytest.mark.asyncio
async def test_export_rejects_category_resolution_error(
    monkeypatch,
):
    import taxonomy_resolution

    async def fake_resolve_category(*args):
        return True, None, "Category mapping conflict"

    monkeypatch.setattr(
        taxonomy_resolution,
        "resolve_category",
        fake_resolve_category,
    )

    conn = AsyncMock()

    with pytest.raises(
        ValueError, match="Category mapping conflict"
    ):
        await pricing_rules.prepare_export_pricing(
            conn,
            {"supplier_id": "supplier1", "supplier_sku": "ABC"},
            [{"price": 10}],
            50,
        )


@pytest.mark.asyncio
async def test_export_rejects_missing_legacy_category(
    monkeypatch,
):
    import taxonomy_resolution

    async def fake_resolve_category(*args):
        return False, None, None

    monkeypatch.setattr(
        taxonomy_resolution,
        "resolve_category",
        fake_resolve_category,
    )

    conn = AsyncMock()
    conn.fetch.return_value = []

    with pytest.raises(
        ValueError,
        match="Choose one published category",
    ):
        await pricing_rules.prepare_export_pricing(
            conn,
            {
                "supplier_id": "supplier1",
                "supplier_sku": "ABC",
                "category": "Apparel",
            },
            [{"price": 10}],
            50,
        )
