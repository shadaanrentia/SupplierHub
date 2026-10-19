"""Iteration 14 - Live Lightspeed connection tests with real Personal Token."""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv('/app/frontend/.env')
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

DOMAIN = "redleafssports"
PERSONAL_TOKEN = "lsxs_pt_tiodrkFVK9qKD4xGeWj6TaY5RtUoMRHT"
CLIENT_ID = "public_ycmUEk1yjqgUZYzeGFCwGNxVmMDe9Wgw"
CLIENT_SECRET = "secret_7LFgEv69Z2ZUmRxaKNduSeMUmQVzkw1e"


@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("token") or r.json().get("access_token")
    assert token, f"No token: {r.json()}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def setup_credentials(auth_headers):
    """Save all Lightspeed credentials before tests run."""
    payload = {
        "lightspeed_store_id": DOMAIN,
        "lightspeed_secret_token": PERSONAL_TOKEN,
        "lightspeed_client_id": CLIENT_ID,
        "lightspeed_client_secret": CLIENT_SECRET,
    }
    r = requests.put(f"{BASE_URL}/api/settings", json=payload, headers=auth_headers, timeout=15)
    assert r.status_code == 200, f"Settings save failed: {r.status_code} {r.text}"


def test_api_version_is_2026_07():
    import sys
    sys.path.insert(0, '/app/backend')
    from lightspeed_service import API_VERSION
    assert API_VERSION == "2026-07", f"API_VERSION is {API_VERSION}, expected 2026-07"


def test_settings_persisted(auth_headers):
    r = requests.get(f"{BASE_URL}/api/settings", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data.get("lightspeed_store_id") == DOMAIN
    assert data.get("lightspeed_client_id") == CLIENT_ID
    # Personal token should be present (may be masked)
    assert data.get("lightspeed_secret_token"), "Personal token missing"


def test_lightspeed_test_connection_live(auth_headers):
    """POST /api/settings/lightspeed/test should return connected=true."""
    r = requests.post(f"{BASE_URL}/api/settings/lightspeed/test",
                      headers=auth_headers, timeout=60)
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    print(f"Test connection response: {data}")
    assert data.get("connected") is True, f"Not connected: {data}"
    assert data.get("success") is True
    assert DOMAIN in data.get("message", "")


def test_lightspeed_categories_live(auth_headers):
    """GET /api/categories/lightspeed should return 50+ real categories with correct structure."""
    r = requests.get(f"{BASE_URL}/api/categories/lightspeed",
                     headers=auth_headers, timeout=120)
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("success") is True, f"Failed: {data}"
    categories = data.get("categories", [])
    print(f"Categories fetched: {len(categories)}")
    if categories:
        print(f"Sample category: {categories[0]}")
    assert len(categories) >= 50, f"Expected 50+ categories, got {len(categories)}"

    # Verify structure of first category
    c = categories[0]
    required_keys = {"lightspeed_category_id", "category_name", "parent_id",
                     "leaf_category", "category_path"}
    missing = required_keys - set(c.keys())
    assert not missing, f"Missing keys: {missing} in {c}"
    assert c["lightspeed_category_id"], "Missing category id"
    assert c["category_name"], "Missing category name"


def test_lightspeed_oauth_authorize_returns_valid_url(auth_headers):
    r = requests.get(f"{BASE_URL}/api/lightspeed/oauth/authorize",
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    url = data.get("authorize_url", "")
    assert "secure.retail.lightspeed.app/connect" in url
    assert f"client_id={CLIENT_ID}" in url
    assert "state=" in url
    assert "response_type=code" in url


def test_lightspeed_oauth_disconnect(auth_headers):
    r = requests.post(f"{BASE_URL}/api/lightspeed/oauth/disconnect",
                      headers=auth_headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert data.get("status") == "disconnected"
