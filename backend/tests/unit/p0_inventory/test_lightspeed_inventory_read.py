
"""Read-only Lightspeed inventory endpoint tests."""

from unittest.mock import MagicMock

import pytest

from lightspeed_service import LightspeedService


@pytest.fixture
def service(monkeypatch):
    ls = LightspeedService()

    session = MagicMock()
    monkeypatch.setattr(ls, "_http_session", lambda: session)
    monkeypatch.setattr(ls, "_throttle", lambda: None)
    monkeypatch.setattr(ls, "_handle_rate_limit", lambda r: None)
    monkeypatch.setattr(ls, "_headers", lambda: {
        "Authorization": "Bearer TEST-ONLY",
        "Accept": "application/json",
    })

    return ls, session


def test_inventory_read_uses_correct_endpoint(service):
    ls, session = service

    # A synthetic response used to verify transport only.
    response = MagicMock()
    response.ok = True
    response.status_code = 200
    response.json.return_value = {"data": []}
    session.get.return_value = response

    result = ls._get(
        "inventory_levels/remote-product-1"
    )

    assert result == {"data": []}

    args, kwargs = session.get.call_args

    assert args[0].endswith(
        "/api/2026-07/inventory_levels/remote-product-1"
    )
    assert kwargs["timeout"] == 120

    # This test must never write to Lightspeed.
    session.put.assert_not_called()
    session.post.assert_not_called()
    session.patch.assert_not_called()


def test_inventory_read_api_failure_is_not_success(service):
    ls, session = service

    response = MagicMock()
    response.ok = False
    response.status_code = 403
    response.text = "Forbidden"
    response.json.return_value = {
        "message": "Missing inventory read permission"
    }

    session.get.return_value = response
    response.raise_for_status.side_effect = RuntimeError(
        "HTTP 403"
    )

    with pytest.raises(RuntimeError, match="HTTP 403"):
        ls._get("inventory_levels/remote-product-1")

    session.put.assert_not_called()
    session.post.assert_not_called()
