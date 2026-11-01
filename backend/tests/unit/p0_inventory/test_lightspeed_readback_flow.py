
"""End-to-end inventory readback tests using mocked Lightspeed API calls.

No real network requests are made.
"""

from unittest.mock import MagicMock

import pytest

from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService()

    # Enable verification for these tests only.
    monkeypatch.setenv(
        "LIGHTSPEED_VERIFY_INVENTORY_READBACK",
        "1",
    )

    put_mock = MagicMock(
        return_value={"data": {"id": "remote-001"}}
    )

    get_mock = MagicMock()

    monkeypatch.setattr(ls, "_put_legacy_21", put_mock)
    monkeypatch.setattr(ls, "_get", get_mock)

    return ls, put_mock, get_mock


def update_payload(quantity):
    return {
        "details": {
            "price_excluding_tax": 20.0,
            "inventory": [{
                "outlet_id": "outlet-001",
                "current_amount": quantity,
            }],
        }
    }


def inventory_response(quantity, next_page=None):
    # Synthetic API fixture.
    # The response shape still requires real API validation.
    return {
        "data": [{
            "product_id": "remote-001",
            "location_id": "outlet-001",
            "current_inventory_level": quantity,
        }],
        "pagination": {
            "next": next_page,
        },
    }


@pytest.mark.asyncio
async def test_zero_inventory_verified_end_to_end(service):
    ls, put_mock, get_mock = service

    get_mock.return_value = inventory_response(0)

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-001",
        update_payload(0),
    )

    assert result["success"] is True
    assert result["inventory_verified"] is True

    put_mock.assert_called_once_with(
        "products/remote-001",
        update_payload(0),
    )

    get_mock.assert_called_once_with(
        "inventory_levels/remote-001"
    )


@pytest.mark.asyncio
async def test_stale_inventory_cannot_report_success(service):
    ls, put_mock, get_mock = service

    # SupplierHub requested 0, remote inventory remains 25.
    get_mock.return_value = inventory_response(25)

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-001",
        update_payload(0),
    )

    assert result["success"] is False
    assert "mismatch" in result["error"].lower()

    # A failed readback must NOT blindly repeat the write.
    assert put_mock.call_count == 1
    assert get_mock.call_count == 1


@pytest.mark.asyncio
async def test_missing_outlet_cannot_report_success(service):
    ls, put_mock, get_mock = service

    response = inventory_response(0)
    response["data"][0]["location_id"] = "wrong-outlet"

    get_mock.return_value = response

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-001",
        update_payload(0),
    )

    assert result["success"] is False
    assert put_mock.call_count == 1


@pytest.mark.asyncio
async def test_incomplete_pagination_cannot_report_success(service):
    ls, put_mock, get_mock = service

    get_mock.return_value = inventory_response(
        0,
        next_page="another-page",
    )

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-001",
        update_payload(0),
    )

    assert result["success"] is False
    assert "page" in result["error"].lower()
    assert put_mock.call_count == 1


@pytest.mark.asyncio
async def test_inventory_readback_timeout_cannot_report_success(service):
    ls, put_mock, get_mock = service

    get_mock.side_effect = TimeoutError(
        "Simulated inventory read timeout"
    )

    result = await ls._sync_single_variant(
        "remote-001",
        "SKU-001",
        update_payload(0),
    )

    assert result["success"] is False

    # A timeout does not authorize another inventory write.
    put_mock.assert_called_once()
    get_mock.assert_called_once()
