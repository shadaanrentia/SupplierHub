
"""Unit tests for Lightspeed single-variant updates.

All HTTP operations are mocked.
"""

from unittest.mock import MagicMock, AsyncMock

import pytest

from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService()

    put = MagicMock(return_value={"data": {"id": "remote-001"}})
    measurements = MagicMock()
    monkeypatch.setattr(ls, "_verify_remote_inventory", AsyncMock(return_value=True))

    monkeypatch.setattr(ls, "_put_legacy_21", put)
    monkeypatch.setattr(ls, "_sync_measurements", measurements)

    return ls, put, measurements


@pytest.mark.asyncio
async def test_successful_variant_update(service):
    ls, put, measurements = service

    payload = {
        "details": {
            "price_excluding_tax": 20.0,
            "inventory": [{
                "outlet_id": "test-outlet",
                "current_amount": 0,
                "reorder_amount": 0,
                "reorder_point": 0,
            }],
        }
    }

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-S",
        payload,
    )

    assert result["success"] is True

    put.assert_called_once_with(
        "products/remote-001",
        payload,
    )

    measurements.assert_not_called()


@pytest.mark.asyncio
async def test_lightspeed_validation_error(service):
    ls, put, measurements = service

    put.return_value = {
        "_lightspeed_validation_error": True,
        "message": "Invalid inventory payload",
    }

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-S",
        {"details": {}},
    )

    assert result["success"] is False
    assert result["sku"] == "SKU-S"

    measurements.assert_not_called()


@pytest.mark.asyncio
async def test_network_exception_returns_failure(service):
    ls, put, measurements = service

    put.side_effect = ConnectionError(
        "Simulated network failure"
    )

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-S",
        {"details": {}},
    )

    assert result["success"] is False
    assert "Simulated network failure" in result["error"]


@pytest.mark.asyncio
async def test_measurements_sync_after_update(service):
    ls, put, measurements = service

    source = {
        "weight": 2.0,
    }
    snapshot = {
        "weight": 1.0,
    }

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-S",
        {"details": {}},
        measurements=source,
        measurement_snapshot=snapshot,
    )

    assert result["success"] is True

    measurements.assert_called_once_with(
        "remote-001",
        source,
        snapshot,
    )
