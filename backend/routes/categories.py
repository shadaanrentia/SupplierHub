"""Category mapping routes."""
from fastapi import APIRouter, Depends, HTTPException
import json
import deps
from deps import row_to_dict, new_id, get_current_user

router = APIRouter(prefix="/api")


async def ensure_supplier_mapping_schema(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS supplier_category_links (
        id VARCHAR(64) PRIMARY KEY,
        supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
        store_domain TEXT NOT NULL,
        supplier_category_name TEXT NOT NULL,
        lightspeed_category_id TEXT,
        odoo_category_id INTEGER,
        lightspeed_override BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(supplier_id,store_domain,supplier_category_name)
    )""")
    await conn.execute("ALTER TABLE supplier_category_links ADD COLUMN IF NOT EXISTS lightspeed_override BOOLEAN NOT NULL DEFAULT FALSE")


@router.on_event("startup")
async def init_supplier_mapping_schema():
    async with deps.pool.acquire() as conn:
        await ensure_supplier_mapping_schema(conn)


async def mapping_store(conn):
    return str(await conn.fetchval("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'") or '').strip()


async def checked_supplier(conn, supplier_id):
    if not await conn.fetchval("SELECT 1 FROM suppliers WHERE id=$1", supplier_id):
        raise HTTPException(404, "Supplier not found")


@router.get("/supplier-categories")
async def get_supplier_categories(supplier_id: str = None, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        if supplier_id:
            await checked_supplier(conn, supplier_id)
        rows = await conn.fetch("""SELECT DISTINCT category FROM products
            WHERE category IS NOT NULL AND BTRIM(category)<>''
              AND ($1::varchar IS NULL OR supplier_id=$1)
            ORDER BY category""", supplier_id)
        return {"supplier_id": supplier_id, "categories": [r['category'] for r in rows]}


@router.get("/category-mappings")
async def get_category_mappings(supplier_id: str = None, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        if supplier_id:
            await checked_supplier(conn, supplier_id)
            await ensure_supplier_mapping_schema(conn)
            rows = await conn.fetch("""SELECT m.* FROM supplier_category_links m
                WHERE supplier_id=$1 AND store_domain=$2 ORDER BY supplier_category_name""",
                supplier_id, await mapping_store(conn))
            return {"supplier_id": supplier_id, "mappings": [row_to_dict(r) for r in rows]}
        rows = await conn.fetch('''
            SELECT cm.*, oc.category_name as odoo_category_name
            FROM category_mapping cm LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            ORDER BY cm.supplier_category_name
        ''')
        return {"mappings": [row_to_dict(r) for r in rows]}


@router.post("/category-mappings")
async def create_or_update_mapping(data: dict, user: dict = Depends(get_current_user)):
    supplier_id = data.get('supplier_id')
    if supplier_id:
        category = data.get('supplier_category_name')
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(400, "Supplier category name is required")
        if 'lightspeed_category_id' not in data and 'odoo_category_id' not in data:
            raise HTTPException(400, "Choose a destination or clear the mapping")
        cid = data.get('lightspeed_category_id') or None
        oid = data.get('odoo_category_id')
        if cid is not None and (not isinstance(cid, str) or len(cid)>200):
            raise HTTPException(400, "Invalid Lightspeed category ID")
        if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int)):
            raise HTTPException(400, "Invalid Odoo category ID")
        async with deps.pool.acquire() as conn:
            await ensure_supplier_mapping_schema(conn)
            await checked_supplier(conn, supplier_id)
            domain = await mapping_store(conn)
            if 'lightspeed_category_id' in data and not domain:
                raise HTTPException(400, "Configure Lightspeed in Settings first")
            if not await conn.fetchval("SELECT 1 FROM products WHERE supplier_id=$1 AND category=$2 LIMIT 1", supplier_id, category):
                raise HTTPException(400, "Category does not belong to this supplier's imported products")
            if cid and await conn.fetchval("SELECT to_regclass('public.lightspeed_category_snapshots')"):
                snapshot = await conn.fetchval("SELECT categories FROM lightspeed_category_snapshots WHERE store_domain=$1", domain.lower())
                from category_tree import category_tree
                snapshot = category_tree(snapshot or [])
                if not any(c['lightspeed_category_id']==cid and c['leaf_category'] and c['hierarchy_valid'] for c in snapshot):
                    raise HTTPException(400, "Refresh Lightspeed categories and choose an available final category")
            async with conn.transaction():
                await conn.execute("""INSERT INTO supplier_category_links
                    (id,supplier_id,store_domain,supplier_category_name,lightspeed_category_id,odoo_category_id,lightspeed_override)
                    VALUES($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT(supplier_id,store_domain,supplier_category_name) DO UPDATE SET
                        lightspeed_category_id=CASE WHEN $7 THEN EXCLUDED.lightspeed_category_id ELSE supplier_category_links.lightspeed_category_id END,
                        odoo_category_id=CASE WHEN $8 THEN EXCLUDED.odoo_category_id ELSE supplier_category_links.odoo_category_id END,
                        lightspeed_override=supplier_category_links.lightspeed_override OR EXCLUDED.lightspeed_override,
                        updated_at=NOW()""",new_id(),supplier_id,domain,category,cid,oid,
                        'lightspeed_category_id' in data,'odoo_category_id' in data)
                await conn.execute("""UPDATE products SET preprocessing_status='pending',updated_at=NOW()
                    WHERE supplier_id=$1 AND category=$2""", supplier_id,category)
        return {"success": True}
    supplier_category = data.get('supplier_category_name')
    odoo_category_id = data.get('odoo_category_id')
    lightspeed_category_id = data.get('lightspeed_category_id')  # UUID string or None
    if not supplier_category:
        raise HTTPException(400, "Supplier category name is required")
    async with deps.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM category_mapping WHERE supplier_category_name = $1", supplier_category)
        if existing:
            # Update existing mapping
            if 'odoo_category_id' in data:
                await conn.execute(
                    "UPDATE category_mapping SET odoo_category_id = $1, updated_at = NOW() WHERE supplier_category_name = $2",
                    odoo_category_id, supplier_category)
            if 'lightspeed_category_id' in data:
                await conn.execute(
                    "UPDATE category_mapping SET lightspeed_category_id = $1, updated_at = NOW() WHERE supplier_category_name = $2",
                    lightspeed_category_id if lightspeed_category_id else None, supplier_category)
        else:
            await conn.execute('''
                INSERT INTO category_mapping (id, supplier_category_name, odoo_category_id, lightspeed_category_id, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
            ''', new_id(), supplier_category, odoo_category_id, lightspeed_category_id)
    return {"success": True}


@router.delete("/category-mappings/{mapping_id}")
async def delete_mapping(mapping_id: str, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await conn.execute('DELETE FROM category_mapping WHERE id = $1', mapping_id)
    return {"success": True}
