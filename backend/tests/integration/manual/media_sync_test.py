#!/usr/bin/env python3
import requests
import json
import sys

API_BASE = "https://product-bridge-23.preview.emergentagent.com/api"

def test_media_sync_functionality():
    """Test specific media sync features for iteration 2"""
    print("🖼️  Testing Media Sync Functionality")
    print("=" * 50)
    
    # Test 1: Check if GET /api/products returns thumbnail URLs
    print("\n1. Testing Products List - Checking for thumbnails")
    try:
        response = requests.get(f"{API_BASE}/products")
        data = response.json()
        products = data.get('products', [])
        
        print(f"   Found {len(products)} products")
        
        thumbnails_count = 0
        for product in products:
            if product.get('thumbnail'):
                thumbnails_count += 1
                print(f"   ✅ {product['product_name']}: {product['thumbnail']}")
            else:
                print(f"   ❌ {product['product_name']}: NO THUMBNAIL")
        
        print(f"   📊 Products with thumbnails: {thumbnails_count}/{len(products)}")
        
        if thumbnails_count == len(products):
            print("   ✅ ALL products have thumbnails (CDN fallback working)")
        else:
            print("   ❌ Some products missing thumbnails")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Check specific product detail for media array
    print("\n2. Testing Product Detail - Checking media array")
    try:
        response = requests.get(f"{API_BASE}/products")
        data = response.json()
        products = data.get('products', [])
        
        if products:
            product_id = products[0]['id']
            product_name = products[0]['product_name']
            
            detail_response = requests.get(f"{API_BASE}/products/{product_id}")
            product_detail = detail_response.json()
            
            media = product_detail.get('media', [])
            print(f"   Product: {product_name}")
            print(f"   Media count: {len(media)}")
            
            if media:
                for i, m in enumerate(media):
                    print(f"   📷 Media {i+1}: {m.get('media_url', 'No URL')} ({m.get('media_type', 'Unknown')})")
                print("   ✅ Product has media")
            else:
                print("   ❌ Product has no media")
                
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Test media sync trigger
    print("\n3. Testing Media Sync Trigger")
    try:
        # Get supplier ID first
        suppliers_response = requests.get(f"{API_BASE}/suppliers")
        suppliers = suppliers_response.json().get('suppliers', [])
        
        if suppliers:
            supplier_id = suppliers[0]['id']
            supplier_name = suppliers[0]['supplier_name']
            
            print(f"   Triggering media sync for: {supplier_name}")
            
            sync_response = requests.post(f"{API_BASE}/sync/media/{supplier_id}")
            sync_data = sync_response.json()
            
            if sync_response.status_code == 200:
                print(f"   ✅ Media sync triggered: {sync_data.get('sync_log_id', 'unknown')}")
            else:
                print(f"   ❌ Media sync failed: {sync_response.status_code}")
                
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 4: Check sync logs for media entries with CDN fallback message
    print("\n4. Testing Sync Logs - Looking for media sync with CDN fallback")
    try:
        logs_response = requests.get(f"{API_BASE}/sync/logs?sync_type=media&limit=10")
        logs_data = logs_response.json()
        logs = logs_data.get('logs', [])
        
        print(f"   Found {len(logs)} media sync logs")
        
        cdn_fallback_found = False
        for log in logs:
            sync_type = log.get('sync_type')
            message = log.get('message', '')
            status = log.get('status')
            
            print(f"   📝 {sync_type} sync - Status: {status}")
            print(f"      Message: {message}")
            
            if 'CDN fallback' in message or 'SOAP API auth failed' in message:
                cdn_fallback_found = True
                print("      ✅ CDN fallback message found!")
            
        if cdn_fallback_found:
            print("   ✅ CDN fallback implementation verified in logs")
        else:
            print("   ⚠️  CDN fallback message not found in recent logs")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    test_media_sync_functionality()