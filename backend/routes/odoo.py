"""Odoo routes: connection test, push products, sync/manage categories."""
import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import deps
from deps import row_to_dict, utc_now, new_id, get_current_user, calculate_sale_price
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/odoo/test-connection")
async def test_odoo_connection(user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not row:
            return {"success": False, "message": "Settings not configured"}
        settings = row_to_dict(row)
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    result = odoo.test_connection()
    async with deps.pool.acquire() as conn:
        await conn.execute("UPDATE settings SET odoo_connected = $1 WHERE id = 'system_settings'", result.get('success', False))
    return result


@router.post("/odoo/push-products")
async def push_to_odoo(user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        pending_count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE AND odoo_sync_status = 'pending'")
        if pending_count == 0:
            return {"status": "no_products", "message": "No products pending sync to Odoo"}
        products = await conn.fetch('''
            SELECT p.*, cm.odoo_category_id FROM products p
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending'
        ''')
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    conn_test = odoo.test_connection()
    if not conn_test.get('connected'):
        raise HTTPException(400, f"Odoo connection failed: {conn_test.get('message')}")
    synced = 0; failed = 0
    for p in products:
        product = row_to_dict(p)
        async with deps.pool.acquire() as conn:
            variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
            images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
        cost = float(product.get('base_price') or 0)
        sale_price = calculate_sale_price(cost, markup)
        odoo_data = {
            'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
            'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
            'category_id': product.get('odoo_category_id'), 'default_category': 'SanMar Apparel',
            'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(i) for i in images],
        }
        result = odoo.create_or_update_product(odoo_data)
        if result.get('success'):
            async with deps.pool.acquire() as conn:
                await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                    str(result.get('odoo_id', '')), utc_now(), product['id'])
            synced += 1
        else:
            failed += 1
            logger.error(f"Failed to push {product.get('supplier_sku')}: {result.get('error')}")
    return {"status": "completed", "products_to_push": len(products), "synced": synced, "failed": failed}


@router.post("/odoo/sync-products")
async def sync_to_odoo(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        if not settings.get('odoo_connected'):
            raise HTTPException(400, "Odoo not connected")
        products = await conn.fetch('''
            SELECT p.*, cm.odoo_category_id FROM products p
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending'
        ''')
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    synced = 0
    for p in products:
        product = row_to_dict(p)
        async with deps.pool.acquire() as conn:
            variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
            images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
        cost = float(product.get('base_price') or 0)
        sale_price = calculate_sale_price(cost, markup)
        odoo_data = {
            'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
            'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
            'category_id': product.get('odoo_category_id'), 'default_category': 'SanMar Apparel',
            'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(i) for i in images],
        }
        result = odoo.create_or_update_product(odoo_data)
        if result.get('success'):
            async with deps.pool.acquire() as conn:
                await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                    str(result.get('odoo_id', '')), utc_now(), product['id'])
            synced += 1
    return {"synced": synced, "total": len(products)}


@router.post("/odoo/sync-categories")
async def sync_odoo_categories(user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    result = odoo.get_ecommerce_categories()
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to fetch categories'))
    categories = result.get('categories', [])
    async with deps.pool.acquire() as conn:
        synced = 0
        for cat in categories:
            await conn.execute('''
                INSERT INTO odoo_categories (id, odoo_category_id, category_name, parent_category, parent_id, last_synced, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
                ON CONFLICT (odoo_category_id) DO UPDATE SET
                    category_name = EXCLUDED.category_name, parent_category = EXCLUDED.parent_category,
                    parent_id = EXCLUDED.parent_id, last_synced = NOW(), updated_at = NOW()
            ''', new_id(), cat['odoo_category_id'], cat['category_name'], cat.get('parent_category'), cat.get('parent_id'))
            synced += 1
    return {"success": True, "synced": synced, "total": len(categories)}


@router.get("/odoo/categories")
async def get_odoo_categories(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM odoo_categories ORDER BY parent_category NULLS FIRST, category_name')
        return {"categories": [row_to_dict(r) for r in rows]}


@router.put("/odoo/categories/{category_id}/select")
async def toggle_odoo_category_selection(category_id: str, data: dict, user: dict = Depends(get_current_user)):
    is_selected = data.get('is_selected', False)
    async with deps.pool.acquire() as conn:
        await conn.execute('UPDATE odoo_categories SET is_selected = $1, updated_at = NOW() WHERE id = $2', is_selected, category_id)
    return {"success": True}


@router.put("/odoo/categories/bulk-select")
async def bulk_select_odoo_categories(data: dict, user: dict = Depends(get_current_user)):
    category_ids = data.get('category_ids', []); is_selected = data.get('is_selected', False)
    async with deps.pool.acquire() as conn:
        await conn.execute('UPDATE odoo_categories SET is_selected = $1, updated_at = NOW() WHERE id = ANY($2)', is_selected, category_ids)
    return {"success": True, "updated": len(category_ids)}
