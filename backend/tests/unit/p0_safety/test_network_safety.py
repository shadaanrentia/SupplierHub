
import socket

import pytest
import requests


def test_external_http_is_blocked():
    with pytest.raises(
        AssertionError,
        match="External network access blocked",
    ):
        requests.get(
            "https://example.com",
            timeout=1,
        )


def test_external_socket_is_blocked():
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as connection:
        with pytest.raises(
            AssertionError,
            match="External network access blocked",
        ):
            connection.connect(("192.0.2.1", 5432))


def test_create_connection_is_blocked():
    with pytest.raises(
        AssertionError,
        match="External network access blocked",
    ):
        socket.create_connection(
            ("127.0.0.1", 5432),
            timeout=1,
        )


@pytest.mark.asyncio
async def test_asyncio_event_loop_still_works():
    import asyncio

    assert await asyncio.sleep(0, result=42) == 42
