
"""Split export state and partial-failure recovery tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import export_safety


@pytest.fixture
def split_environment(monkeypatch):
    import export_format
    import pricing_rules
    import single_family

    variants = [
        {
            "id": f"variant-{i}",
            "variant_sku": f"SKU-{i}",
            "color": "Black",
            "size": "S" if i == 1 else "M",
            "price": 10.0,
            "inventory": 25,
            "is_active": True,
        }
        for i in (1, 2)
    ]

    groups = [
        {
            "id": "group-1",
            "group_number": 1,
            "export_sku": "TEST-G1",
            "variant_ids": ["variant-1"],
            "state": "planned",
            "lightspeed_product_id": None,
        },
        {
            "id": "group-2",
            "group_number": 2,
            "export_sku": "TEST-G2",
            "variant_ids": ["variant-2"],
            "state": "planned",
            "lightspeed_product_id": None,
        },
    ]

    conn = AsyncMock()
    conn.fetch.return_value = groups
    conn.fetchval.side_effect = lambda query, group_id: group_id

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    monkeypatch.setattr(export_safety.deps, "pool", pool)

    async def fake_pricing(conn, product, variants, markup):
        priced = [
            dict(v, retail_price_override=20.0)
            for v in variants
        ]
        return dict(
            product,
            calculated_sale_price=20.0,
        ), priced, markup

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
        domain_prefix="fake-test-store",
        assert_split_skus_available=MagicMock(),
        create_or_update_product=AsyncMock(),
    )

    product = {
        "id": "product-1",
        "supplier_sku": "TEST",
        "product_name": "Cotton Tee",
        "base_price": 10.0,
    }

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/product.jpg",
        "source_part_ids": ["SKU-1","SKU-2"],
    }]

    return ls, conn, product, variants, images, repair


@pytest.mark.asyncio
async def test_first_group_succeeds_second_group_fails(
    split_environment,
):
    ls, conn, product, variants, images, repair = (
        split_environment
    )

    ls.create_or_update_product.side_effect = [
        {
            "success": True,
            "lightspeed_id": "LS-GROUP-1",
        },
        {
            "success": False,
            "error": "Simulated group 2 failure",
        },
    ]

    result = await export_safety._legacy_export_product(
        ls, product, variants, images, 50, "category-1"
    )

    assert result["success"] is False
    assert result["completed_groups"] == ["LS-GROUP-1"]
    assert "Simulated group 2 failure" in result["error"]

    assert ls.create_or_update_product.await_count == 2
    repair.assert_awaited_once()

    sql_calls = [
        call.args[0]
        for call in conn.execute.await_args_list
    ]

    # Group 1 must be recorded as completed.
    assert any(
        "state='done'" in sql for sql in sql_calls
    )

    # Group 2 must be marked uncertain.
    assert any(
        "state='uncertain'" in sql for sql in sql_calls
    )


@pytest.mark.asyncio
async def test_uncertain_group_blocks_automatic_retry(
    split_environment,
):
    ls, conn, product, variants, images, repair = (
        split_environment
    )

    # Simulate a previous attempt with an uncertain result.
    conn.fetch.return_value[1]["state"] = "uncertain"

    with pytest.raises(
        ValueError,
        match="uncertain result",
    ):
        await export_safety._legacy_export_product(
            ls, product, variants, images, 50, "category-1"
        )

    # No new remote product must be created.
    ls.create_or_update_product.assert_not_awaited()
