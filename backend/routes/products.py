"""Product routes: list, detail, selection, bulk ops, delete."""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from uuid import UUID
import deps
from deps import row_to_dict, new_id, utc_now, get_current_user, get_admin_user
from models import ProductSelectRequest, BulkSelectRequest, BulkDeleteRequest
router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
@router.get("/products/categories")
async def get_categories(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return {"categories": [r["category"] for r in rows]}
@router.get("/products/brands")
async def get_brands(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != '' ORDER BY brand")
        return {"brands": [r["brand"] for r in rows]}
@router.get("/products")
async def get_products(
    supplier_id: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    search: Optional[str] = None,
    selected: Optional[bool] = None,
    odoo_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    async with deps.pool.acquire() as conn:
        conditions = []
        values = []
        param_idx = 1
        if supplier_id:
            conditions.append(f"p.supplier_id = ${param_idx}")
            values.append(supplier_id)
            param_idx += 1
        if category and category != "all":
            conditions.append(f"p.category = ${param_idx}")
            values.append(category)
            param_idx += 1
        if brand and brand != "all":
            conditions.append(f"p.brand = ${param_idx}")
            values.append(brand)
            param_idx += 1
        if search:
            conditions.append(f"(p.product_name ILIKE ${param_idx} OR p.supplier_sku ILIKE ${param_idx})")
            values.append(f"%{search}%")
            param_idx += 1
        if selected is not None:
            conditions.append(f"p.selected_for_odoo = ${param_idx}")
            values.append(selected)
            param_idx += 1
        if odoo_status and odoo_status != "all":
            conditions.append(f"p.odoo_sync_status = ${param_idx}")
            values.append(odoo_status)
            param_idx += 1
        conditions.append("""
            (
                p.base_price IS NOT NULL
                AND p.base_price > 0
            )
        """)
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM product_media pm
                WHERE pm.product_id = p.id
                AND pm.media_type = 'image'
                AND (
                    (pm.url IS NOT NULL AND pm.url != '')
                    OR
                    (pm.image_base64 IS NOT NULL AND pm.image_base64 != '')
                )
            )
        """)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM products p
            WHERE {where_clause}
            """,
            *values
        )
        offset = (page - 1) * limit
        limit_param = param_idx
        offset_param = param_idx + 1
        query = f"""
            SELECT
                p.*,
                s.supplier_name,
                (
                    SELECT pm.url
                    FROM product_media pm
                    WHERE pm.product_id = p.id
                    AND pm.media_type = 'image'
                    AND pm.url IS NOT NULL
                    AND pm.url != ''
                    ORDER BY
                        pm.is_primary DESC,
                        pm.created_at ASC
                    LIMIT 1
                ) AS thumbnail,
                (
                    SELECT pm.image_base64
                    FROM product_media pm
                    WHERE pm.product_id = p.id
                    AND pm.media_type = 'image'
                    AND pm.image_base64 IS NOT NULL
                    AND pm.image_base64 != ''
                    ORDER BY
                        pm.is_primary DESC,
                        pm.created_at ASC
                    LIMIT 1
                ) AS thumbnail_base64,
                (
                    SELECT COUNT(*)
                    FROM product_variants pv
                    WHERE pv.product_id = p.id
                ) AS variant_count,
                (
                    SELECT COUNT(*)
                    FROM product_media pm2
                    WHERE pm2.product_id = p.id
                    AND pm2.media_type = 'image'
                ) AS media_count
            FROM products p
            LEFT JOIN suppliers s
                ON p.supplier_id = s.id
            WHERE {where_clause}
            ORDER BY p.created_at DESC
            LIMIT ${limit_param}
            OFFSET ${offset_param}
        """
        query_values = list(values)
        query_values.extend([limit, offset])
        rows = await conn.fetch(
            query,
            *query_values
        )
        products = []
        for row in rows:
            product = row_to_dict(row)
            if product.get("thumbnail"):
                product["image"] = product["thumbnail"]
            elif product.get("thumbnail_base64"):
                base64_image = product["thumbnail_base64"]
                if not base64_image.startswith("data:image"):
                    base64_image = f"data:image/jpeg;base64,{base64_image}"
                product["image"] = base64_image
            else:
                product["image"] = None
            products.append(product)
        return {
            "products": products,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
@router.get("/products/{product_id}")
async def get_product(
    product_id: UUID,
    user: dict = Depends(get_current_user)
):
    async with deps.pool.acquire() as conn:
        db_info = await conn.fetchrow("""
            SELECT
                current_database() AS database_name,
                current_schema() AS schema_name,
                inet_server_addr() AS server_ip,
                inet_server_port() AS server_port
        """)
        logger.info(
            "PRODUCT DETAIL DEBUG | DB=%s | SCHEMA=%s | SERVER=%s:%s | ID=%s",
            db_info["database_name"],
            db_info["schema_name"],
            db_info["server_ip"],
            db_info["server_port"],
            product_id
        )
        product_id = str(product_id)
        row = await conn.fetchrow(
            """
            SELECT
                p.*,
                s.supplier_name
            FROM products p
            LEFT JOIN suppliers s
                ON p.supplier_id = s.id
            WHERE p.id = $1
            """,
            product_id
        )
        if not row:
            logger.error(
                "PRODUCT NOT FOUND | id=%s | database=%s",
                product_id,
                db_info["database_name"]
            )
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )
        product = row_to_dict(row)
        variant_rows = await conn.fetch(
            """
            SELECT *
            FROM product_variants
            WHERE product_id = $1
            ORDER BY variant_sku
            """,
            product_id
        )
        variants = [row_to_dict(v) for v in variant_rows]
        media_rows = await conn.fetch(
            """
            SELECT *
            FROM product_media
            WHERE product_id = $1
            ORDER BY is_primary DESC, created_at ASC
            """,
            product_id
        )
        media = [row_to_dict(m) for m in media_rows]
        settings = await conn.fetchrow(
            """
            SELECT preferred_warehouse
            FROM settings
            WHERE id = 'system_settings'
            """
        )
        preferred_warehouse = (
            settings["preferred_warehouse"]
            if settings and settings["preferred_warehouse"]
            else ""
        )
        for v in variants:
            warehouse_inventory = v.get(
                "warehouse_inventory",
                []
            )
            if isinstance(warehouse_inventory, str):
                try:
                    warehouse_inventory = json.loads(
                        warehouse_inventory
                    )
                except (json.JSONDecodeError, TypeError):
                    warehouse_inventory = []
            if isinstance(warehouse_inventory, list):
                for wh in warehouse_inventory:
                    if not isinstance(wh, dict):
                        continue
                    if wh.get("name") == preferred_warehouse:
                        v["inventory"] = wh.get(
                            "quantity",
                            0
                        )
                        v["warehouse_name"] = wh.get(
                            "name",
                            ""
                        )
                        break
            if "inventory" not in v:
                v["inventory"] = 0
        product["variants"] = variants
        product["media"] = media
        product["preferred_warehouse"] = preferred_warehouse
        return product
@router.post("/products/{product_id}/select-for-odoo")
async def toggle_selection(product_id: str, data: ProductSelectRequest, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        result = await conn.execute(
            "UPDATE products SET selected_for_odoo = $1, odoo_sync_status = $2, updated_at = $3 WHERE id = $4",
            data.selected, status, utc_now(), product_id
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "Product not found")
        return {"status": "updated", "selected_for_odoo": data.selected}
@router.post("/products/bulk-select")
async def bulk_select(data: BulkSelectRequest, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        await conn.execute(
            "UPDATE products SET selected_for_odoo = $1, odoo_sync_status = $2, updated_at = $3 WHERE id = ANY($4)",
            data.selected, status, utc_now(), data.product_ids
        )
        return {"status": "updated"}
@router.post("/products/{product_id}/select-for-lightspeed")
async def toggle_lightspeed_selection(product_id: str, data: ProductSelectRequest, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        result = await conn.execute(
            "UPDATE products SET selected_for_lightspeed = $1, lightspeed_sync_status = $2, updated_at = $3 WHERE id = $4",
            data.selected, status, utc_now(), product_id
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "Product not found")
        return {"status": "updated", "selected_for_lightspeed": data.selected}
@router.post("/products/bulk-select-lightspeed")
async def bulk_select_lightspeed(data: BulkSelectRequest, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        await conn.execute(
            "UPDATE products SET selected_for_lightspeed = $1, lightspeed_sync_status = $2, updated_at = $3 WHERE id = ANY($4)",
            data.selected, status, utc_now(), data.product_ids
        )
        return {"status": "updated"}
@router.post("/products/bulk-delete")
async def bulk_delete_products(data: BulkDeleteRequest, user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM product_variants WHERE product_id = ANY($1)",
            data.product_ids
        )
        await conn.execute(
            "DELETE FROM product_media WHERE product_id = ANY($1)",
            data.product_ids
        )
        result = await conn.execute(
            "DELETE FROM products WHERE id = ANY($1)",
            data.product_ids
        )
        deleted = int(result.split()[-1]) if result else 0
        return {"status": "deleted", "count": deleted}
@router.delete("/products/delete-all")
async def delete_all_products(user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        await conn.execute("DELETE FROM product_variants")
        await conn.execute("DELETE FROM product_media")
        await conn.execute("DELETE FROM products")
        return {"status": "deleted", "count": count}