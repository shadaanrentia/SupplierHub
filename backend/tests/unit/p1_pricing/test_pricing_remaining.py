
"""Remaining pricing unit coverage using mocked dependencies."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import pricing_rules
import taxonomy_resolution


def test_variant_retail_without_override(monkeypatch):
    calls = []

    def fake_calculate_sale_price(cost, markup):
        calls.append((cost, markup))
        return 18.50

    monkeypatch.setattr(
        pricing_rules.deps,
        "calculate_sale_price",
        fake_calculate_sale_price,
    )

    result = pricing_rules.variant_retail(
        {"price": 10, "retail_price_override": None},
        50,
    )

    assert result == 18.50
    assert calls == [(10.0, 50)]


@pytest.mark.asyncio
async def test_pricing_schema_initializes_and_caches(monkeypatch):
    connection = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = connection

    monkeypatch.setattr(pricing_rules.deps, "pool", pool)
    monkeypatch.setattr(pricing_rules, "_schema_pool", None)

    await pricing_rules.ensure_pricing_schema()

    connection.execute.assert_awaited_once()
    assert "supplier_category_policies" in (
        connection.execute.await_args.args[0]
    )

    # Second call should reuse the initialized schema.
    await pricing_rules.ensure_pricing_schema()

    assert connection.execute.await_count == 1


@pytest.mark.asyncio
async def test_legacy_category_mapping_success(monkeypatch):
    async def fake_resolve_category(*args):
        return False, None, None

    async def fake_category_policies(conn):
        return {}

    monkeypatch.setattr(
        taxonomy_resolution,
        "resolve_category",
        fake_resolve_category,
    )
    monkeypatch.setattr(
        pricing_rules,
        "category_policies",
        fake_category_policies,
    )

    conn = AsyncMock()
    conn.fetch.return_value = [
        {"lightspeed_category_id": "lightspeed-cat-1"}
    ]
    conn.fetchrow.return_value = None

    product, variants, markup = (
        await pricing_rules.prepare_export_pricing(
            conn,
            {
                "supplier_id": "supplier1",
                "supplier_sku": "ATC1000",
                "category": "Apparel",
                "base_price": 10,
            },
            [{"variant_sku": "SKU001", "price": 10}],
            25,
        )
    )

    assert product["category_policy_id"] == "lightspeed-cat-1"
    assert product["pricing_mode"] == "global"
    assert variants[0]["retail_price_override"] == (
        pricing_rules.price_for(
            10,
            {"mode": "global", "value": 25, "anchor_cost": 10},
        )
    )
    assert markup == 25


@pytest.mark.asyncio
async def test_database_markup_overrides_supplied_markup(
    monkeypatch,
):
    async def fake_resolve_category(*args):
        return True, "category1", None

    async def fake_category_policies(conn):
        return {}

    monkeypatch.setattr(
        taxonomy_resolution,
        "resolve_category",
        fake_resolve_category,
    )
    monkeypatch.setattr(
        pricing_rules,
        "category_policies",
        fake_category_policies,
    )

    conn = AsyncMock()
    conn.fetchrow.return_value = {"markup_percentage": 40}

    product, variants, markup = (
        await pricing_rules.prepare_export_pricing(
            conn,
            {
                "supplier_id": "supplier1",
                "supplier_sku": "ATC1000",
                "base_price": 10,
            },
            [{"variant_sku": "SKU001", "price": 10}],
            20,
        )
    )

    assert markup == 40
    assert product["effective_markup_percentage"] == 40
    assert variants[0]["retail_price_override"] == (
        pricing_rules.price_for(
            10,
            {"mode": "global", "value": 40, "anchor_cost": 10},
        )
    )

@pytest.mark.asyncio
async def test_schema_initialized_by_another_task(monkeypatch):
    """
    If another task initializes the schema while this task
    waits for the lock, do not initialize it again.
    """

    pool = object()

    class SimulatedLock:
        async def __aenter__(self):
            # Simulate another task completing initialization.
            monkeypatch.setattr(
                pricing_rules,
                "_schema_pool",
                pool,
            )

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pricing_rules.deps, "pool", pool)
    monkeypatch.setattr(pricing_rules, "_schema_pool", None)
    monkeypatch.setattr(
        pricing_rules,
        "_schema_lock",
        SimulatedLock(),
    )

    await pricing_rules.ensure_pricing_schema()

    assert pricing_rules._schema_pool is pool
