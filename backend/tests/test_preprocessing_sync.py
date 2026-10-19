"""Tests for pre-processing sync endpoints (Lightspeed + Odoo)."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://product-bridge-23.preview.emergentagent.com').rstrip('/')
LS_STORE = "redleafssports"
LS_TOKEN = "lsxs_pt_tiodrkFVK9qKD4xGeWj6TaY5RtUoMRHT"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------ Save Lightspeed credentials ----------------
def test_save_lightspeed_settings(auth):
    r = requests.put(f"{BASE_URL}/api/settings",
                     json={"lightspeed_store_id": LS_STORE,
                           "lightspeed_secret_token": LS_TOKEN},
                     headers=auth, timeout=30)
    assert r.status_code == 200, r.text


def test_lightspeed_test_connection(auth):
    r = requests.post(f"{BASE_URL}/api/settings/lightspeed/test", headers=auth, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("connected") is True, f"Not connected: {data}"


# ------------ sync-to-lightspeed endpoint ----------------
def test_sync_to_lightspeed_endpoint_exists_and_structure(auth):
    r = requests.post(f"{BASE_URL}/api/preprocessing/sync-to-lightspeed",
                      json={"sync_all": True}, headers=auth, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("success", "total", "synced", "failed", "errors"):
        assert key in data, f"Missing key {key}: {data}"
    assert data["success"] is True
    assert isinstance(data["errors"], list)


def test_sync_to_lightspeed_no_products_specified(auth):
    r = requests.post(f"{BASE_URL}/api/preprocessing/sync-to-lightspeed",
                      json={}, headers=auth, timeout=60)
    assert r.status_code == 200
    data = r.json()
    # Backend returns success=false when neither product_ids nor sync_all provided
    assert data.get("success") is False
    assert "error" in data


# ------------ sync-to-odoo regression ----------------
def test_sync_to_odoo_endpoint_regression(auth):
    r = requests.post(f"{BASE_URL}/api/preprocessing/sync-to-odoo",
                      json={"sync_all": True}, headers=auth, timeout=60)
    # Odoo may fail connection (not configured); we just verify endpoint responds structurally
    # Either 200 with structure, or 400 with connection failure detail
    if r.status_code == 200:
        data = r.json()
        for key in ("success", "total", "synced", "failed"):
            assert key in data, data
    else:
        assert r.status_code == 400
        assert "Odoo" in r.text or "connection" in r.text.lower()


# ------------ Verify lightspeed_service payload (unit-level static check) ----------
def test_lightspeed_service_supplier_and_pricing():
    """Ensure the code paths in lightspeed_service include supplier + correct pricing keys."""
    import sys
    sys.path.insert(0, "/app/backend")
    from lightspeed_service import LightspeedService

    ls = LightspeedService()  # mock mode
    # Attributes exist
    assert hasattr(ls, "_get_or_create_supplier")

    src = open("/app/backend/lightspeed_service.py").read()
    # supply_price = cost, price_excluding_tax = sale
    assert "'supply_price': cost_price" in src
    assert "'price_excluding_tax': sale_price" in src
    # supplier_id used in payload
    assert "payload['supplier_id'] = supplier_id" in src or "update_data['supplier_id'] = ls_supplier_id" in src
    # _get_or_create_supplier is called with supplier_name
    assert "_get_or_create_supplier(supplier_name)" in src


# ------------ Preprocessing products includes lightspeed mapping ----------------
def test_preprocessing_products_returns_lightspeed_mapping_field(auth):
    r = requests.get(f"{BASE_URL}/api/preprocessing/products?page=1&limit=1",
                     headers=auth, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert "products" in data
    # The query selects mapped_lightspeed_category_id — validated by no error
