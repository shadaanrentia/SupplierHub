"""
Test suite for Supplier CRUD operations - Iteration 12
Focus: Verify supplier creation works after PostgreSQL auto-start fix
Bug: User reported 'Unable to create supplier - Error message - Failed to create supplier'
Fix: Added _ensure_postgresql() auto-start function in server.py startup
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndPostgreSQL:
    """Verify PostgreSQL is running and backend is healthy"""

    def test_health_endpoint(self):
        """GET /api/health - Backend should be healthy with PostgreSQL"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "postgresql"
        print(f"✓ Health check passed - PostgreSQL is running")


class TestSupplierCRUD:
    """Test full supplier CRUD flow - Create, Read, Update, Delete"""

    @pytest.fixture
    def auth_headers(self):
        """Get auth token for admin user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        if response.status_code == 200:
            token = response.json().get("token")
            return {"Authorization": f"Bearer {token}"}
        pytest.skip("Authentication failed")

    def test_create_supplier_basic(self, auth_headers):
        """POST /api/suppliers - Create supplier with basic fields"""
        supplier_name = f"TEST_Supplier_{uuid.uuid4().hex[:8]}"
        payload = {
            "supplier_name": supplier_name,
            "account_number": "12345",
            "password": "testpass123"
        }
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload, headers=auth_headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "id" in data, "Response should contain supplier ID"
        assert data.get("message") == "Supplier created"
        
        supplier_id = data["id"]
        print(f"✓ Created supplier: {supplier_name} (ID: {supplier_id})")
        
        # Verify persistence via GET
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["supplier_name"] == supplier_name
        assert fetched["account_number"] == "12345"
        assert fetched["password"] == "***"  # Should be masked
        print(f"✓ Verified supplier persisted in database")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        print(f"✓ Cleaned up test supplier")

    def test_create_supplier_with_all_fields(self, auth_headers):
        """POST /api/suppliers - Create supplier with all fields"""
        supplier_name = f"TEST_FullSupplier_{uuid.uuid4().hex[:8]}"
        payload = {
            "supplier_name": supplier_name,
            "api_base_url": "https://test-api.example.com",
            "account_number": "ACC123",
            "password": "pass123",
            "media_password": "mediapass456",
            "endpoint_style": "atc",
            "use_uat": True,
            "services": {"product_data": "https://test.com/products"},
            "bulk_data_url": "https://test.com/bulk"
        }
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        supplier_id = data["id"]
        
        # Verify all fields persisted
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert get_response.status_code == 200
        fetched = get_response.json()
        
        assert fetched["supplier_name"] == supplier_name
        assert fetched["api_base_url"] == "https://test-api.example.com"
        assert fetched["account_number"] == "ACC123"
        assert fetched["password"] == "***"  # Masked
        assert fetched["media_password"] == "***"  # Masked
        assert fetched["endpoint_style"] == "atc"
        assert fetched["use_uat"] == True
        assert fetched["bulk_data_url"] == "https://test.com/bulk"
        print(f"✓ All supplier fields persisted correctly")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)

    def test_list_suppliers(self, auth_headers):
        """GET /api/suppliers - List all suppliers"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "suppliers" in data
        assert isinstance(data["suppliers"], list)
        print(f"✓ Listed {len(data['suppliers'])} suppliers")

    def test_update_supplier(self, auth_headers):
        """PUT /api/suppliers/{id} - Update supplier fields"""
        # Create test supplier
        create_payload = {
            "supplier_name": f"TEST_ToUpdate_{uuid.uuid4().hex[:8]}",
            "account_number": "OLD123"
        }
        create_response = requests.post(f"{BASE_URL}/api/suppliers", json=create_payload, headers=auth_headers)
        assert create_response.status_code == 200
        supplier_id = create_response.json()["id"]
        
        # Update supplier
        new_name = f"TEST_Updated_{uuid.uuid4().hex[:8]}"
        update_payload = {
            "supplier_name": new_name,
            "account_number": "NEW456",
            "api_base_url": "https://updated-api.com"
        }
        update_response = requests.put(f"{BASE_URL}/api/suppliers/{supplier_id}", json=update_payload, headers=auth_headers)
        assert update_response.status_code == 200
        assert update_response.json().get("status") == "updated"
        
        # Verify update persisted
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["supplier_name"] == new_name
        assert fetched["account_number"] == "NEW456"
        assert fetched["api_base_url"] == "https://updated-api.com"
        print(f"✓ Supplier updated and verified")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)

    def test_delete_supplier(self, auth_headers):
        """DELETE /api/suppliers/{id} - Delete supplier"""
        # Create test supplier
        create_payload = {"supplier_name": f"TEST_ToDelete_{uuid.uuid4().hex[:8]}"}
        create_response = requests.post(f"{BASE_URL}/api/suppliers", json=create_payload, headers=auth_headers)
        assert create_response.status_code == 200
        supplier_id = create_response.json()["id"]
        
        # Delete supplier
        delete_response = requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert delete_response.status_code == 200
        assert delete_response.json().get("status") == "deleted"
        
        # Verify deletion
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert get_response.status_code == 404
        print(f"✓ Supplier deleted and verified gone")

    def test_get_nonexistent_supplier_returns_404(self, auth_headers):
        """GET /api/suppliers/{id} - Nonexistent ID returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.get(f"{BASE_URL}/api/suppliers/{fake_id}", headers=auth_headers)
        assert response.status_code == 404
        print(f"✓ Nonexistent supplier correctly returns 404")

    def test_delete_nonexistent_supplier_returns_404(self, auth_headers):
        """DELETE /api/suppliers/{id} - Nonexistent ID returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(f"{BASE_URL}/api/suppliers/{fake_id}", headers=auth_headers)
        assert response.status_code == 404
        print(f"✓ Delete nonexistent supplier correctly returns 404")


class TestSupplierWithoutAuth:
    """Test supplier endpoints require authentication"""

    def test_create_supplier_without_auth_returns_401(self):
        """POST /api/suppliers without auth should return 401"""
        payload = {"supplier_name": "TEST_NoAuth"}
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload)
        assert response.status_code == 401
        print(f"✓ Create supplier without auth correctly returns 401")

    def test_list_suppliers_without_auth_returns_401(self):
        """GET /api/suppliers without auth should return 401"""
        response = requests.get(f"{BASE_URL}/api/suppliers")
        assert response.status_code == 401
        print(f"✓ List suppliers without auth correctly returns 401")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
