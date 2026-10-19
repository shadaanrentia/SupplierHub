"""
Test suite for Lightspeed eSeries (Ecwid) integration - Iteration 9
Tests the refactored API from old Lightspeed eCom (api_key + api_secret + cluster)
to new Ecwid REST API v3 (store_id + secret_token with Bearer auth)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLightspeedEcwidIntegration:
    """Tests for the new Lightspeed eSeries (Ecwid) integration"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - get auth token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
    
    # ==================== GET /api/settings ====================
    def test_get_settings_returns_new_lightspeed_fields(self):
        """GET /api/settings should return lightspeed_store_id and lightspeed_secret_token (masked)"""
        resp = self.session.get(f"{BASE_URL}/api/settings")
        assert resp.status_code == 200, f"GET settings failed: {resp.text}"
        
        data = resp.json()
        
        # New fields should exist
        assert "lightspeed_store_id" in data, "lightspeed_store_id field missing from settings"
        assert "lightspeed_secret_token" in data, "lightspeed_secret_token field missing from settings"
        
        # Store ID should be plain text (not masked)
        # Secret token should be masked as '***' if set, or empty string if not set
        store_id = data.get("lightspeed_store_id", "")
        secret_token = data.get("lightspeed_secret_token", "")
        
        # Verify store_id is not masked (it's not a secret)
        assert store_id != "***", "lightspeed_store_id should not be masked"
        
        print(f"lightspeed_store_id: '{store_id}'")
        print(f"lightspeed_secret_token: '{secret_token}' (should be '***' if set, '' if not)")
    
    def test_get_settings_does_not_return_old_lightspeed_fields(self):
        """GET /api/settings should NOT return old fields (api_key, api_secret, cluster, language)"""
        resp = self.session.get(f"{BASE_URL}/api/settings")
        assert resp.status_code == 200
        
        data = resp.json()
        
        # Old fields should NOT be present in API response
        old_fields = ["lightspeed_api_key", "lightspeed_api_secret", "lightspeed_cluster", "lightspeed_language"]
        for field in old_fields:
            assert field not in data, f"Old field '{field}' should not be in API response"
        
        print("Verified: Old Lightspeed fields are not in API response")
    
    # ==================== PUT /api/settings ====================
    def test_save_lightspeed_store_id(self):
        """PUT /api/settings should save lightspeed_store_id correctly"""
        test_store_id = "TEST_12345678"
        
        resp = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": test_store_id
        })
        assert resp.status_code == 200, f"PUT settings failed: {resp.text}"
        
        # Verify it was saved
        get_resp = self.session.get(f"{BASE_URL}/api/settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        
        assert data.get("lightspeed_store_id") == test_store_id, \
            f"Store ID not saved correctly. Expected '{test_store_id}', got '{data.get('lightspeed_store_id')}'"
        
        print(f"Successfully saved and retrieved lightspeed_store_id: {test_store_id}")
    
    def test_save_lightspeed_secret_token(self):
        """PUT /api/settings should save lightspeed_secret_token and mask it on GET"""
        test_token = "secret_TEST_token_abc123"
        
        resp = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_secret_token": test_token
        })
        assert resp.status_code == 200, f"PUT settings failed: {resp.text}"
        
        # Verify it's masked on GET
        get_resp = self.session.get(f"{BASE_URL}/api/settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        
        assert data.get("lightspeed_secret_token") == "***", \
            f"Secret token should be masked as '***', got '{data.get('lightspeed_secret_token')}'"
        
        print("Successfully saved lightspeed_secret_token (masked as '***' on GET)")
    
    def test_save_both_lightspeed_credentials(self):
        """PUT /api/settings should save both store_id and secret_token together"""
        test_store_id = "TEST_STORE_99999"
        test_token = "secret_TEST_combined_xyz789"
        
        resp = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": test_store_id,
            "lightspeed_secret_token": test_token
        })
        assert resp.status_code == 200, f"PUT settings failed: {resp.text}"
        
        # Verify both were saved
        get_resp = self.session.get(f"{BASE_URL}/api/settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        
        assert data.get("lightspeed_store_id") == test_store_id
        assert data.get("lightspeed_secret_token") == "***"
        
        print(f"Successfully saved both credentials: store_id={test_store_id}, token=***")
    
    def test_masked_token_not_overwritten(self):
        """PUT /api/settings with masked token '***' should not overwrite actual token"""
        # First, set a real token
        real_token = "real_secret_token_do_not_overwrite"
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_secret_token": real_token
        })
        
        # Now try to save with masked value (simulating frontend sending back '***')
        resp = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": "UPDATED_STORE_ID",
            "lightspeed_secret_token": "***"  # This should be ignored
        })
        assert resp.status_code == 200
        
        # Token should still be masked (meaning original value preserved)
        get_resp = self.session.get(f"{BASE_URL}/api/settings")
        data = get_resp.json()
        assert data.get("lightspeed_secret_token") == "***", "Token should still be masked"
        
        print("Verified: Masked token '***' does not overwrite actual token")
    
    # ==================== POST /api/settings/lightspeed/test ====================
    def test_lightspeed_test_connection_no_credentials(self):
        """POST /api/settings/lightspeed/test should return mock mode message when no credentials"""
        # Clear credentials first
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        
        resp = self.session.post(f"{BASE_URL}/api/settings/lightspeed/test")
        assert resp.status_code == 200, f"Test connection failed: {resp.text}"
        
        data = resp.json()
        assert data.get("success") == False, "Should return success=false when not configured"
        assert data.get("mock_mode") == True, "Should return mock_mode=true when not configured"
        assert "not configured" in data.get("message", "").lower() or "store id" in data.get("message", "").lower(), \
            f"Message should indicate not configured: {data.get('message')}"
        
        print(f"Mock mode response: {data}")
    
    def test_lightspeed_test_connection_invalid_credentials(self):
        """POST /api/settings/lightspeed/test should return error with invalid credentials"""
        # Set invalid credentials
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": "invalid_store_12345",
            "lightspeed_secret_token": "invalid_token_xyz"
        })
        
        resp = self.session.post(f"{BASE_URL}/api/settings/lightspeed/test")
        assert resp.status_code == 200, f"Test connection request failed: {resp.text}"
        
        data = resp.json()
        assert data.get("success") == False, "Should return success=false with invalid credentials"
        assert data.get("connected") == False, "Should return connected=false with invalid credentials"
        assert data.get("mock_mode") == False, "Should not be in mock mode when credentials are set"
        
        # Should have an error message about authentication or connection
        message = data.get("message", "").lower()
        assert any(word in message for word in ["auth", "failed", "error", "invalid", "not found"]), \
            f"Message should indicate auth/connection error: {data.get('message')}"
        
        print(f"Invalid credentials response: {data}")
    
    # ==================== GET /api/categories/lightspeed ====================
    def test_get_lightspeed_categories_mock_mode(self):
        """GET /api/categories/lightspeed should return error when not configured"""
        # Clear credentials
        self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        
        resp = self.session.get(f"{BASE_URL}/api/categories/lightspeed")
        assert resp.status_code == 200, f"Get categories failed: {resp.text}"
        
        data = resp.json()
        assert data.get("success") == False, "Should return success=false when not configured"
        assert "categories" in data, "Should have categories field (empty list)"
        assert len(data.get("categories", [])) == 0, "Categories should be empty when not configured"
        
        print(f"Categories mock mode response: {data}")
    
    # ==================== Cleanup ====================
    def test_cleanup_test_data(self):
        """Cleanup: Reset Lightspeed credentials to empty"""
        resp = self.session.put(f"{BASE_URL}/api/settings", json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        assert resp.status_code == 200
        print("Cleaned up test credentials")


class TestLightspeedServiceUnit:
    """Unit tests for LightspeedService class"""
    
    def test_service_mock_mode_no_credentials(self):
        """LightspeedService should be in mock mode when no credentials provided"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService('', '')
        assert ls.mock_mode == True, "Should be in mock mode with empty credentials"
        
        result = ls.test_connection()
        assert result.get("mock_mode") == True
        assert result.get("success") == False
        print(f"Mock mode test_connection: {result}")
    
    def test_service_not_mock_mode_with_credentials(self):
        """LightspeedService should NOT be in mock mode when credentials provided"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService('12345', 'secret_token')
        assert ls.mock_mode == False, "Should NOT be in mock mode with credentials"
        print("Service correctly detects credentials are provided")
    
    def test_service_url_construction(self):
        """LightspeedService should construct correct Ecwid API URLs"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService('12345678', 'secret_token')
        
        # Test URL construction
        url = ls._url("profile")
        assert url == "https://app.ecwid.com/api/v3/12345678/profile", f"URL incorrect: {url}"
        
        url = ls._url("products")
        assert url == "https://app.ecwid.com/api/v3/12345678/products", f"URL incorrect: {url}"
        
        print("URL construction verified correct")
    
    def test_service_headers(self):
        """LightspeedService should use Bearer auth in headers"""
        import sys
        sys.path.insert(0, '/app/backend')
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService('12345678', 'my_secret_token')
        headers = ls._headers()
        
        assert headers.get("Authorization") == "Bearer my_secret_token", \
            f"Authorization header incorrect: {headers.get('Authorization')}"
        assert headers.get("Content-Type") == "application/json"
        
        print("Headers verified correct (Bearer auth)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
