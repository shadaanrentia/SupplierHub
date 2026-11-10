
"""Offline regression tests for strict new Lightspeed split eligibility."""

import ast
from pathlib import Path

import pytest

from sku_eligibility import (
    eligibility_reason,
    new_export_eligible_variants,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "routes" / "export_review.py"


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


def make_variant(
    variant_id,
    inventory=5,
    price=10,
    sku=None,
    active=True,
):
    return {
        "id": str(variant_id),
        "variant_sku": sku or f"SKU-{variant_id}",
        "price": price,
        "inventory": inventory,
        "is_active": active,
        "active": active,
        "price_needs_review": False,
        "color": "Black",
        "size": f"Size-{variant_id}",
    }


def load_new_split_snapshot():
    """Load the actual helper without importing the FastAPI application."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "new_split_snapshot"
    )

    async def fake_snapshot(conn, product_id):
        return (
            {"id": product_id, "lightspeed_product_id": None},
            [],
            [],
        )

    namespace = {
        "snapshot": fake_snapshot,
        "row_to_dict": dict,
        "new_export_eligible_variants": new_export_eligible_variants,
        "eligibility_reason": eligibility_reason,
        "HTTPException": HTTPException,
    }

    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(SOURCE), "exec"), namespace)

    return namespace["new_split_snapshot"]


class FakeConnection:
    def __init__(self, variants):
        self.variants = variants
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)

        # Simulate PostgreSQL:
        # is_active IS DISTINCT FROM FALSE
        if "product_variants" in sql:
            return [
                variant
                for variant in self.variants
                if variant.get("is_active") is not False
            ]

        return self.variants

@pytest.mark.asyncio
async def test_new_split_snapshot_accepts_all_positive_stock_variants():
    variants = [
        make_variant(1, inventory=5),
        make_variant(2, inventory=1),
        make_variant(3, inventory=20),
    ]

    conn = FakeConnection(variants)
    snapshot = load_new_split_snapshot()

    product, selected, images = await snapshot(conn, "product-1")

    assert product["id"] == "product-1"
    assert {v["id"] for v in selected} == {"1", "2", "3"}
    assert images == []
    assert len(conn.queries) == 1


@pytest.mark.asyncio
async def test_new_split_snapshot_rejects_zero_inventory_variant():
    variants = [
        make_variant(1, inventory=5),
        make_variant(2, inventory=0),
    ]

    snapshot = load_new_split_snapshot()

    with pytest.raises(HTTPException) as error:
        await snapshot(FakeConnection(variants), "product-1")

    assert error.value.status_code == 400
    assert "SKU-2" in error.value.detail
    assert "inventory_zero" in error.value.detail


@pytest.mark.asyncio
async def test_new_split_snapshot_rejects_invalid_price():
    variants = [
        make_variant(1, inventory=5),
        make_variant(2, inventory=5, price=0),
    ]

    snapshot = load_new_split_snapshot()

    with pytest.raises(HTTPException) as error:
        await snapshot(FakeConnection(variants), "product-1")

    assert error.value.status_code == 400
    assert "SKU-2" in error.value.detail


@pytest.mark.asyncio
async def test_new_split_snapshot_rejects_invalid_inventory():
    variants = [
        make_variant(1, inventory=5),
        make_variant(2, inventory=-1),
    ]

    snapshot = load_new_split_snapshot()

    with pytest.raises(HTTPException) as error:
        await snapshot(FakeConnection(variants), "product-1")

    assert error.value.status_code == 400
    assert "SKU-2" in error.value.detail


@pytest.mark.asyncio
async def test_inactive_variant_is_not_part_of_split_snapshot():
    variants = [
        make_variant(1, inventory=5),
        make_variant(2, inventory=0, active=False),
    ]

    snapshot = load_new_split_snapshot()

    _, selected, _ = await snapshot(
        FakeConnection(variants),
        "product-1",
    )

    assert {v["id"] for v in selected} == {"1"}
