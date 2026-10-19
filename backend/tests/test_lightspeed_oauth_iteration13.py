"""Backend tests for Lightspeed OAuth 2.0 integration (iteration 13)."""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

CLIENT_ID = "public_ycmUEk1yjqgUZYzeGFCwGNxVmMDe9Wgw"
CLIENT_SECRET = "secret_7LFgEv69Z2ZUmRxaKNduSeMUmQVzkw1e"
DOMAIN_PREFIX = "redleafssports"


@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("token") or r.json().get("access_token")
    assert token
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---------- Settings save/load ----------
class TestLightspeedSettings:
    def test_get_settings(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/settings")
        assert r.status_code == 200
        data = r.json()
        # Fields should exist (either populated or empty string)
        for key in ["lightspeed_store_id", "lightspeed_client_id", "lightspeed_client_secret",
                    "lightspeed_oauth_connected"]:
            assert key in data, f"Missing field: {key}"

    def test_save_lightspeed_oauth_settings(self, auth_client):
        payload = {
            "lightspeed_store_id": DOMAIN_PREFIX,
            "lightspeed_client_id": CLIENT_ID,
            "lightspeed_client_secret": CLIENT_SECRET,
        }
        r = auth_client.put(f"{BASE_URL}/api/settings", json=payload)
        assert r.status_code == 200, f"PUT failed: {r.text}"
        assert r.json().get("success") is True

        # Verify persistence
        r2 = auth_client.get(f"{BASE_URL}/api/settings")
        assert r2.status_code == 200
        d = r2.json()
        assert d["lightspeed_store_id"] == DOMAIN_PREFIX
        assert d["lightspeed_client_id"] == CLIENT_ID
        # secret should be masked
        assert d["lightspeed_client_secret"] == "***"


# ---------- OAuth authorize URL ----------
class TestOAuthAuthorize:
    def test_authorize_url_generated(self, auth_client):
        # Ensure creds saved
        auth_client.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": DOMAIN_PREFIX,
            "lightspeed_client_id": CLIENT_ID,
            "lightspeed_client_secret": CLIENT_SECRET,
        })
        r = auth_client.get(f"{BASE_URL}/api/lightspeed/oauth/authorize")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "authorize_url" in data
        assert "state" in data
        url = data["authorize_url"]
        assert "secure.retail.lightspeed.app/connect" in url
        assert f"client_id={CLIENT_ID}" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=" in url
        assert "scope=" in url

    def test_authorize_fails_without_client_id(self, auth_client):
        # Clear client_id
        auth_client.put(f"{BASE_URL}/api/settings", json={"lightspeed_client_id": ""})
        r = auth_client.get(f"{BASE_URL}/api/lightspeed/oauth/authorize")
        assert r.status_code == 400
        # Restore
        auth_client.put(f"{BASE_URL}/api/settings", json={"lightspeed_client_id": CLIENT_ID})


# ---------- Test connection ----------
class TestConnectionEndpoint:
    def test_test_connection_no_oauth(self, auth_client):
        # Disconnect first
        auth_client.post(f"{BASE_URL}/api/lightspeed/oauth/disconnect")
        r = auth_client.post(f"{BASE_URL}/api/settings/lightspeed/test")
        assert r.status_code == 200
        data = r.json()
        # Should indicate not connected / needs oauth
        assert data.get("connected") is False
        # Either needs_oauth flag or a message about needing OAuth/token
        msg = (data.get("message") or "").lower()
        assert data.get("needs_oauth") or "token" in msg or "oauth" in msg or "credential" in msg


# ---------- OAuth disconnect ----------
class TestOAuthDisconnect:
    def test_disconnect_clears_tokens(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/lightspeed/oauth/disconnect")
        assert r.status_code == 200
        data = r.json()
        assert data.get("success") is True or data.get("status") == "disconnected"
        # Verify GET settings shows oauth not connected
        r2 = auth_client.get(f"{BASE_URL}/api/settings")
        assert r2.json().get("lightspeed_oauth_connected") is False


# ---------- Other settings still work ----------
class TestOtherSettings:
    def test_save_odoo(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/settings", json={
            "odoo_url": "https://odoo.example.com",
            "odoo_db": "test_db",
            "odoo_username": "test@example.com",
        })
        assert r.status_code == 200

    def test_save_sync_schedule(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/settings", json={
            "sync_products_interval_hours": 12,
            "sync_inventory_interval_minutes": 60,
            "auto_sync_enabled": True,
        })
        assert r.status_code == 200
        d = auth_client.get(f"{BASE_URL}/api/settings").json()
        assert d["sync_products_interval_hours"] == 12
        assert d["sync_inventory_interval_minutes"] == 60
        assert d["auto_sync_enabled"] is True

    def test_save_warehouse_and_markup(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/settings", json={
            "preferred_warehouse": "MISSISSAUGA/ON",
            "markup_percentage": 45,
        })
        assert r.status_code == 200
        d = auth_client.get(f"{BASE_URL}/api/settings").json()
        assert d["preferred_warehouse"] == "MISSISSAUGA/ON"
        assert float(d["markup_percentage"]) == 45.0


# ---------- API Version verification ----------
class TestApiVersion:
    def test_api_version_2026_01(self):
        """Ensure lightspeed_service uses 2026-01 date-based API version."""
        import sys
        sys.path.insert(0, "/app/backend")
        from lightspeed_service import API_VERSION
        assert API_VERSION == "2026-01"
