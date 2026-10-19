"""Iteration 15: Supplier CRUD + Lightspeed regression after PG fix."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
LS_STORE = "redleafssports"
LS_TOKEN = "lsxs_pt_tiodrkFVK9qKD4xGeWj6TaY5RtUoMRHT"


@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"username": "admin", "password": "admin"}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"no token in {r.json()}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def created_supplier(auth_headers):
    payload = {
        "supplier_name": f"TEST_Iter15_{uuid.uuid4().hex[:8]}",
        "api_base_url": "https://example.com",
        "account_number": "ACC-1",
        "password": "pw",
        "endpoint_style": "custom",
    }
    r = requests.post(f"{BASE_URL}/api/suppliers", json=payload, headers=auth_headers, timeout=20)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    data = r.json()
    assert "id" in data
    assert "message" in data
    yield {"id": data["id"], "payload": payload}
    # cleanup
    requests.delete(f"{BASE_URL}/api/suppliers/{data['id']}", headers=auth_headers)


class TestSupplierCRUD:
    def test_create_and_list_contains_it(self, auth_headers, created_supplier):
        r = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        ids = [s["id"] for s in r.json().get("suppliers", [])]
        assert created_supplier["id"] in ids

    def test_get_by_id(self, auth_headers, created_supplier):
        r = requests.get(f"{BASE_URL}/api/suppliers/{created_supplier['id']}",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["supplier_name"] == created_supplier["payload"]["supplier_name"]

    def test_update_supplier(self, auth_headers, created_supplier):
        new_name = f"TEST_Iter15_Upd_{uuid.uuid4().hex[:6]}"
        r = requests.put(f"{BASE_URL}/api/suppliers/{created_supplier['id']}",
                         json={"supplier_name": new_name}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        # verify persisted
        g = requests.get(f"{BASE_URL}/api/suppliers/{created_supplier['id']}",
                         headers=auth_headers, timeout=15)
        assert g.status_code == 200
        assert g.json()["supplier_name"] == new_name

    def test_delete_supplier(self, auth_headers):
        # dedicated create+delete flow (not using the module fixture)
        payload = {"supplier_name": f"TEST_Del_{uuid.uuid4().hex[:8]}",
                   "endpoint_style": "custom"}
        c = requests.post(f"{BASE_URL}/api/suppliers", json=payload,
                          headers=auth_headers, timeout=15)
        assert c.status_code == 200
        sid = c.json()["id"]
        d = requests.delete(f"{BASE_URL}/api/suppliers/{sid}",
                            headers=auth_headers, timeout=15)
        assert d.status_code == 200
        assert d.json().get("status") == "deleted"
        g = requests.get(f"{BASE_URL}/api/suppliers/{sid}",
                         headers=auth_headers, timeout=15)
        assert g.status_code == 404


class TestLightspeedRegression:
    def test_save_and_test_connection(self, auth_headers):
        # save credentials
        r = requests.put(f"{BASE_URL}/api/settings",
                         json={"lightspeed_store_id": LS_STORE,
                               "lightspeed_secret_token": LS_TOKEN},
                         headers=auth_headers, timeout=20)
        assert r.status_code in (200, 204), f"settings save failed: {r.status_code} {r.text}"

        t = requests.post(f"{BASE_URL}/api/settings/lightspeed/test",
                          headers=auth_headers, timeout=30)
        assert t.status_code == 200, f"{t.status_code} {t.text}"
        assert t.json().get("connected") is True, f"connected!=true: {t.json()}"

    def test_categories(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/categories/lightspeed",
                         headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        cats = data.get("categories") if isinstance(data, dict) else data
        assert isinstance(cats, list)
        assert len(cats) >= 50, f"only got {len(cats)} categories"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
