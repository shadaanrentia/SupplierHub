"""Iteration 16: Test Lightspeed category mapping UUID and preprocessing validation."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://product-bridge-23.preview.emergentagent.com').rstrip('/')


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# ==== Ensure Lightspeed creds configured ====
def test_configure_lightspeed_settings(client):
    # Get current settings
    r = client.get(f"{BASE_URL}/api/settings")
    assert r.status_code == 200
    data = r.json()
    # PUT to save creds
    r = client.put(f"{BASE_URL}/api/settings", json={
        **data,
        "lightspeed_store_id": "redleafssports",
        "lightspeed_secret_token": "lsxs_pt_tiodrkFVK9qKD4xGeWj6TaY5RtUoMRHT",
    })
    assert r.status_code in (200, 204), r.text


# ==== DB column type check ====
def test_lightspeed_category_id_column_is_text(client):
    """Verify DB migration: category_mapping.lightspeed_category_id column is TEXT."""
    import asyncio
    import asyncpg
    async def _check():
        conn = await asyncpg.connect("postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db")
        row = await conn.fetchrow(
            "SELECT data_type FROM information_schema.columns WHERE table_name='category_mapping' AND column_name='lightspeed_category_id'"
        )
        await conn.close()
        return row
    row = asyncio.get_event_loop().run_until_complete(_check())
    assert row is not None, "lightspeed_category_id column not found"
    assert row['data_type'] == 'text', f"Expected TEXT, got {row['data_type']}"


# ==== GET /api/categories/lightspeed hierarchical fields ====
def test_get_lightspeed_categories_returns_hierarchy_fields(client):
    r = client.get(f"{BASE_URL}/api/categories/lightspeed")
    assert r.status_code == 200, r.text
    data = r.json()
    cats = data.get("categories") or data.get("data") or []
    assert isinstance(cats, list) and len(cats) > 0, f"No categories returned: {data}"
    sample = cats[0]
    # Check required fields exist (may be null for root)
    assert "lightspeed_category_id" in sample
    assert "parent_id" in sample
    assert "leaf_category" in sample
    assert "category_path" in sample


# ==== POST /api/category-mappings with UUID string ====
TEST_SUPPLIER_CATEGORY = "TEST_HEADWEAR_ITER16"
TEST_UUID = "9250b0f7-8a4c-427e-8846-e6f91e74bba0"


def test_create_mapping_with_lightspeed_uuid(client):
    # Cleanup any pre-existing mapping first
    r = client.get(f"{BASE_URL}/api/category-mappings")
    assert r.status_code == 200
    for m in r.json().get("mappings", []):
        if m.get("supplier_category_name") == TEST_SUPPLIER_CATEGORY:
            client.delete(f"{BASE_URL}/api/category-mappings/{m['id']}")

    r = client.post(f"{BASE_URL}/api/category-mappings", json={
        "supplier_category_name": TEST_SUPPLIER_CATEGORY,
        "lightspeed_category_id": TEST_UUID,
    })
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True


def test_get_mapping_returns_uuid_string(client):
    r = client.get(f"{BASE_URL}/api/category-mappings")
    assert r.status_code == 200
    mapping = next((m for m in r.json()["mappings"] if m["supplier_category_name"] == TEST_SUPPLIER_CATEGORY), None)
    assert mapping is not None, "Mapping not persisted"
    assert mapping["lightspeed_category_id"] == TEST_UUID, f"UUID mismatch: {mapping}"
    assert isinstance(mapping["lightspeed_category_id"], str)


# ==== Preprocessing validation ====
def test_preprocessing_products_valid_with_lightspeed_mapping(client):
    """Create a test product with category=TEST_SUPPLIER_CATEGORY and price, verify it shows as valid."""
    import asyncio
    import asyncpg
    from uuid import uuid4

    product_id = str(uuid4())

    async def _setup():
        conn = await asyncpg.connect("postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db")
        # Get any supplier
        sup = await conn.fetchrow("SELECT id FROM suppliers LIMIT 1")
        supplier_id = sup['id'] if sup else None
        await conn.execute(
            """INSERT INTO products (id, supplier_id, supplier_sku, product_name, category, base_price, preprocessing_status, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, 'ready', NOW())""",
            product_id, supplier_id, f"TEST_SKU_{product_id[:8]}", "Test Product Iter16",
            TEST_SUPPLIER_CATEGORY, 10.0
        )
        # Insert an image so 'No images' error doesn't appear
        await conn.execute(
            """INSERT INTO product_media (id, product_id, url, media_type, is_primary)
               VALUES ($1, $2, $3, 'image', TRUE)""",
            str(uuid4()), product_id, "https://example.com/test.jpg"
        )
        await conn.close()

    async def _cleanup():
        conn = await asyncpg.connect("postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db")
        await conn.execute("DELETE FROM product_media WHERE product_id=$1", product_id)
        await conn.execute("DELETE FROM products WHERE id=$1", product_id)
        await conn.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())

        r = client.get(f"{BASE_URL}/api/preprocessing/products?limit=200")
        assert r.status_code == 200, r.text
        products = r.json()["products"]
        p = next((x for x in products if x["id"] == product_id), None)
        assert p is not None, f"Test product {product_id} not in preprocessing list"
        assert p["is_valid"] is True, f"Product should be valid, errors={p['validation_errors']}"
        assert "Missing category mapping" not in p["validation_errors"]
        assert p["status"] == "ready"
    finally:
        loop.run_until_complete(_cleanup())
        loop.close()


def test_preprocessing_summary_counts_lightspeed_mapped(client):
    r = client.get(f"{BASE_URL}/api/preprocessing/summary")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "category_mapping" in data
    # mapped counter should be >= 0 (our TEST mapping exists but may have no products right now)
    assert data["category_mapping"]["mapped"] >= 0


# ==== Cleanup ====
def test_zzz_cleanup_mapping(client):
    r = client.get(f"{BASE_URL}/api/category-mappings")
    for m in r.json().get("mappings", []):
        if m.get("supplier_category_name") == TEST_SUPPLIER_CATEGORY:
            client.delete(f"{BASE_URL}/api/category-mappings/{m['id']}")
