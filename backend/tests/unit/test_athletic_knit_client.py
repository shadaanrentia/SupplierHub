import inspect

import pytest

from multi_supplier.ak_client import AthleticKnitClient


@pytest.fixture
def client():
    return AthleticKnitClient({
        "account_number": "TEST-ACCOUNT",
        "password": "TEST-PASSWORD",
        "services": {
            "product_data": "https://example.test/productdata"
        }
    })


def test_sellable_request_is_true_only(client, monkeypatch):
    captured = {}

    def fake_post(endpoint, body_xml, soap_action):
        captured["endpoint"] = endpoint
        captured["body"] = body_xml
        captured["action"] = soap_action
        return "mock-response"

    monkeypatch.setattr(client, "_soap_post", fake_post)
    result = client.get_sellable_products_raw()

    assert result == "mock-response"
    assert "<shar:isSellable>true</shar:isSellable>" in captured["body"]
    assert "<shar:isSellable>false</shar:isSellable>" not in captured["body"]
    assert captured["endpoint"] == "https://example.test/productdata"
    assert captured["action"] == "getProductSellable"


def test_sellable_request_does_not_accept_a_state_argument(client):
    parameters = inspect.signature(
        client.get_sellable_products_raw
    ).parameters
    assert list(parameters) == []


def test_inventory_request_uses_configured_inventory_endpoint_and_action(client, monkeypatch):
    client.inventory_url = "https://example.test/inventory"
    captured = {}

    def fake_post(endpoint, body_xml, soap_action):
        captured.update(endpoint=endpoint, body=body_xml, action=soap_action)
        return "inventory-response"

    monkeypatch.setattr(client, "_soap_post", fake_post)
    assert client.get_inventory_raw("AK-100") == "inventory-response"
    assert captured["endpoint"] == client.inventory_url
    assert captured["action"] == "getInventoryLevels"
    assert "<shar:productId>AK-100</shar:productId>" in captured["body"]


def test_media_request_uses_configured_media_endpoint_and_action(client, monkeypatch):
    client.media_url = "https://example.test/media"
    captured = {}

    def fake_post(endpoint, body_xml, soap_action):
        captured.update(endpoint=endpoint, body=body_xml, action=soap_action)
        return "media-response"

    monkeypatch.setattr(client, "_soap_post", fake_post)
    assert client.get_media_raw("AK-100") == "media-response"
    assert captured["endpoint"] == client.media_url
    assert captured["action"] == "getMediaContent"
    assert "<shar:productId>" in captured["body"]
    assert "AK-100" in captured["body"]


def test_inventory_request_fails_clearly_when_endpoint_missing(client):
    with pytest.raises(ValueError, match="Inventory service URL"):
        client.get_inventory_raw("AK-100")


def test_media_request_fails_clearly_when_endpoint_missing(client):
    with pytest.raises(ValueError, match="Media service URL"):
        client.get_media_raw("AK-100")
