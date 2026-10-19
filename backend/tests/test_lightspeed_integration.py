"""
Test suite for Lightspeed eCom integration features.
Tests new endpoints and functionality added for multi-platform export.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://product-bridge-23.preview.emergentagent.com').rstrip('/')

class TestLightspeedIntegration:
    """Test Lightspeed eCom integration endpoints and features."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json().get("token")
        assert token, "No token returned from login"
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        
        self.session.close()
    
    # ==================== SETTINGS TESTS ====================
    
    def test_settings_contains_lightspeed_fields(self):
        """GET /api/settings should return Lightspeed configuration fields."""
        response = self.session.get(f"{BASE_URL}/api/settings")
        assert response.status_code == 200, f"Settings fetch failed: {response.text}"
        
        data = response.json()
        # Verify Lightspeed fields exist
        assert "lightspeed_api_key" in data, "Missing lightspeed_api_key field"
        assert "lightspeed_cluster" in data, "Missing lightspeed_cluster field"
        assert "lightspeed_language" in data, "Missing lightspeed_language field"
        # lightspeed_api_secret should be masked or empty
        assert "lightspeed_api_secret" in data or data.get("lightspeed_api_secret") == "***", "Missing lightspeed_api_secret field"
        
        print(f"✓ Settings contains Lightspeed fields: cluster={data.get('lightspeed_cluster')}, language={data.get('lightspeed_language')}")
    
    def test_save_lightspeed_settings(self):
        """PUT /api/settings should save Lightspeed credentials."""
        # Save Lightspeed settings
        response = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_api_key": "test_api_key_123",
            "lightspeed_api_secret": "test_secret_456",
            "lightspeed_cluster": "eu1",
            "lightspeed_language": "nl"
        })
        assert response.status_code == 200, f"Save settings failed: {response.text}"
        
        # Verify settings were saved
        get_response = self.session.get(f"{BASE_URL}/api/settings")
        assert get_response.status_code == 200
        data = get_response.json()
        
        assert data.get("lightspeed_api_key") == "test_api_key_123", "API key not saved"
        assert data.get("lightspeed_cluster") == "eu1", "Cluster not saved"
        assert data.get("lightspeed_language") == "nl", "Language not saved"
        # Secret should be masked
        assert data.get("lightspeed_api_secret") == "***", "Secret should be masked"
        
        print("✓ Lightspeed settings saved and retrieved correctly")
        
        # Reset to defaults
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_api_key": "",
            "lightspeed_api_secret": "",
            "lightspeed_cluster": "us1",
            "lightspeed_language": "en"
        })
    
    def test_lightspeed_connection_test_mock_mode(self):
        """POST /api/settings/lightspeed/test should return mock mode message when not configured."""
        # First ensure credentials are empty
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_api_key": "",
            "lightspeed_api_secret": "",
            "lightspeed_cluster": "us1",
            "lightspeed_language": "en"
        })
        
        response = self.session.post(f"{BASE_URL}/api/settings/lightspeed/test")
        assert response.status_code == 200, f"Test connection failed: {response.text}"
        
        data = response.json()
        assert data.get("mock_mode") == True, "Should be in mock mode"
        assert data.get("connected") == False, "Should not be connected in mock mode"
        assert "not configured" in data.get("message", "").lower(), f"Expected 'not configured' message, got: {data.get('message')}"
        
        print(f"✓ Lightspeed test connection returns mock mode: {data.get('message')}")
    
    # ==================== CATEGORIES TESTS ====================
    
    def test_get_lightspeed_categories_mock_mode(self):
        """GET /api/categories/lightspeed should return error when not configured."""
        response = self.session.get(f"{BASE_URL}/api/categories/lightspeed")
        assert response.status_code == 200, f"Get categories failed: {response.text}"
        
        data = response.json()
        assert data.get("success") == False, "Should fail when not configured"
        assert "not configured" in data.get("error", "").lower() or len(data.get("categories", [])) == 0, \
            f"Expected 'not configured' error or empty categories, got: {data}"
        
        print(f"✓ Lightspeed categories returns expected response in mock mode")
    
    # ==================== DASHBOARD STATS TESTS ====================
    
    def test_dashboard_stats_includes_lightspeed_count(self):
        """GET /api/dashboard/stats should include selected_for_lightspeed count."""
        response = self.session.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200, f"Dashboard stats failed: {response.text}"
        
        data = response.json()
        assert "selected_for_lightspeed" in data, "Missing selected_for_lightspeed field in dashboard stats"
        assert isinstance(data["selected_for_lightspeed"], int), "selected_for_lightspeed should be an integer"
        
        print(f"✓ Dashboard stats includes selected_for_lightspeed: {data['selected_for_lightspeed']}")
    
    # ==================== PRODUCT SELECTION TESTS ====================
    
    def test_product_lightspeed_selection_endpoint_exists(self):
        """POST /api/products/{id}/select-for-lightspeed endpoint should exist."""
        # Use a fake product ID - should return 404 (not found) not 405 (method not allowed)
        response = self.session.post(f"{BASE_URL}/api/products/fake-product-id/select-for-lightspeed", json={
            "product_id": "fake-product-id",
            "selected": True
        })
        # 404 means endpoint exists but product not found
        # 405 would mean endpoint doesn't exist
        assert response.status_code in [404, 200], f"Endpoint should exist, got: {response.status_code}"
        
        print("✓ POST /api/products/{id}/select-for-lightspeed endpoint exists")
    
    def test_bulk_select_lightspeed_endpoint_exists(self):
        """POST /api/products/bulk-select-lightspeed endpoint should exist."""
        response = self.session.post(f"{BASE_URL}/api/products/bulk-select-lightspeed", json={
            "product_ids": [],
            "selected": True
        })
        # Should return 200 even with empty list
        assert response.status_code == 200, f"Bulk select endpoint failed: {response.text}"
        
        print("✓ POST /api/products/bulk-select-lightspeed endpoint works")
    
    # ==================== SYNC TESTS ====================
    
    def test_lightspeed_sync_endpoint_exists(self):
        """POST /api/sync/lightspeed/{supplier_id} endpoint should exist."""
        # Use a fake supplier ID - should return 404 (not found) not 405 (method not allowed)
        response = self.session.post(f"{BASE_URL}/api/sync/lightspeed/fake-supplier-id")
        # 404 means endpoint exists but supplier not found
        assert response.status_code == 404, f"Expected 404 for fake supplier, got: {response.status_code}"
        
        print("✓ POST /api/sync/lightspeed/{supplier_id} endpoint exists")
    
    def test_sync_logs_filter_includes_lightspeed_push(self):
        """GET /api/sync/logs should support lightspeed_push filter."""
        response = self.session.get(f"{BASE_URL}/api/sync/logs", params={
            "sync_type": "lightspeed_push",
            "limit": 10
        })
        assert response.status_code == 200, f"Sync logs filter failed: {response.text}"
        
        data = response.json()
        assert "logs" in data, "Response should contain logs array"
        # All returned logs should be lightspeed_push type (or empty if none exist)
        for log in data.get("logs", []):
            assert log.get("sync_type") == "lightspeed_push", f"Log type mismatch: {log.get('sync_type')}"
        
        print(f"✓ Sync logs filter for lightspeed_push works, found {len(data.get('logs', []))} logs")
    
    # ==================== CATEGORY MAPPING TESTS ====================
    
    def test_category_mapping_supports_lightspeed(self):
        """POST /api/category-mappings should support lightspeed_category_id."""
        # Create a test mapping with lightspeed_category_id
        response = self.session.post(f"{BASE_URL}/api/category-mappings", json={
            "supplier_category_name": "TEST_Category_Lightspeed",
            "lightspeed_category_id": 12345
        })
        assert response.status_code == 200, f"Create mapping failed: {response.text}"
        
        # Verify mapping was created
        get_response = self.session.get(f"{BASE_URL}/api/category-mappings")
        assert get_response.status_code == 200
        
        mappings = get_response.json().get("mappings", [])
        test_mapping = next((m for m in mappings if m.get("supplier_category_name") == "TEST_Category_Lightspeed"), None)
        
        assert test_mapping is not None, "Test mapping not found"
        assert test_mapping.get("lightspeed_category_id") == 12345, f"Lightspeed category ID not saved: {test_mapping}"
        
        print("✓ Category mapping supports lightspeed_category_id")
        
        # Cleanup - update to remove the test mapping
        self.session.post(f"{BASE_URL}/api/category-mappings", json={
            "supplier_category_name": "TEST_Category_Lightspeed",
            "lightspeed_category_id": None
        })


class TestSupplierAndProductSetup:
    """Test creating supplier and syncing products for Lightspeed toggle testing."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        
        self.session.close()
    
    def test_create_supplier_for_testing(self):
        """Create a test supplier with sandbox credentials."""
        # Check if supplier already exists
        suppliers_response = self.session.get(f"{BASE_URL}/api/suppliers")
        assert suppliers_response.status_code == 200
        
        suppliers = suppliers_response.json().get("suppliers", [])
        existing = next((s for s in suppliers if s.get("supplier_name") == "ATC Sandbox"), None)
        
        if existing:
            print(f"✓ Supplier 'ATC Sandbox' already exists with ID: {existing['id']}")
            return
        
        # Create new supplier with sandbox credentials
        response = self.session.post(f"{BASE_URL}/api/suppliers", json={
            "supplier_name": "ATC Sandbox",
            "api_base_url": "https://edi.atc-apparel.com",
            "account_number": "sandbox",
            "password": "sandbox123",
            "endpoint_style": "atc"
        })
        assert response.status_code == 200, f"Create supplier failed: {response.text}"
        
        data = response.json()
        assert "id" in data, "No supplier ID returned"
        
        print(f"✓ Created supplier 'ATC Sandbox' with ID: {data['id']}")


class TestLightspeedServiceMock:
    """Test LightspeedService mock mode behavior."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert login_response.status_code == 200
        token = login_response.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        
        self.session.close()
    
    def test_lightspeed_service_mock_mode_message(self):
        """Verify Lightspeed service returns proper mock mode message."""
        # Ensure credentials are cleared
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_api_key": "",
            "lightspeed_api_secret": ""
        })
        
        response = self.session.post(f"{BASE_URL}/api/settings/lightspeed/test")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("mock_mode") == True
        assert "Set API Key, Secret, and Cluster in Settings" in data.get("message", "")
        
        print(f"✓ Mock mode message is correct: {data.get('message')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
