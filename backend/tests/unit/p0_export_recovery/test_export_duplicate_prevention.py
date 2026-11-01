
"""SupplierHub duplicate-prevention and export recovery tests.

All database and Lightspeed calls are mocked.
No real SQL, HTTP requests, or product creation.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import deps
import export_format
import export_safety
import pricing_rules
from multi_family import export_families


class FakeConnection:
    def __init__(self, groups):
        self.groups = groups
        self.queries = []
        self.lock_held = False

    async def fetchval(self, sql, *args):
        self.queries.append(("fetchval", sql, args))

        if "pg_try_advisory_lock" in sql:
            self.lock_held = True
            return True

        raise AssertionError(f"Unexpected query: {sql}")

    async def fetch(self, sql, *args):
        self.queries.append(("fetch", sql, args))

        if "FROM lightspeed_export_groups" in sql:
            return self.groups

        raise AssertionError(f"Unexpected query: {sql}")

    async def execute(self, sql, *args):
        self.queries.append(("execute", sql, args))

        if "pg_advisory_unlock" in sql:
            self.lock_held = False
            return "SELECT 1"

        if "UPDATE lightspeed_export_groups" in sql:
            return "UPDATE 1"

        raise AssertionError(f"Unexpected write: {sql}")


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def environment(monkeypatch):
    product = {
        "id": "local-product-001",
        "product_name": "Test T-Shirt",
        "supplier_sku": "TEST-001",
        "supplier_name": "Test Supplier",
    }

    variants = [
        {
            "id": "v1",
            "variant_sku": "TEST-001-S",
            "size": "S",
            "color": "Black",
            "price": 10.0,
            "inventory": 5,
        },
        {
            "id": "v2",
            "variant_sku": "TEST-001-M",
            "size": "M",
            "color": "Black",
            "price": 10.0,
            "inventory": 0,
        },
    ]

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/product.jpg",
    }]

    connection = FakeConnection([])

    monkeypatch.setattr(
        deps,
        "pool",
        SimpleNamespace(
            acquire=lambda: FakeAcquire(connection)
        ),
    )

    # Isolate export orchestration from price calculations.
    monkeypatch.setattr(
        export_format,
        "assert_service_compatible",
        lambda service: None,
    )

    monkeypatch.setattr(
        export_safety,
        "validate_prices",
        lambda product, variants: None,
    )

    async def fake_pricing(conn, product, variants, markup):
        return product, variants, markup

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        fake_pricing,
    )

    ls = MagicMock()
    ls.domain_prefix = "unit-test-store"

    ls._get_or_create_supplier.return_value = "supplier-test"
    ls._get_or_create_brand.return_value = "brand-test"

    ls._ensure_variant_attributes.return_value = {
        "Color": "attr-color",
        "Size": "attr-size",
    }

    ls._get_inventory_outlet_id.return_value = "outlet-test"
    ls.lookup_skus.return_value = {}

    # These must never run in rejection scenarios.
    ls._create_product = AsyncMock(
        side_effect=AssertionError(
            "Unexpected Lightspeed product creation"
        )
    )

    ls.family_request.side_effect = AssertionError(
        "Unexpected Lightspeed family API request"
    )

    return SimpleNamespace(
        conn=connection,
        ls=ls,
        product=product,
        variants=variants,
        images=images,
    )


def group(variant_ids, state="planned"):
    return {
        "id": "export-group-001",
        "product_id": "local-product-001",
        "store_domain": "unit-test-store",
        "group_number": 1,
        "export_mode": "size_families",
        "export_sku": "TEST-001-G01",
        "variant_ids": variant_ids,
        "state": state,
        "lightspeed_product_id": None,
    }


async def run_export(env):
    return await export_families(
        env.ls,
        env.product,
        env.variants,
        env.images,
        20.0,
        None,
    )


def assert_no_product_creation(env):
    env.ls._create_product.assert_not_awaited()
    env.ls.family_request.assert_not_called()


def assert_lock_released(env):
    assert env.conn.lock_held is False

    unlock_calls = [
        query
        for query in env.conn.queries
        if "pg_advisory_unlock" in query[1]
    ]

    assert len(unlock_calls) == 1


@pytest.mark.asyncio
async def test_missing_saved_plan_blocks_export(environment):
    env = environment
    env.conn.groups = []

    result = await run_export(env)

    assert result["success"] is False
    assert "Review and save a plan" in result["error"]

    assert_no_product_creation(env)
    assert_lock_released(env)


@pytest.mark.asyncio
async def test_incomplete_plan_blocks_export(environment):
    env = environment

    # v2 is omitted from the saved plan.
    env.conn.groups = [
        group(["v1"])
    ]

    result = await run_export(env)

    assert result["success"] is False
    assert "Review and save a plan" in result["error"]

    assert_no_product_creation(env)
    assert_lock_released(env)


@pytest.mark.asyncio
async def test_running_group_rejects_second_export(environment):
    env = environment

    env.conn.groups = [
        group(["v1", "v2"], state="running")
    ]

    result = await run_export(env)

    assert result["success"] is False
    assert "Another worker is running" in result["error"]

    assert_no_product_creation(env)
    assert_lock_released(env)


@pytest.mark.asyncio
async def test_uncertain_creation_does_not_create_duplicate(
    environment,
):
    env = environment

    env.conn.groups = [
        group(["v1", "v2"], state="uncertain")
    ]

    # Simulate no confirmed Lightspeed SKU match.
    env.ls.lookup_skus.return_value = {}

    result = await run_export(env)

    assert result["success"] is False

    assert (
        "Previous creation outcome cannot be verified"
        in result["error"]
    )

    # No second POST is permitted.
    assert_no_product_creation(env)

    # SupplierHub attempted read-only SKU reconciliation.
    env.ls.lookup_skus.assert_called()

    assert_lock_released(env)
