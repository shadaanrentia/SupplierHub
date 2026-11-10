from catalogue_labels import display_product_labels, display_variant_labels
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
@router.get('/products/categories')
async def get_categories(supplier_id: Optional[str]=None,user:dict=Depends(get_current_user)):
    from catalog_filters import catalog_filter
    where,args,_=catalog_filter({'supplier_id':supplier_id})
    async with deps.pool.acquire() as conn:
        rows=await conn.fetch("SELECT DISTINCT CASE WHEN NULLIF(BTRIM(p.category),'') IS NULL OR LOWER(BTRIM(p.category))='uncategorized' THEN 'Uncategorized' ELSE BTRIM(p.category) END category FROM products p WHERE "+where+' ORDER BY category',*args)
    return {'categories':[r['category'] for r in rows]}


@router.get('/products/brands')
async def get_brands(supplier_id:Optional[str]=None,category:Optional[str]=None,user:dict=Depends(get_current_user)):
    from catalog_filters import catalog_filter
    where,args,_=catalog_filter({'supplier_id':supplier_id,'category':category})
    async with deps.pool.acquire() as conn:
        rows=await conn.fetch("SELECT DISTINCT CASE WHEN NULLIF(BTRIM(p.brand),'') IS NULL OR LOWER(BTRIM(p.brand))='unbranded' THEN 'Unbranded' ELSE BTRIM(p.brand) END brand FROM products p WHERE "+where+' ORDER BY brand',*args)
    return {'brands':[r['brand'] for r in rows]}


@router.get('/products/filter-options')
async def filter_options(supplier_id:Optional[str]=None,category:Optional[str]=None,brand:Optional[str]=None,user:dict=Depends(get_current_user)):
    from catalog_filters import catalog_filter
    from size_order import size_key
    where,args,_=catalog_filter({'supplier_id':supplier_id,'category':category,'brand':brand})
    async with deps.pool.acquire() as conn:
        rows=await conn.fetch("""SELECT DISTINCT BTRIM(COALESCE(v.color,'')) colour,
            BTRIM(COALESCE(v.size,'')) size FROM product_variants v JOIN products p ON p.id=v.product_id WHERE """+where,*args)
        unassigned=bool(await conn.fetchval('SELECT EXISTS(SELECT 1 FROM products p WHERE NOT EXISTS(SELECT 1 FROM suppliers s WHERE s.id=p.supplier_id))'))
    from media_links import normalize_colour_label
    colours={normalize_colour_label(r['colour']) for r in rows if r['colour']}
    return {'colours':sorted(colours,key=str.casefold),
            'sizes':sorted({r['size'] for r in rows if r['size']},key=size_key),'unassigned_supplier':unassigned}


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

    supplier_id=supplier_id.strip()
    if not supplier_id or supplier_id in ('all','__unassigned__'):
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
                states = await load_readiness(conn, batch, include_assets=False)
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
    images:str='', pricing:str='', stock:str='', colour:str='', size:str='',
    price_min:Optional[float]=None, price_max:Optional[float]=None,
    variants_min:Optional[int]=None, variants_max:Optional[int]=None,
    updated_from:str='',updated_to:str='',sort:str='newest',
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    async with deps.pool.acquire() as conn:
        from catalog_filters import catalog_filter, SAVED_INVENTORY
        try:where_clause,values,order_by=catalog_filter(locals())
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc
        param_idx=len(values)+1
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
                {SAVED_INVENTORY} AS inventory_total,
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
            ORDER BY {order_by}
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
            product = display_product_labels(row_to_dict(row))
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
        product = display_product_labels(row_to_dict(row))
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
        from inventory_selection import select_inventory
        variants = select_inventory(variants, preferred_warehouse, strict=False)
        from sku_eligibility import eligibility_reason
        from media_links import normalize_colour_label
        for variant in variants:
            reason = eligibility_reason(variant)
            variant["lightspeed_eligible"] = reason is None
            variant["lightspeed_eligibility_reason"] = reason
            variant["original_color"] = variant.get("color")
            variant["color"] = normalize_colour_label(variant.get("color"))
        product["variants"] = [display_variant_labels(v) for v in variants]
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






@router.get('/products/{product_id}/workbench')
async def product_workbench(product_id: UUID, user: dict=Depends(get_current_user)):
    """Saved supplier data plus computed export values; no live destination writes."""
    from pricing_rules import ensure_pricing_schema, category_policies, apply_category_policy, pricing_policy, price_for
    from product_readiness import load_readiness, public_state
    from category_scope import destination_labels
    from shipping_measurements import source_measurements
    product = await get_product(product_id,user)
    from product_history import mississauga_inventory
    product['variants'] = mississauga_inventory(product['variants'],product.get('preferred_warehouse'))
    product['preferred_warehouse'] = 'MISSISSAUGA/ON'
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        state=(await load_readiness(conn,[product]))[product['id']]
        labels=await destination_labels(conn)
        product=apply_category_policy(product,state['mapped_lightspeed_category_id'],await category_policies(conn))
        markup=await conn.fetchval("SELECT markup_percentage FROM settings WHERE id='system_settings'")
        product['readiness']=public_state(state)
        product['lightspeed_category_name']=labels.get(str(state['mapped_lightspeed_category_id']))
        try:
            policy=pricing_policy(product,state['variants'],markup if markup is not None else 40)
            product['computed_base_retail']=price_for(policy['anchor_cost'],policy)
        except ValueError as exc:
            policy=None;product['pricing_error']=str(exc)
        for variant in product['variants']:
            try:variant['computed_retail']=price_for(variant.get('price'),policy) if policy else None
            except ValueError:variant['computed_retail']=None
            try:variant['export_measurements']=source_measurements({**variant,'category_shipping':product['category_shipping']})
            except ValueError as exc:variant['measurement_error']=str(exc)

    return product

from product_history import router as product_history_router
router.include_router(product_history_router)
