from unittest.mock import AsyncMock, MagicMock

import pytest

from inventory_verification import InventoryVerificationError
from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService()
    monkeypatch.setenv("LIGHTSPEED_VERIFY_INVENTORY_READBACK", "1")
    monkeypatch.setattr(ls, "_put_legacy_21", MagicMock(return_value={"data": {"id": "remote-s"}}))
    verifier = AsyncMock()
    monkeypatch.setattr(ls, "_verify_remote_inventory", verifier)
    return ls, verifier


def payload(quantity):
    return {"details": {"price_excluding_tax": 20.0, "inventory": [
        {"outlet_id": "test-outlet", "current_amount": quantity}
    ]}}


@pytest.mark.asyncio
async def test_successful_put_must_verify_zero_inventory(service):
    ls, verifier = service
    verifier.side_effect = InventoryVerificationError("Inventory mismatch: expected 0, received 25")
    result = await ls._sync_single_variant("remote-s", "SKU-S", payload(0))
    assert result["success"] is False
    assert "mismatch" in result["error"].lower()
    verifier.assert_awaited_once_with("remote-s", "test-outlet", 0)
    ls._put_legacy_21.assert_called_once()


@pytest.mark.asyncio
async def test_matching_zero_stock_is_verified(service):
    ls, verifier = service
    verifier.return_value = True
    result = await ls._sync_single_variant("remote-s", "SKU-S", payload(0))
    assert result["success"] is True
    assert result["inventory_verified"] is True
    verifier.assert_awaited_once_with("remote-s", "test-outlet", 0)


@pytest.mark.asyncio
async def test_readback_api_failure_does_not_report_success(service):
    ls, verifier = service
    verifier.side_effect = ConnectionError("Simulated readback failure")
    result = await ls._sync_single_variant("remote-s", "SKU-S", payload(25))
    assert result["success"] is False
    ls._put_legacy_21.assert_called_once()


@pytest.mark.asyncio
async def test_missing_outlet_is_rejected(service):
    ls, verifier = service
    result = await ls._sync_single_variant(
        "remote-s", "SKU-S", {"details": {"inventory": [{"current_amount": 0}]}}
    )
    assert result["success"] is False
    verifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_disabled_uses_legacy_behavior(service, monkeypatch):
    ls, verifier = service
    monkeypatch.delenv("LIGHTSPEED_VERIFY_INVENTORY_READBACK", raising=False)
    result = await ls._sync_single_variant("remote-s", "SKU-S", payload(0))
    assert result["success"] is True
    assert result["inventory_verified"] is False
    verifier.assert_not_awaited()
