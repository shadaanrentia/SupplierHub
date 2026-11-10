
"""Offline tests for split-plan commit safety."""

import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "routes" / "export_review.py"


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


class FakeConnection:
    
    def __init__(self, saved_groups=None):
        self.executed = []
        self.fetch_calls = []
        self.fetchval_calls = []
        self.rollback_count = 0
        self.committed = False
        self.saved_groups = saved_groups or []

    @asynccontextmanager
    async def transaction(self):
        try:
            yield
            self.committed = True
        except Exception:
            self.rollback_count += 1
            raise

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self.saved_groups

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return 0

def valid_oversized_snapshot(
    product_id,
    duplicate_sku=False,
    blank_sku=False,
):
    """Create 200 valid variants, optionally introducing a bad SKU."""

    variants = [
        {
            "id": f"variant-{i}",
            "variant_sku": (
                ""
                if blank_sku and i == 199
                else "SKU-1"
                if duplicate_sku and i == 199
                else f"SKU-{i}"
            ),
            "color": "Black",
            "size": "M",
            "price": 10,
            "inventory": 20,
        }
        for i in range(200)
    ]

    return (
        {
            "id": product_id,
            "lightspeed_product_id": None,
        },
        variants,
        [],
    )


def load_split_plan(new_snapshot, connection, group_builder=None):
    """Load the actual split_plan route without starting FastAPI."""

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "split_plan"
    )

    function.decorator_list = []

    @asynccontextmanager
    async def acquire():
        yield connection

    class FakeService:
        domain_prefix = "test-store"

    async def fake_service():
        return FakeService()

    namespace = {
        "deps": SimpleNamespace(
            pool=SimpleNamespace(acquire=acquire)
        ),
        "service": fake_service,
        "new_split_snapshot": new_snapshot,
        "fingerprint": lambda product, variants: "valid-digest",
        "HTTPException": HTTPException,
        "Commit": object,
        "Depends": lambda dependency: dependency,
        "get_admin_user": lambda: None,
        "LIMIT": 199,
        "grouped_variants": group_builder or (
            lambda variants: [
                variants[i:i + 199]
                for i in range(0, len(variants), 199)
            ]
        ),
        "new_id": lambda: "generated-id",
        "json": __import__("json"),
    }

    module = ast.Module(
        body=[function],
        type_ignores=[],
    )

    exec(
        compile(module, str(SOURCE), "exec"),
        namespace,
    )

    return namespace["split_plan"]


@pytest.mark.asyncio
async def test_commit_rejects_variant_that_became_ineligible():
    conn = FakeConnection()

    async def changed_snapshot(conn, product_id):
        raise HTTPException(
            400,
            "Split plan blocked: SKU-2 inventory_zero",
        )

    split_plan = load_split_plan(changed_snapshot, conn)

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 400
    assert "SKU-2" in error.value.detail

    # Only the advisory lock may have been executed.
    assert len(conn.executed) == 1
    assert "pg_advisory_xact_lock" in conn.executed[0][0]

    # No existing plan was deleted and no new group was inserted.
    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )

    assert conn.rollback_count == 1
    assert conn.committed is False


@pytest.mark.asyncio
async def test_commit_rejects_changed_preview_fingerprint():
    conn = FakeConnection()

    async def valid_snapshot(conn, product_id):
        return (
            {
                "id": product_id,
                "lightspeed_product_id": None,
            },
            [
                {
                    "id": "1",
                    "variant_sku": "SKU-1",
                }
            ],
            [],
        )

    split_plan = load_split_plan(valid_snapshot, conn)

    body = SimpleNamespace(
        digest="old-preview-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 409
    assert "Variants changed" in error.value.detail

    # Fingerprint validation happens before reading or replacing saved groups.
    assert len(conn.fetch_calls) == 0
    assert len(conn.fetchval_calls) == 0

    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )

    assert conn.rollback_count == 1
    assert conn.committed is False


@pytest.mark.asyncio
async def test_commit_rejects_changed_store_before_database_access():
    conn = FakeConnection()

    async def unused_snapshot(conn, product_id):
        raise AssertionError("Snapshot must not be called")

    split_plan = load_split_plan(unused_snapshot, conn)

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="different-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 409
    assert "Store changed" in error.value.detail

    assert conn.executed == []
    assert conn.fetch_calls == []
    assert conn.fetchval_calls == []


@pytest.mark.asyncio
async def test_commit_rejects_duplicate_skus_before_deleting_plan():
    conn = FakeConnection()

    async def duplicate_snapshot(conn, product_id):
        return valid_oversized_snapshot(
            product_id,
            duplicate_sku=True,
        )

    split_plan = load_split_plan(duplicate_snapshot, conn)

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 400
    assert "duplicate" in error.value.detail.lower()

    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )

    assert conn.rollback_count == 1
    assert conn.committed is False


@pytest.mark.asyncio
async def test_commit_rejects_blank_skus_before_deleting_plan():
    conn = FakeConnection()

    async def blank_snapshot(conn, product_id):
        return valid_oversized_snapshot(
            product_id,
            blank_sku=True,
        )

    split_plan = load_split_plan(blank_snapshot, conn)

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 400
    assert "missing" in error.value.detail.lower()

    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )

    assert conn.rollback_count == 1
    assert conn.committed is False

@pytest.mark.asyncio
async def test_commit_rejects_generated_groups_with_duplicate_variant_ids():
    conn = FakeConnection()

    async def snapshot(conn, product_id):
        return valid_oversized_snapshot(product_id)

    def duplicate_group_builder(variants):
        return [
            variants[:199],
            [variants[0]],
        ]

    split_plan = load_split_plan(
        snapshot,
        conn,
        group_builder=duplicate_group_builder,
    )

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 400
    assert "exactly once" in error.value.detail

    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )


@pytest.mark.asyncio
async def test_commit_rejects_generated_groups_missing_variants():
    conn = FakeConnection()

    async def snapshot(conn, product_id):
        return valid_oversized_snapshot(product_id)

    def incomplete_group_builder(variants):
        return [variants[:199]]

    split_plan = load_split_plan(
        snapshot,
        conn,
        group_builder=incomplete_group_builder,
    )

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    with pytest.raises(HTTPException) as error:
        await split_plan("product-1", body, user={})

    assert error.value.status_code == 400
    assert "exactly once" in error.value.detail

    assert not any(
        "DELETE FROM lightspeed_export_groups" in sql
        or "INSERT INTO lightspeed_export_groups" in sql
        for sql, _ in conn.executed
    )


@pytest.mark.asyncio
async def test_commit_replaces_valid_plan_with_199_plus_1_groups():
    existing_plan = [
        {
            "id": "old-group",
            "state": "planned",
            "lightspeed_product_id": None,
        }
    ]

    conn = FakeConnection(saved_groups=existing_plan)

    async def snapshot(conn, product_id):
        return valid_oversized_snapshot(product_id)

    split_plan = load_split_plan(snapshot, conn)

    body = SimpleNamespace(
        digest="valid-digest",
        store_domain="test-store",
    )

    result = await split_plan("product-1", body, user={})

    assert result == {"success": True}
    assert conn.committed is True
    assert conn.rollback_count == 0

    deletes = [
        (sql, args)
        for sql, args in conn.executed
        if "DELETE FROM lightspeed_export_groups" in sql
    ]

    inserts = [
        (sql, args)
        for sql, args in conn.executed
        if "INSERT INTO lightspeed_export_groups" in sql
    ]

    assert len(deletes) == 1
    assert len(inserts) == 2

    import json

    first_group = json.loads(inserts[0][1][5])
    second_group = json.loads(inserts[1][1][5])

    assert len(first_group) == 199
    assert len(second_group) == 1

    assert len(set(first_group + second_group)) == 200