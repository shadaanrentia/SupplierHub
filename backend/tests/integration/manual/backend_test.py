#!/usr/bin/env python3
import requests
import sys
import json
from datetime import datetime

class SupplierHubAPITester:
    def __init__(self, base_url="https://product-bridge-23.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def run_test(self, name, method, endpoint, expected_status, data=None, params=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {method} {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    resp_data = response.json()
                    if isinstance(resp_data, dict) and len(resp_data) > 0:
                        print(f"   Response keys: {list(resp_data.keys())}")
                except:
                    pass
                return True, response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
            else:
                self.failed_tests.append(f"{name}: Expected {expected_status}, got {response.status_code}")
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error: {error_detail}")
                except:
                    print(f"   Response: {response.text[:200]}")
                return False, {}

        except Exception as e:
            self.failed_tests.append(f"{name}: {str(e)}")
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_dashboard_stats(self):
        """Test dashboard statistics endpoint"""
        success, response = self.run_test(
            "Dashboard Stats",
            "GET", 
            "dashboard/stats",
            200
        )
        if success:
            required_keys = ['total_products', 'total_suppliers', 'total_variants']
            missing_keys = [key for key in required_keys if key not in response]
            if missing_keys:
                print(f"   ⚠️  Missing keys: {missing_keys}")
                return False
            print(f"   📊 Products: {response.get('total_products', 0)}, Suppliers: {response.get('total_suppliers', 0)}, Variants: {response.get('total_variants', 0)}")
        return success

    def test_seed_demo_data(self):
        """Seed demo data if needed"""
        # First check if data exists
        success, stats = self.run_test("Check existing data", "GET", "dashboard/stats", 200)
        
        if success and stats.get('total_products', 0) == 0:
            print("   No products found, seeding demo data...")
            success, response = self.run_test(
                "Seed Demo Data",
                "POST",
                "seed-demo", 
                200
            )
            if success:
                print(f"   🌱 Seeded {response.get('products_created', 0)} products")
            return success
        else:
            print(f"   ✅ Data already exists: {stats.get('total_products', 0)} products")
            return True

    def test_products_list(self):
        """Test products listing with filters"""
        # Test basic products list
        success, response = self.run_test(
            "Products List",
            "GET",
            "products",
            200
        )
        
        if success:
            products = response.get('products', [])
            total = response.get('total', 0)
            print(f"   📦 Found {len(products)} products (total: {total})")
            
            # Test category filter for Hoodies
            success2, response2 = self.run_test(
                "Products Filter (Hoodies)",
                "GET",
                "products",
                200,
                params={'category': 'Hoodies'}
            )
            
            if success2:
                hoodie_products = response2.get('products', [])
                print(f"   👕 Found {len(hoodie_products)} Hoodies")
                return len(hoodie_products) >= 1  # Should have at least 1 hoodie
        
        return success

    def test_product_detail_and_selection(self):
        """Test product detail view and Odoo selection toggle"""
        # Get first product
        success, response = self.run_test("Get Products for Detail Test", "GET", "products", 200)
        
        if not success or not response.get('products'):
            return False
            
        product_id = response['products'][0]['id']
        
        # Test product detail
        success, product = self.run_test(
            "Product Detail",
            "GET",
            f"products/{product_id}",
            200
        )
        
        if success:
            print(f"   📋 Product: {product.get('product_name', 'Unknown')}")
            print(f"   🔧 Variants: {len(product.get('variants', []))}")
            
            # Test Odoo selection toggle
            current_selection = product.get('selected_for_odoo', False)
            success2, _ = self.run_test(
                "Toggle Odoo Selection",
                "POST",
                f"products/{product_id}/select-for-odoo",
                200,
                data={
                    "product_id": product_id,
                    "selected": not current_selection
                }
            )
            
            if success2:
                print(f"   🔄 Toggled Odoo selection: {current_selection} -> {not current_selection}")
            
            return success2
            
        return success

    def test_suppliers_endpoints(self):
        """Test supplier CRUD operations"""
        # List suppliers
        success, response = self.run_test(
            "List Suppliers",
            "GET",
            "suppliers",
            200
        )
        
        if success:
            suppliers = response.get('suppliers', [])
            print(f"   🚛 Found {len(suppliers)} suppliers")
            
            if suppliers:
                supplier_id = suppliers[0]['id']
                supplier_name = suppliers[0].get('supplier_name', 'Unknown')
                print(f"   📝 Testing with supplier: {supplier_name}")
                
                # Test individual supplier get
                success2, _ = self.run_test(
                    "Get Individual Supplier",
                    "GET",
                    f"suppliers/{supplier_id}",
                    200
                )
                return success2
                
        return success

    def test_sync_endpoints(self):
        """Test sync management endpoints"""
        # Get sync logs
        success, response = self.run_test(
            "Sync Logs",
            "GET",
            "sync/logs",
            200
        )
        
        if success:
            logs = response.get('logs', [])
            print(f"   📜 Found {len(logs)} sync log entries")
            
            # Test sync trigger (this will run in background)
            suppliers_success, suppliers_resp = self.run_test("Get Suppliers for Sync", "GET", "suppliers", 200)
            if suppliers_success and suppliers_resp.get('suppliers'):
                supplier_id = suppliers_resp['suppliers'][0]['id']
                success2, sync_resp = self.run_test(
                    "Trigger Product Sync",
                    "POST",
                    f"sync/products/{supplier_id}",
                    200
                )
                if success2:
                    print(f"   ⚡ Started sync job: {sync_resp.get('sync_log_id', 'unknown')}")
                return success2
                
        return success

    def test_odoo_endpoints(self):
        """Test Odoo integration endpoints"""
        # Test connection (should return mock mode)
        success, response = self.run_test(
            "Odoo Test Connection",
            "POST",
            "odoo/test-connection",
            200
        )
        
        if success:
            mock_mode = response.get('mock_mode', False)
            connected = response.get('connected', False)
            message = response.get('message', '')
            print(f"   🔌 Connection: {connected}, Mock: {mock_mode}")
            print(f"   💬 Message: {message}")
            
            # Test push to Odoo
            success2, push_resp = self.run_test(
                "Push to Odoo",
                "POST",
                "odoo/push-products",
                200
            )
            
            if success2:
                status = push_resp.get('status', 'unknown')
                print(f"   🚀 Push status: {status}")
                if status == 'no_products':
                    print("   ℹ️  No products selected for Odoo yet")
                
            return success2
            
        return success

    def test_settings_endpoints(self):
        """Test settings CRUD"""
        success, response = self.run_test(
            "Get Settings",
            "GET",
            "settings",
            200
        )
        
        if success:
            print(f"   ⚙️  Odoo URL: {response.get('odoo_url', 'Not set')}")
            print(f"   ⏰ Sync interval: {response.get('sync_products_interval_hours', 24)}h")
            
            # Test settings update
            success2, _ = self.run_test(
                "Update Settings",
                "PUT",
                "settings",
                200,
                data={"sync_products_interval_hours": 24}
            )
            return success2
            
        return success

    def run_all_tests(self):
        """Run comprehensive backend API tests"""
        print("🚀 Starting SupplierHub Backend API Tests")
        print("=" * 50)
        
        # Test sequence
        tests = [
            ("Dashboard Stats", self.test_dashboard_stats),
            ("Seed Demo Data", self.test_seed_demo_data),
            ("Products Endpoints", self.test_products_list),
            ("Product Detail & Selection", self.test_product_detail_and_selection),
            ("Suppliers Endpoints", self.test_suppliers_endpoints),
            ("Sync Management", self.test_sync_endpoints), 
            ("Odoo Integration", self.test_odoo_endpoints),
            ("Settings Management", self.test_settings_endpoints)
        ]
        
        for test_name, test_func in tests:
            print(f"\n{'='*20} {test_name} {'='*20}")
            try:
                test_func()
            except Exception as e:
                self.failed_tests.append(f"{test_name}: Exception - {str(e)}")
                print(f"❌ Test failed with exception: {e}")
        
        # Print summary
        print("\n" + "="*50)
        print("📊 TEST SUMMARY")
        print("="*50)
        print(f"Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%" if self.tests_run > 0 else "0%")
        
        if self.failed_tests:
            print("\n❌ FAILED TESTS:")
            for failure in self.failed_tests:
                print(f"  - {failure}")
        
        return self.tests_passed == self.tests_run

def main():
    tester = SupplierHubAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())