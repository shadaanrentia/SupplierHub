from unittest.mock import MagicMock

import pytest

from lightspeed_service import LightspeedService
from inventory_verification import InventoryVerificationError


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService(domain_prefix="test-store")
    monkeypatch.setattr(ls, "_headers", lambda: {"Accept": "application/json"})
    remote_get = MagicMock()
    monkeypatch.setattr(ls, 'family_request', remote_get)
    # The 2.0 fallback must be mocked as well as the modern family request.
    # Keep the repository's real-network guard enabled.
    session = MagicMock()
    session.get.side_effect = AssertionError('Unexpected legacy inventory GET')
    monkeypatch.setattr(ls, '_http_session', lambda: session)
    monkeypatch.setattr(ls, '_throttle', lambda: None)
    return ls, remote_get


def response(quantity):
    return {'data': {'id': 'remote-s', 'outlet_inventories': [
        {'outlet_id': 'outlet-1', 'current_amount': quantity},
    ]}}


def legacy_response(quantity):
    return {'data': {'id': 'remote-s', 'inventory': [
        {'product_id': 'remote-s', 'outlet_id': 'outlet-1', 'count': quantity},
    ]}}


def mock_legacy(monkeypatch, ls, payload):
    session = ls._http_session()
    session.get.side_effect = None
    http_response = MagicMock()
    session.get.return_value = http_response
    monkeypatch.setattr(ls, '_handle_rate_limit', MagicMock())
    decode = MagicMock(return_value=payload)
    monkeypatch.setattr(ls, '_handle_response', decode)
    return session, http_response, decode


@pytest.mark.asyncio
async def test_verified_zero_inventory(service):
    ls, remote_get = service
    remote_get.return_value = response(0)
    assert await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    remote_get.assert_called_once_with('GET', 'products/remote-s')
    ls._http_session().get.assert_not_called()


@pytest.mark.asyncio
async def test_stale_inventory_fails(service):
    ls, remote_get = service
    remote_get.return_value = response(25)
    with pytest.raises(InventoryVerificationError, match='mismatch'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    ls._http_session().get.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_outlet_records_fail(service):
    ls, remote_get = service
    data = response(0)
    data['data']['outlet_inventories'] *= 2
    remote_get.return_value = data
    with pytest.raises(InventoryVerificationError, match='exactly one'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    ls._http_session().get.assert_not_called()


@pytest.mark.asyncio
async def test_missing_outlet_collection_fails(service, monkeypatch):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'remote-s'}}
    session, _, _ = mock_legacy(monkeypatch, ls, {'data': {'id': 'remote-s'}})
    with pytest.raises(InventoryVerificationError, match='inventory records'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    assert session.get.call_count == 3


@pytest.mark.asyncio
async def test_missing_modern_collection_uses_legacy_zero(service, monkeypatch):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'remote-s'}}
    session, http_response, decode = mock_legacy(monkeypatch, ls, legacy_response('0.00000'))
    assert await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    session.get.assert_called_once_with(
        'https://test-store.retail.lightspeed.app/api/2.0/products/remote-s',
        headers=ls._headers(), timeout=120,
    )
    decode.assert_called_once_with(http_response)


@pytest.mark.asyncio
async def test_legacy_mismatch_fails(service, monkeypatch):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'remote-s'}}
    session, _, _ = mock_legacy(monkeypatch, ls, legacy_response(25))
    with pytest.raises(InventoryVerificationError, match='mismatch'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    assert session.get.call_count == 3


@pytest.mark.asyncio
async def test_legacy_missing_outlet_does_not_mean_zero(service, monkeypatch):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'remote-s'}}
    payload = legacy_response(0)
    payload['data']['inventory'][0]['outlet_id'] = 'other-outlet'
    mock_legacy(monkeypatch, ls, payload)
    with pytest.raises(InventoryVerificationError, match='exactly one'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)


@pytest.mark.asyncio
async def test_wrong_modern_product_cannot_use_fallback(service):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'another-product'}}
    with pytest.raises(InventoryVerificationError, match='wrong product'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    ls._http_session().get.assert_not_called()


@pytest.mark.asyncio
async def test_null_modern_collection_cannot_use_fallback(service):
    ls, remote_get = service
    remote_get.return_value = {'data': {'id': 'remote-s', 'outlet_inventories': None}}
    with pytest.raises(InventoryVerificationError, match='outlet inventories'):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    ls._http_session().get.assert_not_called()


@pytest.mark.asyncio
async def test_readback_api_failure_propagates(service):
    ls, remote_get = service
    remote_get.side_effect = ConnectionError('Simulated remote failure')
    with pytest.raises(ConnectionError):
        await ls._verify_remote_inventory('remote-s', 'outlet-1', 0)
    ls._http_session().get.assert_not_called()
