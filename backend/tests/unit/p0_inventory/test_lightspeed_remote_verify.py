
from unittest.mock import MagicMock

import pytest

from lightspeed_service import LightspeedService
from inventory_verification import InventoryVerificationError


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService()

    remote_get = MagicMock()
    monkeypatch.setattr(ls, "_get", remote_get)

    return ls, remote_get


def response(quantity):
    return {
        "data": [{
            "product_id": "remote-s",
            "location_id": "outlet-1",
            "current_inventory_level": quantity,
        }],
        "pagination": {"next": None},
    }


@pytest.mark.asyncio
async def test_verified_zero_inventory(service):
    ls, remote_get = service
    remote_get.return_value = response(0)

    assert await ls._verify_remote_inventory(
        "remote-s", "outlet-1", 0
    )

    remote_get.assert_called_once_with(
        "inventory_levels/remote-s"
    )


@pytest.mark.asyncio
async def test_stale_inventory_fails(service):
    ls, remote_get = service
    remote_get.return_value = response(25)

    with pytest.raises(
        InventoryVerificationError,
        match="mismatch",
    ):
        await ls._verify_remote_inventory(
            "remote-s", "outlet-1", 0
        )


@pytest.mark.asyncio
async def test_incomplete_page_fails(service):
    ls, remote_get = service

    data = response(0)
    data["pagination"]["next"] = "another-page"
    remote_get.return_value = data

    with pytest.raises(
        InventoryVerificationError,
        match="Additional inventory pages",
    ):
        await ls._verify_remote_inventory(
            "remote-s", "outlet-1", 0
        )


@pytest.mark.asyncio
async def test_unknown_pagination_fails(service):
    ls, remote_get = service
    remote_get.return_value = {
        "data": response(0)["data"]
    }

    with pytest.raises(
        InventoryVerificationError,
        match="pagination",
    ):
        await ls._verify_remote_inventory(
            "remote-s", "outlet-1", 0
        )


@pytest.mark.asyncio
async def test_readback_api_failure_propagates(service):
    ls, remote_get = service
    remote_get.side_effect = ConnectionError(
        "Simulated remote failure"
    )

    with pytest.raises(ConnectionError):
        await ls._verify_remote_inventory(
            "remote-s", "outlet-1", 0
        )
