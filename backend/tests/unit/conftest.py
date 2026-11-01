
"""Network safety guard for SupplierHub unit tests.

Blocks outbound connections while allowing Python's internal
asyncio socketpair mechanism to operate on localhost.
"""

import ipaddress
import socket

import pytest
import requests


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def is_loopback(address):
        if not isinstance(address, tuple) or not address:
            return False

        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError):
            return False

    def guarded_connect(sock, address):
        if is_loopback(address):
            return original_connect(sock, address)

        raise AssertionError(
            "External network access blocked during unit testing. "
            "Mock the external dependency."
        )

    def guarded_connect_ex(sock, address):
        if is_loopback(address):
            return original_connect_ex(sock, address)

        raise AssertionError(
            "External network access blocked during unit testing. "
            "Mock the external dependency."
        )

    def guarded_create_connection(address, *args, **kwargs):
        raise AssertionError(
            "External network access blocked during unit testing. "
            "Mock the external dependency."
        )

    def guarded_http_request(self, *args, **kwargs):
        raise AssertionError(
            "External network access blocked during unit testing. "
            "Mock HTTP requests."
        )

    monkeypatch.setattr(
        socket.socket,
        "connect",
        guarded_connect,
    )

    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        guarded_connect_ex,
    )

    monkeypatch.setattr(
        socket,
        "create_connection",
        guarded_create_connection,
    )

    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        guarded_http_request,
    )
