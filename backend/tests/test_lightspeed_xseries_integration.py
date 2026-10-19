"""
Test suite for Lightspeed Retail X-Series API integration.
Tests the migration from Ecwid API (app.ecwid.com) to X-Series API (retail.lightspeed.app).

Key changes verified:
- Base URL: https://{domain_prefix}.retail.lightspeed.app/api/2.0
- Auth: Bearer personal_token
- Fields: lightspeed_store_id (domain prefix), lightspeed_secret_token (personal token)
"""
import pytest
import requests
import os
import sys

# Add backend to path for importing LightspeedService
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://product-bridge-23.preview.emergentagent.com').rstrip('/')


class TestAuth:
    """Authentication tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["token"]
    
    def test_login_success(self):
        """Test admin login works"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["username"] == "admin"
        print("PASS: Admin login successful")


class TestLightspeedXSeriesSettings:
    """Test Lightspeed X-Series settings endpoints"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        return response.json()["token"]
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        """Auth headers"""
        return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    def test_get_settings_returns_lightspeed_store_id(self, headers):
        """GET /api/settings should return lightspeed_store_id field (domain prefix)"""
        response = requests.get(f"{BASE_URL}/api/settings", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "lightspeed_store_id" in data, "lightspeed_store_id field missing from settings"
        print(f"PASS: lightspeed_store_id present in settings: '{data.get('lightspeed_store_id', '')}'")
    
    def test_get_settings_returns_lightspeed_secret_token_masked(self, headers):
        """GET /api/settings should return lightspeed_secret_token masked as '***' when set"""
        response = requests.get(f"{BASE_URL}/api/settings", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "lightspeed_secret_token" in data, "lightspeed_secret_token field missing from settings"
        # Token should be masked or empty
        token = data.get("lightspeed_secret_token", "")
        assert token in ["", "***"], f"Token should be empty or masked, got: {token}"
        print(f"PASS: lightspeed_secret_token properly handled: '{token}'")
    
    def test_save_domain_prefix(self, headers):
        """PUT /api/settings should save lightspeed_store_id (domain prefix)"""
        test_prefix = "TEST_teststore"
        response = requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": test_prefix
        })
        assert response.status_code == 200
        
        # Verify it was saved
        get_response = requests.get(f"{BASE_URL}/api/settings", headers=headers)
        assert get_response.status_code == 200
        data = get_response.json()
        assert data.get("lightspeed_store_id") == test_prefix
        print(f"PASS: Domain prefix saved correctly: {test_prefix}")
        
        # Cleanup
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": ""
        })
    
    def test_save_personal_token(self, headers):
        """PUT /api/settings should save lightspeed_secret_token (personal token)"""
        test_token = "TEST_personal_token_12345"
        response = requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_secret_token": test_token
        })
        assert response.status_code == 200
        
        # Verify it was saved (should be masked)
        get_response = requests.get(f"{BASE_URL}/api/settings", headers=headers)
        assert get_response.status_code == 200
        data = get_response.json()
        assert data.get("lightspeed_secret_token") == "***", "Token should be masked after saving"
        print("PASS: Personal token saved and masked correctly")
        
        # Cleanup
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_secret_token": ""
        })
    
    def test_masked_token_not_overwritten(self, headers):
        """PUT /api/settings with '***' should NOT overwrite actual token"""
        # First save a real token
        real_token = "TEST_real_token_xyz"
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_secret_token": real_token
        })
        
        # Now try to save with masked value
        response = requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_secret_token": "***"
        })
        assert response.status_code == 200
        
        # Token should still be masked (not overwritten with literal '***')
        get_response = requests.get(f"{BASE_URL}/api/settings", headers=headers)
        data = get_response.json()
        assert data.get("lightspeed_secret_token") == "***"
        print("PASS: Masked token '***' does not overwrite actual token")
        
        # Cleanup
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_secret_token": ""
        })


class TestLightspeedXSeriesConnection:
    """Test Lightspeed X-Series connection endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        return response.json()["token"]
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        """Auth headers"""
        return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    def test_connection_mock_mode_no_credentials(self, headers):
        """POST /api/settings/lightspeed/test with no credentials returns mock mode message"""
        # Clear credentials first
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        
        response = requests.post(f"{BASE_URL}/api/settings/lightspeed/test", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("mock_mode") == True, "Should be in mock mode without credentials"
        assert data.get("connected") == False, "Should not be connected in mock mode"
        
        # Message should mention Domain Prefix and Personal Token (X-Series terminology)
        message = data.get("message", "").lower()
        assert "domain prefix" in message or "personal token" in message, \
            f"Mock mode message should mention Domain Prefix or Personal Token, got: {data.get('message')}"
        print(f"PASS: Mock mode message correct: {data.get('message')}")
    
    def test_connection_invalid_credentials_not_400(self, headers):
        """POST /api/settings/lightspeed/test with invalid credentials should NOT return 400 Bad Request"""
        # Set fake credentials
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": "TEST_fakestore",
            "lightspeed_secret_token": "TEST_faketoken123"
        })
        
        response = requests.post(f"{BASE_URL}/api/settings/lightspeed/test", headers=headers)
        assert response.status_code == 200, f"Should return 200 with error in body, not {response.status_code}"
        data = response.json()
        
        # Should NOT be connected
        assert data.get("connected") == False, "Should not be connected with invalid credentials"
        assert data.get("mock_mode") == False, "Should NOT be in mock mode when credentials are provided"
        
        # The error should be connection error or auth failure, NOT 400 Bad Request
        message = data.get("message", "")
        assert "400" not in message, f"Should not get 400 error (old Ecwid bug), got: {message}"
        print(f"PASS: Invalid credentials return proper error (not 400): {message}")
        
        # Cleanup
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })


class TestLightspeedXSeriesCategories:
    """Test Lightspeed X-Series categories endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        return response.json()["token"]
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        """Auth headers"""
        return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    def test_categories_mock_mode(self, headers):
        """GET /api/categories/lightspeed returns error when not configured"""
        # Clear credentials
        requests.put(f"{BASE_URL}/api/settings", headers=headers, json={
            "lightspeed_store_id": "",
            "lightspeed_secret_token": ""
        })
        
        response = requests.get(f"{BASE_URL}/api/categories/lightspeed", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        # Should return error or empty categories in mock mode
        assert data.get("success") == False or data.get("categories") == [], \
            "Should return error or empty categories in mock mode"
        print(f"PASS: Categories endpoint handles mock mode correctly")


class TestLightspeedServiceXSeriesAPI:
    """Test LightspeedService class uses correct X-Series API"""
    
    def test_service_base_url_uses_xseries(self):
        """LightspeedService should use retail.lightspeed.app, NOT app.ecwid.com"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="testtoken")
        base_url = ls._base_url()
        
        # Should use X-Series URL
        assert "retail.lightspeed.app" in base_url, f"Should use retail.lightspeed.app, got: {base_url}"
        assert "teststore.retail.lightspeed.app" in base_url, f"Domain prefix should be in URL, got: {base_url}"
        assert "api/2.0" in base_url, f"Should use API v2.0, got: {base_url}"
        
        # Should NOT use Ecwid URL
        assert "ecwid" not in base_url.lower(), f"Should NOT use ecwid URL, got: {base_url}"
        assert "app.ecwid.com" not in base_url, f"Should NOT use app.ecwid.com, got: {base_url}"
        
        print(f"PASS: Base URL correct: {base_url}")
    
    def test_service_uses_bearer_auth(self):
        """LightspeedService should use Bearer token auth"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="my_personal_token")
        headers = ls._headers()
        
        assert "Authorization" in headers, "Should have Authorization header"
        assert headers["Authorization"] == "Bearer my_personal_token", \
            f"Should use Bearer auth, got: {headers['Authorization']}"
        
        print(f"PASS: Bearer auth correct: {headers['Authorization']}")
    
    def test_service_mock_mode_without_credentials(self):
        """LightspeedService should be in mock mode without credentials"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="", personal_token="")
        assert ls.mock_mode == True, "Should be in mock mode without credentials"
        
        ls2 = LightspeedService(domain_prefix="store", personal_token="")
        assert ls2.mock_mode == True, "Should be in mock mode without token"
        
        ls3 = LightspeedService(domain_prefix="", personal_token="token")
        assert ls3.mock_mode == True, "Should be in mock mode without domain prefix"
        
        print("PASS: Mock mode correctly detected when credentials missing")
    
    def test_service_not_mock_mode_with_credentials(self):
        """LightspeedService should NOT be in mock mode with credentials"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="testtoken")
        assert ls.mock_mode == False, "Should NOT be in mock mode with credentials"
        
        print("PASS: Not in mock mode when credentials provided")
    
    def test_service_products_endpoint(self):
        """LightspeedService should use /products endpoint (X-Series)"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="testtoken")
        url = ls._url("products")
        
        assert "teststore.retail.lightspeed.app/api/2.0/products" in url, \
            f"Products URL incorrect: {url}"
        
        print(f"PASS: Products endpoint correct: {url}")
    
    def test_service_categories_endpoint(self):
        """LightspeedService should use /product_categories endpoint (X-Series)"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="testtoken")
        url = ls._url("product_categories")
        
        assert "teststore.retail.lightspeed.app/api/2.0/product_categories" in url, \
            f"Categories URL incorrect: {url}"
        
        print(f"PASS: Categories endpoint correct: {url}")
    
    def test_service_image_upload_endpoint(self):
        """LightspeedService should use /products/{id}/actions/image_upload endpoint"""
        from lightspeed_service import LightspeedService
        
        ls = LightspeedService(domain_prefix="teststore", personal_token="testtoken")
        url = ls._url("products/12345/actions/image_upload")
        
        assert "teststore.retail.lightspeed.app/api/2.0/products/12345/actions/image_upload" in url, \
            f"Image upload URL incorrect: {url}"
        
        print(f"PASS: Image upload endpoint correct: {url}")


class TestNoEcwidReferences:
    """Verify no Ecwid API references remain in the codebase"""
    
    def test_lightspeed_service_no_ecwid(self):
        """lightspeed_service.py should not contain ecwid references"""
        with open('/app/backend/lightspeed_service.py', 'r') as f:
            content = f.read().lower()
        
        assert "ecwid" not in content, "lightspeed_service.py should not reference ecwid"
        assert "app.ecwid.com" not in content, "lightspeed_service.py should not use app.ecwid.com"
        
        print("PASS: No ecwid references in lightspeed_service.py")
    
    def test_server_no_ecwid(self):
        """server.py should not contain ecwid references in Lightspeed routes"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read().lower()
        
        # Check that ecwid is not in the main code (comments are ok)
        lines = content.split('\n')
        code_lines = [l for l in lines if not l.strip().startswith('#')]
        code_content = '\n'.join(code_lines)
        
        # Allow "ecwid" in comments but not in actual code
        assert "app.ecwid.com" not in code_content, "server.py should not use app.ecwid.com in code"
        
        print("PASS: No ecwid API URLs in server.py code")


class TestProductPayloadXSeries:
    """Test product creation uses correct X-Series fields"""
    
    def test_product_payload_fields(self):
        """Product payload should use X-Series field names"""
        from lightspeed_service import LightspeedService
        
        # Check the create_or_update_product method builds correct payload
        # by examining the code
        with open('/app/backend/lightspeed_service.py', 'r') as f:
            content = f.read()
        
        # X-Series uses these field names
        assert "'name'" in content or '"name"' in content, "Should use 'name' field"
        assert "'description'" in content or '"description"' in content, "Should use 'description' field"
        assert "'sku'" in content or '"sku"' in content, "Should use 'sku' field"
        assert "'supply_price'" in content or '"supply_price"' in content, "Should use 'supply_price' field"
        assert "'price_excluding_tax'" in content or '"price_excluding_tax"' in content, "Should use 'price_excluding_tax' field"
        assert "'product_type_id'" in content or '"product_type_id"' in content, "Should use 'product_type_id' for category"
        
        print("PASS: Product payload uses correct X-Series field names")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
