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
