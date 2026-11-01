
"""P0 safety tests: invalid inventory must never reach Lightspeed."""

from unittest.mock import MagicMock

import pytest

from lightspeed_service import LightspeedService


@pytest.fixture
def service():
    ls = LightspeedService(
        domain_prefix="isolated-test",
        personal_token="fake-token",
    )

    # No network calls are permitted.
    ls.mock_mode = False
    ls._put = MagicMock(return_value={"data": {}})
    ls._get_outlets = MagicMock(return_value=[])

    return ls


@pytest.mark.parametrize(
    "invalid_count",
    [
        -1,
        -100,
        None,
        "invalid",
        float("nan"),
        float("inf"),
        True,
    ],
)
def test_invalid_inventory_never_reaches_lightspeed(
    service, invalid_count
):
    result = service.update_product_inventory(
        "product-123",
        "outlet-123",
        invalid_count,
    )

    assert result["success"] is False

    # Most important assertion:
    # an invalid quantity must not be sent remotely.
    service._put.assert_not_called()


def test_valid_zero_inventory_is_allowed(service):
    result = service.update_product_inventory(
        "product-123",
        "outlet-123",
        0,
    )

    assert result["success"] is True

    service._put.assert_called_once()

    endpoint, payload = service._put.call_args.args

    assert endpoint == "products/product-123"
    assert payload["inventory"] == [
        {
            "outlet_id": "outlet-123",
            "count": 0,
        }
    ]


def test_missing_product_id_never_writes(service):
    result = service.update_product_inventory(
        "",
        "outlet-123",
        10,
    )

    assert result["success"] is False
    service._put.assert_not_called()


def test_missing_outlet_id_never_writes(service):
    result = service.update_product_inventory(
        "product-123",
        "",
        10,
    )

    assert result["success"] is False
    service._put.assert_not_called()


@pytest.mark.parametrize(
    "invalid_count",
    [
        -0.1,
        2.5,
        "3.7",
        float("-inf"),
        2147483648,
        {},
        [],
    ],
)
def test_additional_invalid_quantities_never_write(
    service, invalid_count
):
    result = service.update_product_inventory(
        "product-123",
        "outlet-123",
        invalid_count,
    )

    assert result["success"] is False
    service._put.assert_not_called()


def test_whole_number_string_is_accepted(service):
    result = service.update_product_inventory(
        "product-123",
        "outlet-123",
        "25",
    )

    assert result["success"] is True

    payload = service._put.call_args.args[1]
    assert payload["inventory"][0]["count"] == 25


def test_failed_lightspeed_update_not_reported_as_success(service):
    service._put.side_effect = RuntimeError(
        "Simulated Lightspeed failure"
    )

    result = service.update_product_inventory(
        "product-123",
        "outlet-123",
        10,
    )

    assert result["success"] is False
    service._put.assert_called_once()
