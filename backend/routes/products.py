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
async def get_categories(supplier_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("""SELECT DISTINCT category FROM products
            WHERE category IS NOT NULL AND BTRIM(category) != ''
            AND ($1::text IS NULL OR supplier_id = $1)
            ORDER BY category""", supplier_id if supplier_id and supplier_id != 'all' else None)
        return {"categories": [r["category"] for r in rows]}
@router.get("/products/brands")
async def get_brands(supplier_id: Optional[str] = None, category: Optional[str] = None, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("""SELECT DISTINCT brand FROM products
            WHERE brand IS NOT NULL AND BTRIM(brand) != ''
            AND ($1::text IS NULL OR supplier_id = $1)
            AND ($2::text IS NULL OR category = $2)
            ORDER BY brand""", supplier_id if supplier_id and supplier_id != 'all' else None,
            category if category and category != 'all' else None)
        return {"brands": [r["brand"] for r in rows]}


def build_supplier_workbook(rows):
    """Produce typed Excel cells; supplier-provided strings are never formulas."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.utils import get_column_letter
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Products'
    sheet.append(['sl_no', 'product_name', 'sku', 'variants', 'brand',
                  'supplier_category', 'supplier_price', 'retail_price'])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='17365D')
        cell.alignment = Alignment(vertical='center')
    sheet.row_dimensions[1].height = 25
    for index, row in enumerate(rows, 1):
        sheet.append([index, row.get('product_name') or '', row.get('supplier_sku') or '',
                      row.get('variant_count', 0), row.get('brand') or '',
                      row.get('category') or '', row.get('export_cost'), row.get('export_retail')])
        for column in (2, 3, 5, 6):
            cell = sheet.cell(index + 1, column)
            cell.value = ILLEGAL_CHARACTERS_RE.sub('', str(cell.value or ''))[:32767]
            cell.data_type = 's'
            cell.number_format = '@'
        for column in (7, 8):
            sheet.cell(index + 1, column).number_format = '#,##0.00'
    for column, width in enumerate((9, 56, 25, 14, 28, 56, 20, 20), 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


@router.get('/products/export.xlsx')
async def export_supplier_products(supplier_id: str = Query(..., min_length=1), user: dict = Depends(get_current_user)):
    import asyncio
    import math
    import re
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse
    from pricing_rules import ensure_pricing_schema, category_policies, apply_category_policy, pricing_policy, price_for
    from product_readiness import load_readiness

    if supplier_id == 'all':
        raise HTTPException(400, 'Select a supplier before exporting')
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            supplier = await conn.fetchrow('SELECT supplier_name FROM suppliers WHERE id=$1', supplier_id)
            if not supplier:
                raise HTTPException(404, 'Supplier not found')
            # Export the complete supplier catalogue, independent of page/search/visibility filters.
            products = [dict(row) for row in await conn.fetch("""SELECT p.*,
                (SELECT COUNT(*) FROM product_variants v WHERE v.product_id=p.id
                 AND v.is_active IS DISTINCT FROM FALSE) AS variant_count
                FROM products p WHERE p.supplier_id=$1
                ORDER BY LOWER(COALESCE(p.product_name,'')), p.supplier_sku, p.id""", supplier_id)]
            settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id='system_settings'")
            markup = settings['markup_percentage'] if settings and settings['markup_percentage'] is not None else 40
            policies = await category_policies(conn)
            for offset in range(0, len(products), 200):
                batch = products[offset:offset + 200]
                states = await load_readiness(conn, batch)
                for product in batch:
                    product['export_cost'] = None
                    product['export_retail'] = None
                    try:
                        cost = float(product.get('base_price'))
                        if math.isfinite(cost) and cost > 0:
                            product['export_cost'] = cost
                    except (TypeError, ValueError, OverflowError):
                        pass
                    state = states[product['id']]
                    priced = apply_category_policy(product, state['mapped_lightspeed_category_id'], policies)
                    try:
                        if product['export_cost'] is not None and not product.get('price_needs_review'):
                            policy = pricing_policy(priced, state['variants'], markup)
                            product['export_retail'] = price_for(product['export_cost'], policy)
                    except (TypeError, ValueError, OverflowError):
                        pass  # Keep every product; an uncomputable retail price stays blank.
    stream = await asyncio.to_thread(build_supplier_workbook, products)
    name = re.sub(r'[^A-Za-z0-9_-]+', '_', supplier['supplier_name'] or 'Supplier').strip('_') or 'Supplier'
    filename = name[:80] + '_products_' + datetime.now(timezone.utc).strftime('%Y-%m-%d') + '.xlsx'
    return StreamingResponse(stream, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename="' + filename + '"', 'Cache-Control': 'no-store'})

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
                    SELECT '/api/media/' || pm.id || '/content'
                    FROM product_media pm
                    WHERE pm.product_id = p.id
                    AND pm.media_type = 'image'
                    AND (COALESCE(pm.url,'')<>'' OR COALESCE(pm.image_base64,'')<>'')
                    ORDER BY
                        (COALESCE(pm.image_base64,'')<>'') DESC,
                        pm.is_primary DESC,
                        pm.created_at ASC
                    LIMIT 1
                ) AS thumbnail,
                NULL::text AS thumbnail_base64,
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
        media = []
        for row in media_rows:
            item = row_to_dict(row)
            item['stored_locally'] = bool(item.get('image_base64'))
            item['local_url'] = '/api/media/' + str(item['id']) + '/content' if item.get('media_type') == 'image' else None
            # Images are served by the image endpoint, not repeated in detail JSON.
            item.pop('image_base64', None)
            media.append(item)
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


