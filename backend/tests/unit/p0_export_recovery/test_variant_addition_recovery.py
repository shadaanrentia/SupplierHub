
"""SupplierHub split-family variant addition safety tests.

No real database or Lightspeed connections.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import deps
import export_format
import export_safety
import multi_family
import pricing_rules


class FakeTransaction:
    """Simulate an async database transaction without real SQL."""

    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.calls.append(
            ("transaction_begin", "", ())
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.connection.calls.append(
                ("transaction_rollback", "", ())
            )
        else:
            self.connection.calls.append(
                ("transaction_commit", "", ())
            )

        return False


class FakeConnection:
    def __init__(self):
        self.groups = []
        self.journal = None
        self.calls = []
        self.locked = False

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        if "pg_try_advisory_lock" in query:
            self.locked = True
            return True
        raise AssertionError(f"Unexpected fetchval: {query}")

    
    def transaction(self):
        return FakeTransaction(self)


    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        if "FROM lightspeed_export_groups" in query:
            return [dict(g) for g in self.groups]
        raise AssertionError(f"Unexpected fetch: {query}")

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "FROM lightspeed_family_additions" in query:
            return self.journal
        raise AssertionError(f"Unexpected fetchrow: {query}")

    
    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))

        if "pg_advisory_unlock" in query:
            self.locked = False
            return "SELECT 1"

        if "UPDATE lightspeed_export_groups" in query:
            return "UPDATE 1"

        if "INSERT INTO lightspeed_family_additions" in query:
            return "INSERT 0 1"

        
        if "DELETE FROM lightspeed_family_additions" in query:
            self.journal = None
            return "DELETE 1"


        raise AssertionError(
            f"Unexpected execute: {query}"
        )



class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def env(monkeypatch):
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

    async def prepare(conn, product, variants, markup):
        return product, variants, markup

    monkeypatch.setattr(
        pricing_rules,
        "prepare_export_pricing",
        prepare,
    )

    # Keep the test focused on recovery rather than naming.
    monkeypatch.setattr(
        multi_family,
        "family_name",
        lambda product, group, variants: "Test Family",
    )

    product = {
        "id": "product-1",
        "product_name": "Test Shirt",
        "supplier_sku": "TEST",
    }

    variants = [
        {
            "id": "v1",
            "variant_sku": "TEST-S",
            "color": "Black",
            "size": "S",
            "inventory": 5,
            "price": 10,
        },
        {
            "id": "v2",
            "variant_sku": "TEST-M",
            "color": "Black",
            "size": "M",
            "inventory": 0,
            "price": 10,
        },
    ]

    images = [{
        "media_type": "image",
        "url": "https://example.invalid/image.jpg",
    }]

    conn.groups = [{
        "id": "group-1",
        "product_id": "product-1",
        "store_domain": "test-store",
        "group_number": 1,
        "export_mode": "size_families",
        "export_sku": "TEST-G01",
        "variant_ids": ["v1", "v2"],
        "state": "planned",
        "lightspeed_product_id": "remote-1",
    }]

    ls = MagicMock()
    ls.domain_prefix = "test-store"
    ls.remote_product_deleted.return_value = False

    ls.remote_family.return_value = {
        "id": "family-1",
        "name": "Test Family",
        "products": [{
            "id": "remote-1",
            "sku": "TEST-S",
        }],
        "variant_attribute_ids": ["color-id", "size-id"],
    }

    ls.lookup_skus.return_value = {}
    ls._ensure_variant_attributes.return_value = {
        "Color": "color-id",
        "Size": "size-id",
    }
    ls._get_inventory_outlet_id.return_value = "outlet-1"

    ls._create_product = AsyncMock(
        side_effect=AssertionError(
            "Unexpected product creation"
        )
    )

    ls._sync_existing_variants = AsyncMock(
        side_effect=AssertionError(
            "Unexpected variant synchronization"
        )
    )

    # Any unexpected family POST is a test failure.
    def family_api(method, endpoint, *args, **kwargs):
        if method.upper() == "POST":
            raise AssertionError(
                "Unexpected Lightspeed family POST"
            )
        raise AssertionError(
            f"Unexpected family request: {method} {endpoint}"
        )

    ls.family_request.side_effect = family_api

    return SimpleNamespace(
        conn=conn,
        ls=ls,
        product=product,
        variants=variants,
        images=images,
    )


async def run_export(env):
    return await multi_family.export_families(
        env.ls,
        env.product,
        env.variants,
        env.images,
        20,
        None,
    )


def assert_no_family_post(env):
    posts = [
        call for call in env.ls.family_request.call_args_list
        if call.args and call.args[0] == "POST"
    ]
    assert posts == []


@pytest.mark.asyncio
async def test_unresolved_variant_journal_blocks_duplicate_post(env):
    # A previous request may have added TEST-M remotely.
    # Its outcome is not yet visible in the remote family.
    env.conn.journal = {"state": "adding"}

    result = await run_export(env)

    assert result["success"] is False
    assert "Previous variant addition is not visible" in result["error"]

    assert_no_family_post(env)
    env.ls._create_product.assert_not_awaited()
    env.ls._sync_existing_variants.assert_not_awaited()

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_oversized_group_rejected_before_creation(env):
    # Build 201 otherwise valid and unique variants.
    env.variants = [
        {
            "id": f"v{i}",
            "variant_sku": f"TEST-{i}",
            "color": f"Color-{i}",
            "size": "M",
            "inventory": 1,
            "price": 10,
        }
        for i in range(201)
    ]

    env.conn.groups[0]["variant_ids"] = [
        v["id"] for v in env.variants
    ]

    result = await run_export(env)

    assert result["success"] is False
    assert "1–200 eligible variants" in result["error"]

    env.ls._create_product.assert_not_awaited()
    assert_no_family_post(env)

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_missing_variant_without_journal_still_requires_review(env):
    # Remote family is missing TEST-M, and there is no
    # previous addition journal entry.
    #
    # This should reach the next step of the export process:
    # adding the missing variant. Our fake API blocks the POST
    # so nothing is created.
    env.conn.journal = None

    result = await run_export(env)

    assert result["success"] is False
    assert "Unexpected Lightspeed family POST" in result["error"]

    assert env.ls.family_request.call_count == 1
    assert env.ls.family_request.call_args.args[0] == "POST"

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_successful_variant_post_but_readback_fails(env):
    """
    Lightspeed accepts a variant addition, but the following
    family read fails.

    SupplierHub must not issue another POST automatically.
    """
    env.conn.journal = None

    original_family = env.ls.remote_family.return_value

    # First GET: family is missing TEST-M.
    # Second GET: simulate failed readback after successful POST.
    env.ls.remote_family.side_effect = [
        original_family,
        ConnectionError("Simulated readback failure"),
    ]

    post_calls = []

    def fake_family_request(method, endpoint, *args, **kwargs):
        if method == "POST":
            post_calls.append((endpoint, args))
            return {"data": {"success": True}}

        raise AssertionError(
            f"Unexpected API request: {method} {endpoint}"
        )

    env.ls.family_request.side_effect = fake_family_request

    result = await run_export(env)

    assert result["success"] is False
    assert "Simulated readback failure" in result["error"]

    # Lightspeed received exactly one simulated addition POST.
    assert len(post_calls) == 1

    # Journal insertion must happen before the POST.
    journal_inserts = [
        call
        for call in env.conn.calls
        if (
            call[0] == "execute"
            and "INSERT INTO lightspeed_family_additions" in call[1]
        )
    ]

    assert len(journal_inserts) == 1

    commits = [
        call
        for call in env.conn.calls
        if call[0] == "transaction_commit"
    ]

    assert len(commits) == 1

    # No variant sync or additional product creation.
    env.ls._create_product.assert_not_awaited()
    env.ls._sync_existing_variants.assert_not_awaited()

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_retry_after_uncertain_variant_post_blocks_duplicate(env):
    """
    Simulate a previous POST that may have succeeded.

    The remote family still does not show TEST-M, while its
    journal records 'adding'. A retry must not POST it again.
    """
    env.conn.journal = {"state": "adding"}
    env.conn.groups[0]["state"] = "uncertain"

    result = await run_export(env)

    assert result["success"] is False
    assert (
        "Previous variant addition is not visible"
        in result["error"]
    )

    post_calls = [
        call
        for call in env.ls.family_request.call_args_list
        if call.args and call.args[0] == "POST"
    ]

    assert len(post_calls) == 0

    env.ls._create_product.assert_not_awaited()
    env.ls._sync_existing_variants.assert_not_awaited()

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_journal_commit_failure_prevents_variant_post(
    env, monkeypatch
):
    """
    A database transaction fails during commit.

    SupplierHub must not send the remote variant-addition POST
    because the 'adding' journal was not durably committed.
    """
    env.conn.journal = None

    class FailingCommitTransaction:
        async def __aenter__(self):
            env.conn.calls.append(
                ("transaction_begin", "", ())
            )
            return self

        async def __aexit__(self, exc_type, exc, tb):
            env.conn.calls.append(
                ("transaction_commit_failed", "", ())
            )
            raise RuntimeError(
                "Simulated journal commit failure"
            )

    monkeypatch.setattr(
        env.conn,
        "transaction",
        lambda: FailingCommitTransaction(),
    )

    result = await run_export(env)

    assert result["success"] is False
    assert "Simulated journal commit failure" in result["error"]

    # The journal insert was attempted.
    inserts = [
        call for call in env.conn.calls
        if (
            call[0] == "execute"
            and "INSERT INTO lightspeed_family_additions"
            in call[1]
        )
    ]
    assert len(inserts) == 1

    # But the transaction was not committed.
    assert any(
        call[0] == "transaction_commit_failed"
        for call in env.conn.calls
    )

    # No remote POST may occur after a failed journal commit.
    env.ls.family_request.assert_not_called()
    env.ls._create_product.assert_not_awaited()
    env.ls._sync_existing_variants.assert_not_awaited()

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_retry_recognizes_variant_already_added_remotely(env):
    """
    A previous variant POST may have succeeded.

    During retry, both variants are already visible in
    Lightspeed. SupplierHub must skip the addition POST.
    """
    env.conn.journal = {"state": "adding"}
    env.conn.groups[0]["state"] = "uncertain"

    # The remote family now contains BOTH expected variants.
    env.ls.remote_family.return_value = {
        "id": "family-1",
        "name": "Test Family",
        "products": [
            {
                "id": "remote-1",
                "sku": "TEST-S",
            },
            {
                "id": "remote-2",
                "sku": "TEST-M",
            },
        ],
        "variant_attribute_ids": [
            "color-id",
            "size-id",
        ],
    }

    # Stop at metadata synchronization so this test
    # does not need to simulate all later export stages.
    env.ls.update_family_metadata.side_effect = RuntimeError(
        "Reached metadata synchronization"
    )

    result = await run_export(env)

    assert result["success"] is False
    assert "Reached metadata synchronization" in result["error"]

    # Existing variants must never be added a second time.
    env.ls.family_request.assert_not_called()
    env.ls._create_product.assert_not_awaited()

    # The code correctly proceeded past variant reconciliation.
    env.ls.update_family_metadata.assert_called_once()

    # No missing-variant journal lookup was necessary.
    journal_reads = [
        call for call in env.conn.calls
        if (
            call[0] == "fetchrow"
            and "FROM lightspeed_family_additions" in call[1]
        )
    ]
    assert journal_reads == []

    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_confirmed_remote_variant_clears_stale_addition_journal(env):
    """
    A previous addition was recorded as 'adding', but
    Lightspeed now confirms the variant exists.

    The stale journal should be cleaned up after
    remote membership reconciliation.
    """
    env.conn.journal = {"state": "adding"}
    env.conn.groups[0]["state"] = "uncertain"

    # Both variants are now confirmed in Lightspeed.
    env.ls.remote_family.return_value = {
        "id": "family-1",
        "name": "Test Family",
        "products": [
            {"id": "remote-1", "sku": "TEST-S"},
            {"id": "remote-2", "sku": "TEST-M"},
        ],
        "variant_attribute_ids": [
            "color-id",
            "size-id",
        ],
    }

    # Stop after membership reconciliation.
    env.ls.update_family_metadata.side_effect = RuntimeError(
        "Simulated later metadata failure"
    )

    result = await run_export(env)

    assert result["success"] is False
    assert "Simulated later metadata failure" in result["error"]

    # No additional remote variant creation.
    env.ls._create_product.assert_not_awaited()
    env.ls.family_request.assert_not_called()

    # A confirmed remote member should no longer have
    # an unresolved addition journal entry.
    cleanup_calls = [
        call
        for call in env.conn.calls
        if (
            call[0] == "execute"
            and "DELETE FROM lightspeed_family_additions"
            in call[1]
        )
    ]

    assert cleanup_calls, (
        "Stale addition journal was not cleaned up "
        "after remote membership verification"
    )

    assert env.conn.journal is None
    assert env.conn.locked is False


@pytest.mark.asyncio
async def test_journal_cleanup_failure_does_not_repeat_variant_post(
    env, monkeypatch
):
    """
    The remote family contains all expected variants, but
    PostgreSQL fails while clearing stale 'adding' records.

    Export must fail safely without issuing any variant POST.
    """
    env.conn.journal = {"state": "adding"}
    env.conn.groups[0]["state"] = "uncertain"

    # Simulate Lightspeed confirming both reviewed SKUs.
    env.ls.remote_family.return_value = {
        "id": "family-1",
        "name": "Test Family",
        "products": [
            {"id": "remote-1", "sku": "TEST-S"},
            {"id": "remote-2", "sku": "TEST-M"},
        ],
        "variant_attribute_ids": [
            "color-id",
            "size-id",
        ],
    }

    original_execute = env.conn.execute

    async def failing_execute(query, *args):
        if "DELETE FROM lightspeed_family_additions" in query:
            env.conn.calls.append(
                ("cleanup_failed", query, args)
            )
            raise RuntimeError(
                "Simulated journal cleanup failure"
            )

        return await original_execute(query, *args)

    monkeypatch.setattr(
        env.conn,
        "execute",
        failing_execute,
    )

    result = await run_export(env)

    # The cleanup error must not be silently ignored.
    assert result["success"] is False
    assert "Simulated journal cleanup failure" in result["error"]

    # No Lightspeed creation or addition request is permitted.
    env.ls._create_product.assert_not_awaited()

    post_calls = [
        call
        for call in env.ls.family_request.call_args_list
        if call.args and call.args[0] == "POST"
    ]
    assert post_calls == []

    # No downstream metadata/inventory synchronization.
    env.ls.update_family_metadata.assert_not_called()
    env.ls._sync_existing_variants.assert_not_awaited()

    # Failed cleanup must not remove the pending journal.
    assert env.conn.journal == {"state": "adding"}

    # Export must remain marked as uncertain.
    assert env.conn.groups[0]["state"] == "uncertain"

    # The export lock must always be released.
    assert env.conn.locked is False

