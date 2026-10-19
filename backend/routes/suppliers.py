"""Supplier routes: CRUD, test, catalog, import."""
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import deps
from deps import row_to_dict, new_id, utc_now, get_current_user, get_admin_user
from models import SupplierCreate, SupplierUpdate

router = APIRouter(prefix="/api")


@router.get("/suppliers")
async def get_suppliers(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM suppliers ORDER BY supplier_name")
        suppliers = []
        for row in rows:
            s = row_to_dict(row)
            if s.get('password'): s['password'] = '***'
            if s.get('media_password'): s['media_password'] = '***'
            suppliers.append(s)
        return {"suppliers": suppliers}


@router.post("/suppliers")
async def create_supplier(data: SupplierCreate, user: dict = Depends(get_admin_user)):
    supplier_id = new_id()
    async with deps.pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO suppliers (id, supplier_name, api_base_url, account_number, password, media_password, use_uat, endpoint_style, services, bulk_data_url, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active', $11, $11)
        ''', supplier_id, data.supplier_name, data.api_base_url, data.account_number, data.password, data.media_password, data.use_uat, data.endpoint_style, json.dumps(data.services), data.bulk_data_url, utc_now())
        return {"id": supplier_id, "message": "Supplier created"}


@router.get("/suppliers/{supplier_id}")
async def get_supplier(supplier_id: str, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        s = row_to_dict(row)
        if s.get('password'): s['password'] = '***'
        if s.get('media_password'): s['media_password'] = '***'
        return s


@router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, data: SupplierUpdate, user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not existing:
            raise HTTPException(404, "Supplier not found")
        update_fields = []
        values = []
        param_idx = 1
        for field, attr in [('supplier_name', data.supplier_name), ('api_base_url', data.api_base_url),
                            ('account_number', data.account_number), ('use_uat', data.use_uat),
                            ('endpoint_style', data.endpoint_style), ('status', data.status), ('bulk_data_url', data.bulk_data_url)]:
            if attr is not None:
                update_fields.append(f"{field} = ${param_idx}"); values.append(attr); param_idx += 1
        if data.password is not None and data.password != '***':
            update_fields.append(f"password = ${param_idx}"); values.append(data.password); param_idx += 1
        if data.media_password is not None and data.media_password != '***':
            update_fields.append(f"media_password = ${param_idx}"); values.append(data.media_password); param_idx += 1
        if data.services is not None:
            update_fields.append(f"services = ${param_idx}"); values.append(json.dumps(data.services)); param_idx += 1
        update_fields.append(f"updated_at = ${param_idx}"); values.append(utc_now()); param_idx += 1
        values.append(supplier_id)
        if update_fields:
            query = f"UPDATE suppliers SET {', '.join(update_fields)} WHERE id = ${param_idx}"
            await conn.execute(query, *values)
        return {"status": "updated"}


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str, user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        result = await conn.execute("DELETE FROM suppliers WHERE id = $1", supplier_id)
        if result == "DELETE 0":
            raise HTTPException(404, "Supplier not found")
        return {"status": "deleted"}


@router.post("/suppliers/{supplier_id}/test")
async def test_supplier(supplier_id: str, user: dict = Depends(get_current_user)):
    from multi_supplier.connector import make_connector
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        connector = make_connector(supplier)
        return await asyncio.to_thread(connector.test_connection)


@router.get("/suppliers/{supplier_id}/catalog")
async def search_supplier_catalog(
    supplier_id: str,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    get_details: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    from multi_supplier.connector import make_connector
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        existing_rows = await conn.fetch("SELECT supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
        existing_skus = set(r['supplier_sku'] for r in existing_rows)
    connector = make_connector(supplier)
    connector.discovery_limit=limit
    result = await asyncio.to_thread(connector.get_sellable_products)
    if not result.get('success'):
        raise HTTPException(500, f"Failed to fetch catalog: {result.get('error')}")
    all_products = result.get('products', [])
    unique_skus = list(set(p['product_id'] for p in all_products))
    total_count = len(unique_skus)
    if search:
        search_lower = search.lower()
        unique_skus = [sku for sku in unique_skus if search_lower in sku.lower()]
    unique_skus = unique_skus[:limit]
    products = []
    if get_details:
        for sku in unique_skus:
            product_data = await asyncio.to_thread(connector.get_product,sku)
            if product_data.get('success') and product_data.get('product'):
                p = product_data['product']
                products.append({'supplier_sku': sku, 'product_name': p.get('product_name') or p.get('name',''), 'description': p.get('description', ''),
                    'brand': p.get('brand', ''), 'category': p.get('category', ''), 'variant_count': len(p.get('variants', [])), 'is_imported': sku in existing_skus})
    else:
        for sku in unique_skus:
            products.append({'supplier_sku': sku, 'product_name': '', 'description': '', 'brand': '', 'category': '', 'variant_count': 0, 'is_imported': sku in existing_skus})
    return {'products': products, 'total_in_catalog': total_count, 'showing': len(products), 'supplier_name': supplier.get('supplier_name', '')}


@router.post("/suppliers/{supplier_id}/import-product/{product_sku}")
async def import_product_from_catalog(supplier_id: str, product_sku: str, user: dict = Depends(get_current_user)):
    from multi_supplier.connector import make_connector
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        existing = await conn.fetchrow("SELECT id FROM products WHERE supplier_id = $1 AND supplier_sku = $2", supplier_id, product_sku)
        if existing:
            return {"success": False, "message": "Product already imported", "product_id": existing['id']}
    connector = make_connector(supplier)
    product_data = await asyncio.to_thread(connector.get_product,product_sku)
    if not product_data.get('success') or not product_data.get('product'):
        raise HTTPException(500, f"Failed to fetch product: {product_data.get('error', 'Unknown error')}")
    p = product_data['product']
    from routes.sync import apply_result
    status,code,message=await apply_result(supplier_id,product_sku,'products',product_data)
    if status=='failed':raise HTTPException(502,message)
    async with deps.pool.acquire() as conn:
        product_id=await conn.fetchval('SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2',supplier_id,product_sku)
    return {'success':True,'product_id':product_id,'product_name':p.get('product_name',''),'variants_added':len(p.get('variants',[])),'message':message}
