
"""Database-lock safety tests for SupplierHub split-family exports.

All database and Lightspeed dependencies are mocked.
No SQL is executed against a real database.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import deps
import export_format
import export_safety
import pricing_rules
from multi_family import export_families


class FakeConnection:
    def __init__(self, lock_granted=True):
        self.lock_granted = lock_granted
        self.executed = []

    async def fetchval(self, query, *args):
        self.executed.append(("fetchval", query, args))

        if "pg_try_advisory_lock" in query:
            return self.lock_granted

        raise AssertionError(f"Unexpected fetchval: {query}")

    async def fetch(self, query, *args):
        self.executed.append(("fetch", query, args))
        raise RuntimeError("Simulated database read failure")

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))

        if "pg_advisory_unlock" in query:
            return "SELECT 1"

        raise AssertionError(f"Unexpected SQL write: {query}")


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def setup_export(monkeypatch):
    connection = FakeConnection()

    fake_pool = SimpleNamespace(
        acquire=lambda: FakeAcquire(connection)
    )

    monkeypatch.setattr(deps, "pool", fake_pool)

    # We are testing locking and cleanup, not price calculations.
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

    product = {
        "id": "local-product-1",
        "product_name": "Test Shirt",
        "supplier_sku": "TEST-001",
    }

    variants = [{
        "id": "variant-1",
        "variant_sku": "TEST-001-S",
        "inventory": 5,
        "price": 10.0,
        "size": "S",
    }]

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/test-image.jpg",
    }]

    ls = MagicMock()
    ls.domain_prefix = "isolated-test-store"

    return connection, ls, product, variants, images


def export_args(data):
    conn, ls, product, variants, images = data
    return (ls, product, variants, images, 20.0, None)


def calls_containing(connection, text):
    return [
        item
        for item in connection.executed
        if text in item[1]
    ]


@pytest.mark.asyncio
async def test_second_worker_cannot_export_same_product(
    setup_export,
):
    connection = setup_export[0]
    connection.lock_granted = False

    with pytest.raises(
        ValueError,
        match="already exporting",
    ):
        await export_families(*export_args(setup_export))

    assert len(
        calls_containing(connection, "pg_try_advisory_lock")
    ) == 1

    # A worker that never acquired a lock must not release it.
    assert not calls_containing(
        connection, "pg_advisory_unlock"
    )

    # No export database updates should be attempted.
    assert not calls_containing(connection, "UPDATE")


@pytest.mark.asyncio
async def test_database_read_failure_releases_lock(
    setup_export, monkeypatch
):
    connection = setup_export[0]

    async def fake_pricing(conn, product, variants, markup):
        return product, variants, markup

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        fake_pricing,
    )

    result = await export_families(
        *export_args(setup_export)
    )

    assert result["success"] is False
    assert "Simulated database read failure" in result["error"]

    assert len(
        calls_containing(connection, "pg_advisory_unlock")
    ) == 1


@pytest.mark.asyncio
async def test_pricing_failure_releases_lock(
    setup_export, monkeypatch
):
    connection = setup_export[0]

    async def failing_pricing(conn, product, variants, markup):
        raise ValueError("Simulated pricing failure")

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        failing_pricing,
    )

    result = await export_families(
        *export_args(setup_export)
    )

    assert result["success"] is False
    assert "Simulated pricing failure" in result["error"]

    assert len(
        calls_containing(connection, "pg_advisory_unlock")
    ) == 1

    assert not calls_containing(connection, "UPDATE")


@pytest.mark.asyncio
async def test_cancellation_still_releases_lock(
    setup_export, monkeypatch
):
    connection = setup_export[0]

    async def cancelled_pricing(conn, product, variants, markup):
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        cancelled_pricing,
    )

    with pytest.raises(asyncio.CancelledError):
        await export_families(
            *export_args(setup_export)
        )

    assert len(
        calls_containing(connection, "pg_advisory_unlock")
    ) == 1

    assert not calls_containing(connection, "UPDATE")
