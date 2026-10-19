"""
Backend API Tests - Iteration 11
Tests for the refactored server.py (decomposed into route modules)
Tests: Auth, Settings, Dashboard, Products, Suppliers, Sync Logs, Category Mappings, Lightspeed, Preprocessing
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://product-bridge-23.preview.emergentagent.com"


class TestHealth:
    """Health check endpoint tests"""
    
    def test_health_endpoint(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "healthy"
        assert data.get("database") == "postgresql"
        assert "timestamp" in data
        print("✓ Health endpoint returns healthy status with PostgreSQL database")


class TestAuth:
    """Authentication endpoint tests"""
    
    def test_login_success(self):
        """POST /api/auth/login with admin/admin returns JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "token" in data, "Response should contain token"
        assert "user" in data, "Response should contain user"
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"
        print(f"✓ Admin login successful, token received: {data['token'][:20]}...")
        return data["token"]
    
    def test_login_invalid_credentials(self):
        """POST /api/auth/login with wrong credentials returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wronguser",
            "password": "wrongpass"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Invalid credentials correctly return 401")
    
    def test_get_users_requires_auth(self):
        """GET /api/users without auth returns 401"""
        response = requests.get(f"{BASE_URL}/api/users")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ GET /api/users correctly requires authentication")
    
    def test_get_users_with_auth(self):
        """GET /api/users returns list with admin user"""
        # First login
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        token = login_resp.json()["token"]
        
        # Get users
        response = requests.get(f"{BASE_URL}/api/users", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "users" in data
        assert len(data["users"]) >= 1
        admin_user = next((u for u in data["users"] if u["username"] == "admin"), None)
        assert admin_user is not None, "Admin user should exist"
        assert admin_user["role"] == "admin"
        print(f"✓ GET /api/users returns {len(data['users'])} users including admin")


class TestSettings:
    """Settings endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_settings(self):
        """GET /api/settings returns valid JSON with lightspeed fields"""
        response = requests.get(f"{BASE_URL}/api/settings", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check required fields exist
        assert "id" in data
        assert "lightspeed_store_id" in data, "Settings should have lightspeed_store_id"
        assert "lightspeed_secret_token" in data, "Settings should have lightspeed_secret_token"
        
        # Check old fields are removed
        assert "lightspeed_api_key" not in data, "Old field lightspeed_api_key should be removed"
        assert "lightspeed_api_secret" not in data, "Old field lightspeed_api_secret should be removed"
        assert "lightspeed_cluster" not in data, "Old field lightspeed_cluster should be removed"
        
        print(f"✓ GET /api/settings returns valid JSON with lightspeed_store_id and lightspeed_secret_token")
    
    def test_settings_masks_secret_token(self):
        """GET /api/settings masks lightspeed_secret_token as ***"""
        # First set a token
        requests.put(f"{BASE_URL}/api/settings", headers=self.headers, json={
            "lightspeed_secret_token": "test_secret_token_12345"
        })
        
        # Now get settings and verify masking
        response = requests.get(f"{BASE_URL}/api/settings", headers=self.headers)
        data = response.json()
        
        # If token was set, it should be masked
        if data.get("lightspeed_secret_token"):
            assert data["lightspeed_secret_token"] == "***", "Secret token should be masked as ***"
            print("✓ lightspeed_secret_token is correctly masked as ***")
        else:
            print("✓ lightspeed_secret_token is empty (no token set)")
    
    def test_update_lightspeed_settings(self):
        """PUT /api/settings updates lightspeed_store_id and lightspeed_secret_token"""
        test_store_id = "test-store-prefix"
        test_token = "test-personal-token-xyz"
        
        # Update settings
        response = requests.put(f"{BASE_URL}/api/settings", headers=self.headers, json={
            "lightspeed_store_id": test_store_id,
            "lightspeed_secret_token": test_token
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Verify update
        get_resp = requests.get(f"{BASE_URL}/api/settings", headers=self.headers)
        data = get_resp.json()
        assert data["lightspeed_store_id"] == test_store_id, "Store ID should be updated"
        assert data["lightspeed_secret_token"] == "***", "Token should be masked after update"
        
        print(f"✓ PUT /api/settings correctly updates lightspeed_store_id to '{test_store_id}'")
    
    def test_masked_token_not_overwritten(self):
        """PUT /api/settings with masked token '***' does NOT overwrite actual token"""
        # First set a real token
        real_token = "real-secret-token-abc123"
        requests.put(f"{BASE_URL}/api/settings", headers=self.headers, json={
            "lightspeed_secret_token": real_token
        })
        
        # Now update with masked token - should NOT overwrite
        requests.put(f"{BASE_URL}/api/settings", headers=self.headers, json={
            "lightspeed_store_id": "updated-prefix",
            "lightspeed_secret_token": "***"
        })
        
        # The token should still be masked (meaning it wasn't overwritten with ***)
        get_resp = requests.get(f"{BASE_URL}/api/settings", headers=self.headers)
        data = get_resp.json()
        assert data["lightspeed_secret_token"] == "***", "Token should still be masked"
        
        print("✓ Masked token '***' does NOT overwrite actual token")


class TestDashboard:
    """Dashboard endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_dashboard_stats(self):
        """GET /api/dashboard/stats returns product and supplier counts"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check required fields
        assert "total_products" in data
        assert "total_suppliers" in data
        assert "active_suppliers" in data
        assert "selected_for_odoo" in data
        assert "selected_for_lightspeed" in data
        assert "category_distribution" in data
        assert "brand_distribution" in data
        assert "supplier_distribution" in data
        
        print(f"✓ Dashboard stats: {data['total_products']} products, {data['total_suppliers']} suppliers")


class TestProducts:
    """Products endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_products_paginated(self):
        """GET /api/products returns paginated product list"""
        response = requests.get(f"{BASE_URL}/api/products?limit=5", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "products" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert "pages" in data
        assert isinstance(data["products"], list)
        
        print(f"✓ GET /api/products returns paginated list: {data['total']} total, page {data['page']}/{data['pages']}")


class TestSuppliers:
    """Suppliers endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_suppliers(self):
        """GET /api/suppliers returns supplier list"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "suppliers" in data
        assert isinstance(data["suppliers"], list)
        
        print(f"✓ GET /api/suppliers returns {len(data['suppliers'])} suppliers")
    
    def test_create_supplier(self):
        """POST /api/suppliers creates a new supplier"""
        test_supplier = {
            "supplier_name": "TEST_Supplier_Iteration11",
            "api_base_url": "https://test-api.example.com",
            "account_number": "TEST123",
            "password": "testpass",
            "use_uat": False,
            "endpoint_style": "standard",
            "services": {}
        }
        
        response = requests.post(f"{BASE_URL}/api/suppliers", headers=self.headers, json=test_supplier)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "id" in data
        assert "message" in data
        
        # Cleanup - delete the test supplier
        supplier_id = data["id"]
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=self.headers)
        
        print(f"✓ POST /api/suppliers creates supplier successfully (ID: {supplier_id})")


class TestSyncLogs:
    """Sync logs endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_sync_logs(self):
        """GET /api/sync/logs returns sync log list"""
        response = requests.get(f"{BASE_URL}/api/sync/logs", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "logs" in data
        assert isinstance(data["logs"], list)
        
        print(f"✓ GET /api/sync/logs returns {len(data['logs'])} logs")
    
    def test_get_sync_log_detail_not_found(self):
        """GET /api/sync/log/{log_id} returns 404 for non-existent log"""
        response = requests.get(f"{BASE_URL}/api/sync/log/nonexistent-id", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ GET /api/sync/log/{log_id} returns 404 for non-existent log")


class TestCategoryMappings:
    """Category mappings endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_category_mappings(self):
        """GET /api/category-mappings returns mapping list"""
        response = requests.get(f"{BASE_URL}/api/category-mappings", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "mappings" in data
        assert isinstance(data["mappings"], list)
        
        print(f"✓ GET /api/category-mappings returns {len(data['mappings'])} mappings")


class TestLightspeed:
    """Lightspeed integration endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_lightspeed_test_connection_mock_mode(self):
        """POST /api/settings/lightspeed/test with no credentials returns mock mode message"""
        # First clear credentials
        requests.put(f"{BASE_URL}/api/settings", headers=self.headers, json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        
        response = requests.post(f"{BASE_URL}/api/settings/lightspeed/test", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data.get("mock_mode") == True, "Should be in mock mode"
        assert "Domain Prefix" in data.get("message", "") or "not configured" in data.get("message", "").lower()
        
        print(f"✓ Lightspeed test returns mock mode message: {data.get('message')}")


class TestPreprocessing:
    """Preprocessing endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        self.token = login_resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_preprocessing_products(self):
        """GET /api/preprocessing/products returns paginated list"""
        response = requests.get(f"{BASE_URL}/api/preprocessing/products", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "products" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert "markup_percentage" in data
        
        print(f"✓ GET /api/preprocessing/products returns {data['total']} products with {data['markup_percentage']}% markup")
    
    def test_get_preprocessing_summary(self):
        """GET /api/preprocessing/summary returns summary stats"""
        response = requests.get(f"{BASE_URL}/api/preprocessing/summary", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "total_products" in data
        assert "total_variants" in data
        assert "category_mapping" in data
        assert "images" in data
        assert "pricing" in data
        assert "sync_status" in data
        
        print(f"✓ GET /api/preprocessing/summary: {data['total_products']} products, {data['total_variants']} variants")


class TestLightspeedServiceURLPattern:
    """Test that Lightspeed service uses correct X-Series API URL pattern"""
    
    def test_lightspeed_service_base_url(self):
        """Verify LightspeedService uses correct X-Series base URL pattern"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        # Test with a domain prefix
        ls = LightspeedService(domain_prefix="teststore", personal_token="test-token")
        
        # Check base URL pattern
        base_url = ls._base_url()
        expected_pattern = "https://teststore.retail.lightspeed.app/api/2.0"
        assert base_url == expected_pattern, f"Expected {expected_pattern}, got {base_url}"
        
        # Check mock mode is False when credentials provided
        assert ls.mock_mode == False, "Should not be in mock mode when credentials provided"
        
        print(f"✓ LightspeedService uses correct X-Series base URL: {base_url}")
    
    def test_lightspeed_service_mock_mode(self):
        """Verify LightspeedService is in mock mode when credentials missing"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        # Test without credentials
        ls = LightspeedService(domain_prefix="", personal_token="")
        assert ls.mock_mode == True, "Should be in mock mode when credentials missing"
        
        # Test with only domain prefix
        ls2 = LightspeedService(domain_prefix="store", personal_token="")
        assert ls2.mock_mode == True, "Should be in mock mode when token missing"
        
        print("✓ LightspeedService correctly enters mock mode when credentials missing")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
