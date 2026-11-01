
"""Tests for Lightspeed HTTP responses and variant updates.

Never makes real HTTP requests.
"""

from unittest.mock import MagicMock

import pytest
import requests

from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService(
        domain_prefix="isolated-test-store",
        personal_token="",
    )

    session = MagicMock()
    monkeypatch.setattr(ls, "_http_session", lambda: session)
    monkeypatch.setattr(ls, "_throttle", lambda: None)
    monkeypatch.setattr(ls, "_handle_rate_limit", lambda response: None)
    monkeypatch.setattr(ls, "_headers", lambda: {"Authorization": "TEST-ONLY"})

    return ls, session


def make_response(status, data=None, text=""):
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text

    if data is None:
        response.json.side_effect = ValueError("Not JSON")
    else:
        response.json.return_value = data

    response.raise_for_status.side_effect = requests.HTTPError(
        f"HTTP {status}",
        response=response,
    )

    return response


def test_successful_put_uses_correct_endpoint(service):
    ls, session = service

    session.put.return_value = make_response(
        200,
        {"data": {"id": "variant-1"}},
    )

    payload = {
        "details": {
            "inventory": [{
                "outlet_id": "outlet-1",
                "current_amount": 0,
            }]
        }
    }

    result = ls._put_legacy_21("products/variant-1", payload)

    assert result["data"]["id"] == "variant-1"

    args, kwargs = session.put.call_args
    assert args[0] == (
        "https://isolated-test-store.retail.lightspeed.app"
        "/api/2.1/products/variant-1"
    )
    assert kwargs["json"] == payload
    assert kwargs["timeout"] == 120


def test_validation_error_is_preserved(service):
    ls, session = service

    session.put.return_value = make_response(
        422,
        {"message": "Invalid inventory value"},
    )

    result = ls._put_legacy_21(
        "products/variant-1",
        {"details": {}},
    )

    assert result["_lightspeed_validation_error"] is True
    assert result["status_code"] == 422


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_http_errors_are_raised(service, status):
    ls, session = service

    session.put.return_value = make_response(
        status,
        {"message": "Simulated API error"},
    )

    with pytest.raises(requests.HTTPError):
        ls._put_legacy_21(
            "products/variant-1",
            {"details": {}},
        )


def test_connection_timeout_propagates(service):
    ls, session = service

    session.put.side_effect = requests.Timeout(
        "Simulated request timeout"
    )

    with pytest.raises(requests.Timeout):
        ls._put_legacy_21(
            "products/variant-1",
            {"details": {}},
        )


def test_success_response_without_json(service):
    ls, session = service

    session.put.return_value = make_response(
        204,
        None,
        "",
    )

    result = ls._put_legacy_21(
        "products/variant-1",
        {"details": {}},
    )

    assert result["success"] is True
    assert result["status_code"] == 204
