
"""Test recovery when Lightspeed creation succeeds but DB persistence fails.

All external systems are simulated. No real PostgreSQL or HTTP calls.
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
    def __init__(self):
        self.groups = []
        self.queries = []
        self.locked = False
        self.fail_destination_save = True

    async def fetchval(self, sql, *args):
        self.queries.append(("fetchval", sql, args))

        if "pg_try_advisory_lock" in sql:
            self.locked = True
            return True

        raise AssertionError(f"Unexpected fetchval: {sql}")

    async def fetch(self, sql, *args):
        self.queries.append(("fetch", sql, args))

        if "FROM lightspeed_export_groups" in sql:
            return [dict(group) for group in self.groups]

        raise AssertionError(f"Unexpected fetch: {sql}")

    async def execute(self, sql, *args):
        self.queries.append(("execute", sql, args))

        if "pg_advisory_unlock" in sql:
            self.locked = False
            return "SELECT 1"

        if "SET lightspeed_product_id=$2" in sql:
            if self.fail_destination_save:
                raise RuntimeError(
                    "Simulated destination ID persistence failure"
                )
            self.groups[0]["lightspeed_product_id"] = args[1]
            return "UPDATE 1"

        if "SET state='running'" in sql:
            self.groups[0]["state"] = "running"
            return "UPDATE 1"

        if "SET state='uncertain'" in sql:
            self.groups[0]["state"] = "uncertain"
            return "UPDATE 1"

        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def environment(monkeypatch):
    conn = FakeConnection()

    monkeypatch.setattr(
        deps,
        "pool",
        SimpleNamespace(
            acquire=lambda: FakeAcquire(conn)
        ),
    )

    monkeypatch.setattr(
        export_format,
        "assert_service_compatible",
        lambda ls: None,
    )

    monkeypatch.setattr(
        export_safety,
        "validate_prices",
        lambda product, variants: None,
    )

    async def fake_prepare(conn, product, variants, markup):
        return product, variants, markup

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        fake_prepare,
    )

    monkeypatch.setattr(
        pricing_rules,
        "variant_retail",
        lambda variant, markup: 20.0,
    )

    product = {
        "id": "product-001",
        "product_name": "Test Shirt",
        "supplier_sku": "TEST-001",
        "base_price": 10.0,
    }

    variants = [
        {
            "id": "v1",
            "variant_sku": "TEST-S",
            "size": "S",
            "color": "Black",
            "price": 10.0,
            "inventory": 5,
        },
        {
            "id": "v2",
            "variant_sku": "TEST-M",
            "size": "M",
            "color": "Black",
            "price": 10.0,
            "inventory": 0,
        },
    ]

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/image.jpg",
    }]

    conn.groups = [{
        "id": "group-001",
        "product_id": "product-001",
        "store_domain": "test-store",
        "group_number": 1,
        "export_mode": "size_families",
        "export_sku": "TEST-001-G01",
        "variant_ids": ["v1", "v2"],
        "state": "planned",
        "lightspeed_product_id": None,
    }]

    ls = MagicMock()
    ls.domain_prefix = "test-store"

    ls._ensure_variant_attributes.return_value = {
        "Color": "color-id",
        "Size": "size-id",
    }
    ls._get_inventory_outlet_id.return_value = "outlet-001"
    ls.lookup_skus.return_value = {}

    # This mock simulates a successful remote creation.
    ls._create_product = AsyncMock(
        return_value={"id": "remote-created-001"}
    )

    # Later export stages must never execute in this test.
    ls._sync_existing_variants = AsyncMock(
        side_effect=AssertionError(
            "Unexpected variant synchronization"
        )
    )

    return SimpleNamespace(
        conn=conn,
        ls=ls,
        product=product,
        variants=variants,
        images=images,
    )


async def run_export(env):
    return await export_families(
        env.ls,
        env.product,
        env.variants,
        env.images,
        20.0,
        None,
    )


@pytest.mark.asyncio
async def test_created_product_but_db_save_fails(environment):
    env = environment

    result = await run_export(env)

    assert result["success"] is False
    assert "destination ID persistence failure" in result["error"]

    # Remote creation was attempted exactly once.
    env.ls._create_product.assert_awaited_once()

    # The export must not proceed to variant synchronization.
    env.ls._sync_existing_variants.assert_not_awaited()

    # Failure is recorded for reconciliation.
    assert env.conn.groups[0]["state"] == "uncertain"

    # No ID was durably saved in our simulated database.
    assert env.conn.groups[0]["lightspeed_product_id"] is None

    # Always release the advisory lock.
    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_retry_never_blindly_creates_duplicate(environment):
    env = environment

    first = await run_export(env)
    assert first["success"] is False

    env.ls._create_product.assert_awaited_once()

    # Simulate a retry with no confirmed remote SKU match.
    env.ls.lookup_skus.return_value = {}

    retry = await run_export(env)

    assert retry["success"] is False
    assert (
        "Previous creation outcome cannot be verified"
        in retry["error"]
    )

    # Even after retry, creation still happened only once.
    env.ls._create_product.assert_awaited_once()
    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_uncertain_state_does_not_sync_variants(environment):
    env = environment
    env.conn.groups[0]["state"] = "uncertain"

    result = await run_export(env)

    assert result["success"] is False

    env.ls._create_product.assert_not_awaited()
    env.ls._sync_existing_variants.assert_not_awaited()

    assert env.conn.locked is False
