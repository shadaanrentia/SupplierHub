from outbound_history import record as record_outbound
"""Preprocessing routes: Lightspeed validation, category defaults, supplier scope and preview."""
import json
from export_safety import validate_prices, export_name
from product_readiness import load_readiness, public_state
from category_scope import destination_labels, in_category, category_rows
from size_order import size_key
from fastapi import Query
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
import deps
from deps import row_to_dict, new_id, utc_now, get_current_user, calculate_sale_price
from deps import get_admin_user
from pydantic import BaseModel
from typing import Literal, Optional
from pricing_rules import ensure_pricing_schema, pricing_summary, pricing_policy, price_for, number, category_policies, apply_category_policy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


async def catalog(conn, search='', supplier_id=None, lightweight=False, product_ids=None):
    columns = 'p.id,p.product_name,p.supplier_sku,p.supplier_id,p.category,p.brand,p.base_price,p.price_needs_review,p.lightspeed_sync_status,p.lightspeed_product_id,p.updated_at' if lightweight else 'p.*'
    return [row_to_dict(r) for r in await conn.fetch(f"SELECT {columns},s.supplier_name FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE (p.product_name ILIKE $1 OR p.supplier_sku ILIKE $1) AND ($2::varchar IS NULL OR p.supplier_id=$2) AND ($3::varchar[] IS NULL OR p.id=ANY($3)) ORDER BY p.updated_at DESC,p.id", '%'+search.strip()+'%', supplier_id, product_ids)]


def measurement_summary(variants, fallback):
    from shipping_measurements import source_measurements
    weight_count, dimensions_count, errors = 0, 0, []
    for v in variants:
        try:
            measurements=source_measurements(dict(v,category_shipping=fallback))
            weight_count+=int(bool(measurements.get('weight')))
            dimensions_count+=int(all(measurements.get(k) for k in ('dimensions_length','dimensions_width','dimensions_height')))
        except (ValueError,TypeError,KeyError) as exc:errors.append(str(exc))
    total=len(variants)
    weight_ready=bool(total) and weight_count==total
    dimensions_ready=bool(total) and dimensions_count==total
    status='complete' if weight_ready and dimensions_ready else ('dimensions_missing' if weight_ready else 'weight_missing' if dimensions_ready else 'missing')
    if errors:status='invalid'
    labels={'complete':'Complete','dimensions_missing':'Dimensions missing','weight_missing':'Weight missing','missing':'Measurements missing','invalid':'Measurements need review'}
    return {'status':status,'label':labels[status],'complete':status=='complete','total_variants':total,
        'variants_with_weight':weight_count,'variants_with_dimensions':dimensions_count,'errors':errors[:3]}


async def policy_catalog(conn,supplier_id=None):
    settings=await conn.fetchrow("SELECT lightspeed_store_id,markup_percentage FROM settings WHERE id='system_settings'")
    domain=str(settings['lightspeed_store_id'] or '').strip() if settings else ''
    markup=float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
    products=await catalog(conn,supplier_id=supplier_id,lightweight=True)
    states=await load_readiness(conn,products,include_assets=False)
    rules=await category_policies(conn)
    labels=await destination_labels(conn)
    entries=category_rows(products,states,labels)
    nodes=await conn.fetch("""SELECT d.supplier_id,d.path,d.category_id FROM supplier_taxonomy_destinations d
        WHERE d.store_domain=$1 AND ($2::varchar IS NULL OR d.supplier_id=$2)""",domain,supplier_id)
    for row in nodes:
        key=(row['supplier_id'],str(row['category_id']))
        if not row['category_id'] or key[1] not in labels:continue
        item=entries.setdefault(key,{'supplier_id':key[0],'category_id':key[1],
            'category_name':labels.get(key[1]) or 'Needs category mapping',
            'category_available':key[1] in labels,
            'path':labels.get(key[1]) or '', 'product_count':0,'supplier_categories':[], 'supplier_paths':[]})
        if row['path'] not in item['supplier_paths']:item['supplier_paths'].append(row['path'])
    for key,item in entries.items():
        rule=rules.get(key,{})
        item.update(mode=rule.get('pricing_mode') or 'global',value=rule.get('pricing_value'),**{k:rule.get(k) for k in ('weight_lb','length_in','width_in','height_in')})
        mode,value=item['mode'],item['value']
        item['pricing_label']=f'Global {markup:g}%' if mode=='global' else f'Category {float(value):g}%' if mode=='percentage' else f'Category base ${float(value):.2f}'
        item['measurements_configured']=all(item.get(k) is not None and float(item[k])>0 for k in ('weight_lb','length_in','width_in','height_in'))
    return sorted(entries.values(),key=lambda r:(r['supplier_id'],str(r['category_name'])))


@router.get('/category-policies')
async def get_category_policies(supplier_id: str=None,user=Depends(get_current_user)):
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        categories=await policy_catalog(conn,supplier_id)
    return {'categories':categories}


@router.get('/preprocessing/products')
async def get_preprocessing_products(page: int=Query(1,ge=1), limit: int=Query(50,ge=1,le=100), status: str=None, search: str='', supplier_id: str=None, category_id: str=None, oversized: bool=False, user: dict=Depends(get_current_user)):
    request_started=time.perf_counter()
    await ensure_pricing_schema()
    if status not in (None,'all','ready','invalid','synced','images_pending'): raise HTTPException(400,'Unknown status filter')
    async with deps.pool.acquire() as conn:
        settings=await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id='system_settings'")
        markup=float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
        products=await catalog(conn,search,supplier_id,lightweight=True)
        states=await load_readiness(conn,products,include_assets=False)
        policies=await category_policies(conn)
        from category_scope import destination_labels
        destination_names=await destination_labels(conn)
    result=[]
    for product in products:
        state=states[product['id']]
        product=apply_category_policy(product,state['mapped_lightspeed_category_id'],policies)
        if state['excluded_from_queue'] or not in_category(state,category_id): continue
        if oversized and state['variants_count'] < 200: continue
        if status not in (None,'all') and state['status']!=status: continue
        product.update(public_state(state))
        product['can_update']=bool(state['is_valid'] and state['status']=='synced')
        product['lightspeed_category_name']=destination_names.get(str(state['mapped_lightspeed_category_id']))
        product['product_name']=export_name(product.get('product_name'),product.get('supplier_sku'))
        cost=float(product.get('base_price') or 0)
        product.update(cost_price=cost,markup_percentage=markup)
        try:
            product.update(pricing_summary(product, state['variants'], markup))
        except ValueError as exc:
            product.update(calculated_sale_price=None, retail_price_min=None, retail_price_max=None, pricing_label='Pricing needs review', pricing_error=str(exc), is_valid=False, can_sync=False, can_update=False)
        result.append(product)
    offset=(page-1)*limit
    visible=result[offset:offset+limit]
    visible_ids=[p['id'] for p in visible]
    measurement_variants={}
    if visible_ids:
        async with deps.pool.acquire() as conn:
            # Full measurement metadata is needed only for products visible on this page.
            rows=await conn.fetch('SELECT * FROM product_variants WHERE product_id=ANY($1::varchar[]) AND is_active IS DISTINCT FROM FALSE',visible_ids)
        from sku_eligibility import eligible_variants
        for row in rows:
            measurement_variants.setdefault(row['product_id'],[]).append(dict(row))
        for product in visible:
            product['measurement_summary']=measurement_summary(eligible_variants(measurement_variants.get(product['id'],[])),product['category_shipping'])
    selectable=[p['id'] for p in result if p.get('can_sync') or p.get('can_update')]
    logger.info('Pre-processing list: matched=%s, returned=%s, elapsed=%.3fs',len(result),len(visible),time.perf_counter()-request_started)
    return {'products':visible,'total':len(result),'page':page,'limit':limit,'markup_percentage':markup,
            'selectable_ids':selectable,'ready_ids':[p['id'] for p in result if p.get('can_sync')]}


@router.get('/preprocessing/ready-ids')
async def preprocessing_ready_ids(search: str='', status: str=None, supplier_id: str=None, include_synced: bool=False, category_id: str=None, oversized: bool=False, user: dict=Depends(get_current_user)):
    await ensure_pricing_schema()
    if status not in (None,'all','ready','invalid','synced','images_pending'): raise HTTPException(400,'Unknown status filter')
    async with deps.pool.acquire() as conn:
        products=await catalog(conn,search,supplier_id,lightweight=True)
        states=await load_readiness(conn,products,include_assets=False)
        policies=await category_policies(conn)
        settings=await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id='system_settings'")
    markup=float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
    selected=[];selectable=[]
    for product in products:
        state=states[product['id']]
        if not in_category(state,category_id) or state['excluded_from_queue'] or (status not in (None,'all') and state['status']!=status): continue
        if oversized and state['variants_count'] < 200: continue
        product=apply_category_policy(product,state['mapped_lightspeed_category_id'],policies)
        try: pricing_summary(product,state['variants'],markup)
        except ValueError: continue
        can_update=state['is_valid'] and state['status']=='synced'
        if state['can_sync'] or can_update: selectable.append(product['id'])
        if state['can_sync'] or (include_synced and can_update): selected.append(product['id'])
    return {'product_ids':selected,'selectable_ids':selectable}


@router.get('/preprocessing/summary')
async def get_preprocessing_summary(supplier_id: str=None, category_id: str=None, user: dict=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        products=await catalog(conn,supplier_id=supplier_id,lightweight=True)
        states=await load_readiness(conn,products,include_assets=False)
    products=[p for p in products if not states[p['id']]['excluded_from_queue'] and in_category(states[p['id']],category_id)]
    values=[states[p['id']] for p in products]; total=len(values)
    mapped=sum(bool(s['mapped_lightspeed_category_id']) and s.get('category_available',True) for s in values)
    with_images=sum(bool(s['images_count']) for s in values)
    with_price=sum(not p.get('price_needs_review') and float(p.get('base_price') or 0)>0 for p in products)
    return {'total_products':total,'total_variants':sum(s['variants_count'] for s in values),
        'category_mapping':{'mapped':mapped,'unmapped':total-mapped},
        'images':{'with_images':with_images,'without_images':total-with_images},
        'pricing':{'with_price':with_price,'without_price':total-with_price},
        'sync_status':{'ready':sum(s['status']=='ready' for s in values),'synced':sum(s['status']=='synced' for s in values),
                       'pending':sum(s['status']=='invalid' for s in values),'failed':sum(p.get('lightspeed_sync_status')=='failed' for p in products)}}


@router.post("/preprocessing/recalculate-prices")
async def recalculate_all_prices(user: dict = Depends(get_current_user)):
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
        products = await catalog(conn,lightweight=True)
        states = await load_readiness(conn,products,include_assets=False)
        policies = await category_policies(conn)
        updated = 0
        for p in products:
            variants = states[p['id']]['variants']
            from sku_eligibility import eligible_variants
            variants = eligible_variants(variants)
            if not variants: continue
            p = apply_category_policy(p,states[p['id']]['mapped_lightspeed_category_id'],policies)
            summary = pricing_summary(p, variants, markup)
            cost = summary['pricing_anchor_cost']; sale_price = summary['calculated_sale_price']
            await conn.execute('INSERT INTO product_sync_status (id, product_id, cost_price, sale_price, updated_at) VALUES ($1,$2,$3,$4,NOW()) ON CONFLICT (product_id) DO UPDATE SET cost_price=EXCLUDED.cost_price, sale_price=EXCLUDED.sale_price, updated_at=NOW()',
                new_id(), p['id'], cost, sale_price)
            updated += 1
            await conn.execute("UPDATE products SET lightspeed_sync_status=CASE WHEN lightspeed_sync_status='images_pending' THEN 'images_pending' ELSE 'pending' END,updated_at=NOW() WHERE id=$1", p['id'])
        return {"success": True, "updated": updated, "markup_percentage": markup}


class CategoryPolicy(BaseModel):
    supplier_id: str
    category_id: str
    mode: Literal['global','percentage','direct'] = 'global'
    value: Optional[float] = None
    weight_lb: Optional[float] = None
    length_in: Optional[float] = None
    width_in: Optional[float] = None
    height_in: Optional[float] = None


@router.get('/category-policy')
@router.get('/preprocessing/category-policy')
async def get_category_policy(supplier_id: str, category_id: str, user=Depends(get_current_user)):
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        policies=await category_policies(conn)
    rule=policies.get((supplier_id,category_id),{})
    return {'mode':rule.get('pricing_mode') or 'global','value':rule.get('pricing_value'),
        **{k:rule.get(k) for k in ('weight_lb','length_in','width_in','height_in')}}


@router.put('/category-policy')
@router.put('/preprocessing/category-policy')
async def set_category_policy(body: CategoryPolicy, user=Depends(get_admin_user)):
    await ensure_pricing_schema()
    try:
        value=None if body.mode=='global' else number(body.value,'Pricing value',body.mode=='percentage')
        if body.mode=='direct' and value<0.01:raise ValueError('Base selling price must be at least $0.01')
        values={k:None if getattr(body,k) is None else number(getattr(body,k),k) for k in ('weight_lb','length_in','width_in','height_in')}
        if value is not None and value>9999999999:raise ValueError('Pricing value is too large')
        if any(v is not None and v>9999999999 for v in values.values()):raise ValueError('Shipping value is too large')
        if any(v is not None and v<0.0001 for v in values.values()):raise ValueError('Shipping values must be at least 0.0001')
        dims=[values[k] for k in ('length_in','width_in','height_in')]
        if any(v is not None for v in dims) and not all(v is not None for v in dims):raise ValueError('Enter all three dimensions or leave all blank')
    except ValueError as exc:raise HTTPException(400,str(exc))
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval('SELECT 1 FROM suppliers WHERE id=$1',body.supplier_id):raise HTTPException(404,'Supplier not found')
            products=await catalog(conn,supplier_id=body.supplier_id,lightweight=True)
            # Prevent an edit from changing an in-flight export; lock the supplier's products.
            for product in sorted(products,key=lambda p:p['id']):
                if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtext($1))','export-review:'+product['id']):raise HTTPException(409,'A supplier product is exporting; try again when it finishes')
            states=await load_readiness(conn,products,include_assets=False)
            affected=[p['id'] for p in products if str(states[p['id']]['mapped_lightspeed_category_id'] or '')==body.category_id]
            settings=await conn.fetchrow("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'")
            domain=str(settings['lightspeed_store_id'] or '').strip() if settings else ''
            if not domain:raise HTTPException(400,'Configure a Lightspeed store first')
            entries=await policy_catalog(conn,body.supplier_id)
            if not any(r['category_id']==body.category_id for r in entries):raise HTTPException(400,'Choose a published category for this supplier')
            if await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=ANY($1::varchar[]) AND status='running'",affected):raise HTTPException(409,'An export job is running for this category')
            await conn.execute("""INSERT INTO supplier_category_policies(store_domain,supplier_id,category_id,pricing_mode,pricing_value,weight_lb,length_in,width_in,height_in)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(store_domain,supplier_id,category_id) DO UPDATE SET
                pricing_mode=EXCLUDED.pricing_mode,pricing_value=EXCLUDED.pricing_value,weight_lb=EXCLUDED.weight_lb,
                length_in=EXCLUDED.length_in,width_in=EXCLUDED.width_in,height_in=EXCLUDED.height_in,updated_at=NOW()""",
                domain,body.supplier_id,body.category_id,body.mode,value,values['weight_lb'],values['length_in'],values['width_in'],values['height_in'])
            await conn.execute("UPDATE products SET lightspeed_sync_status=CASE WHEN lightspeed_sync_status='images_pending' THEN 'images_pending' ELSE 'pending' END,updated_at=NOW() WHERE id=ANY($1::varchar[])",affected)
            await conn.execute("UPDATE product_sync_status SET sync_status='pending',updated_at=NOW() WHERE product_id=ANY($1::varchar[])",affected)
    return {'success':True,'affected_products':len(affected)}


@router.put('/preprocessing/products/{product_id}/pricing')
async def removed_product_pricing(product_id: str,user=Depends(get_admin_user)):
    raise HTTPException(410,'Product pricing is removed. Use category defaults in Category Mapping.')


@router.post('/preprocessing/validate-products')
async def validate_products_for_sync(data: dict=None, user: dict=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        products=await catalog(conn,supplier_id=(data or {}).get('supplier_id'),lightweight=True)
        selected=(data or {}).get('product_ids',[])
        if selected: products=[p for p in products if p['id'] in selected]
        states=await load_readiness(conn,products,include_assets=False)
    valid=sum(s['is_valid'] for s in states.values())
    return {'success':True,'total':len(products),'validated':valid,'invalid':len(products)-valid}


@router.post("/preprocessing/sync-to-odoo")
@record_outbound('sync_preprocessed_to_odoo')
async def sync_preprocessed_to_odoo(data: dict = None, user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    product_ids = data.get('product_ids', []) if data else []
    sync_all = data.get('sync_all', False) if data else False
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row: raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings['markup_percentage']) if settings.get('markup_percentage') is not None else 40.0
        odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
        conn_test = odoo.test_connection()
        if not conn_test.get('connected'): raise HTTPException(400, f"Odoo connection failed: {conn_test.get('message')}")
        if sync_all:
            products = await conn.fetch('SELECT p.*, cm.odoo_category_id, pss.sale_price FROM products p INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name LEFT JOIN product_sync_status pss ON p.id = pss.product_id WHERE cm.odoo_category_id IS NOT NULL AND p.base_price > 0 AND (p.odoo_sync_status != \'synced\' OR p.odoo_sync_status IS NULL)')
        elif product_ids:
            products = await conn.fetch('SELECT p.*, cm.odoo_category_id, pss.sale_price FROM products p LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name LEFT JOIN product_sync_status pss ON p.id = pss.product_id WHERE p.id = ANY($1)', product_ids)
        else:
            return {"success": False, "error": "No products specified"}
        synced = 0; failed = 0; errors = []
        for p in products:
            product = row_to_dict(p)
            try:
                cost = float(product.get('base_price') or 0)
                sale_price = product.get('sale_price') or calculate_sale_price(cost, markup)
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
                odoo_data = {
                    'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
                    'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
                    'category_id': product.get('odoo_category_id'), 'default_category': 'SanMar Apparel',
                    'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(i) for i in images],
                }
                result = odoo.create_or_update_product(odoo_data)
                if result.get('success'):
                    await conn.execute('UPDATE products SET odoo_sync_status=\'synced\', odoo_product_id=$1, calculated_sale_price=$2, updated_at=NOW() WHERE id=$3',
                        str(result.get('odoo_id','')), sale_price, product['id'])
                    await conn.execute('UPDATE product_sync_status SET sync_status=\'synced\', odoo_product_id=$1, last_sync_date=NOW(), updated_at=NOW() WHERE product_id=$2',
                        str(result.get('odoo_id','')), product['id'])
                    synced += 1
                else:
                    await conn.execute('UPDATE products SET odoo_sync_status=\'failed\', updated_at=NOW() WHERE id=$1', product['id'])
                    failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': result.get('error')})
            except Exception as e:
                logger.error(f"Error syncing {product.get('supplier_sku')}: {e}")
                failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': str(e)})
        return {"success": True, "total": len(products), "synced": synced, "failed": failed, "errors": errors[:10]}


def can_export_selected(state, explicit_selection=False):
    # Automatic batches keep their existing scope; synced updates require selection.
    return bool(state.get('can_sync') or (explicit_selection and state.get('is_valid') and state.get('status')=='synced'))


def export_is_busy(exc):
    return 'This product is already exporting' in str(exc)


async def recorded_export(ls,product,variants,images,markup,category_id):
    """Record Pre-processing exports in the same history shown by Export Review."""
    from export_safety import export_product
    job_id=new_id()
    async with deps.pool.acquire() as conn:
        await conn.execute("INSERT INTO lightspeed_review_jobs(id,product_id,store_domain,kind,status) VALUES($1,$2,$3,'preprocessing-sync','running')",job_id,product['id'],ls.domain_prefix)
    try:
        result=await export_product(ls,product,variants,images,markup,category_id)
    except Exception as exc:
        status='skipped' if export_is_busy(exc) else 'failed'
        async with deps.pool.acquire() as conn:
            await conn.execute('UPDATE lightspeed_review_jobs SET status=$2,result=$3::jsonb,updated_at=NOW() WHERE id=$1',job_id,status,json.dumps({'success':False,'error':str(exc),'reason':'already_syncing' if status=='skipped' else 'export_error'}))
        raise
    status='images_pending' if result.get('success') and result.get('image_warnings') else 'completed' if result.get('success') else 'failed'
    async with deps.pool.acquire() as conn:
        await conn.execute('UPDATE lightspeed_review_jobs SET status=$2,result=$3::jsonb,updated_at=NOW() WHERE id=$1',job_id,status,json.dumps(result,default=str))
    return result


@router.post('/preprocessing/sync-to-lightspeed', status_code=202)
async def sync_preprocessed_to_lightspeed(data: dict=None, user: dict=Depends(get_current_user)):
    from lightspeed_jobs import enqueue
    return await enqueue(data or {}, user)


async def sync_products_now(data: dict=None, user: dict=None):
    await ensure_pricing_schema()
    from routes.lightspeed import _get_ls_service
    from export_safety import export_product
    ls=await _get_ls_service()
    if ls.mock_mode: raise HTTPException(400,'Configure Lightspeed first')
    supplier_id=(data or {}).get('supplier_id') or None
    selected=(data or {}).get('product_ids',[])
    all_ready=(data or {}).get('sync_all',False)
    if not selected and not all_ready: raise HTTPException(400,'Select products first')
    async with deps.pool.acquire() as conn:
        settings=await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id='system_settings'")
        markup=float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
        if supplier_id and not await conn.fetchval('SELECT 1 FROM suppliers WHERE id=$1',supplier_id):raise HTTPException(404,'Supplier not found')
        candidates=await catalog(conn,supplier_id=supplier_id,lightweight=True,product_ids=selected or None)
        if selected and set(selected)-{p['id'] for p in candidates}:raise HTTPException(400,'Selected products do not belong to the selected supplier or no longer exist')
        if selected: candidates=[p for p in candidates if p['id'] in selected]
        states=await load_readiness(conn,candidates,include_assets=False)
        products=[p for p in candidates if can_export_selected(states[p['id']],bool(selected))]
        skipped=[{'product_id':p['id'],'sku':p.get('supplier_sku'),'error':'; '.join(states[p['id']]['validation_errors']) or 'Already synced'} for p in candidates if not can_export_selected(states[p['id']],bool(selected))]
    synced,errors,needs_review=0,[],[]
    for product in products:
        # Recheck source state immediately before each write; stale UI cannot bypass it.
        try:
            async with deps.pool.acquire() as conn:
                current=await conn.fetchrow('SELECT p.*,s.supplier_name FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=$1',product['id'])
                if not current: raise ValueError('Product was removed')
                product=row_to_dict(current)
                state=(await load_readiness(conn,[product]))[product['id']]
            if supplier_id and product.get('supplier_id') != supplier_id: raise ValueError('Product supplier changed; reload Pre-processing')
            if not can_export_selected(state,bool(selected)): raise ValueError('; '.join(state['validation_errors']) or 'Already synced')
            if not in_category(state,(data or {}).get('category_id')): raise ValueError('Product mapping changed; no longer in the selected Lightspeed category')
            product['lightspeed_category_id']=state['mapped_lightspeed_category_id']
            # Full Sync Selected must reconcile destinations even when only images were pending.
            # Image-only repair remains an explicit Export Review action.
            result=await recorded_export(ls,product,state['variants'],state['images'],markup,state['mapped_lightspeed_category_id'])
            async with deps.pool.acquire() as conn:
                if result.get('success'):
                    warnings=result.get('image_warnings') or []
                    await conn.execute("UPDATE products SET lightspeed_product_id=$2,lightspeed_sync_status=$3,updated_at=NOW() WHERE id=$1",product['id'],str(result['lightspeed_id']),'images_pending' if warnings else 'synced')
                    if warnings: needs_review.append({'product_id':product['id'],'sku':product.get('supplier_sku'),'error':'; '.join(warnings)})
                    else: synced+=1
                else:
                    await conn.execute("UPDATE products SET lightspeed_sync_status='failed',updated_at=NOW() WHERE id=$1",product['id'])
                    errors.append({'product_id':product['id'],'sku':product.get('supplier_sku'),'error':result.get('error')})
        except Exception as exc:
            if export_is_busy(exc):
                skipped.append({'product_id':product['id'],'sku':product.get('supplier_sku'),'error':'Already syncing; existing export left unchanged','reason':'already_syncing'})
                continue
            async with deps.pool.acquire() as conn:
                await conn.execute("UPDATE products SET lightspeed_sync_status='failed',updated_at=NOW() WHERE id=$1",product['id'])
            logger.exception('Lightspeed export failed for %s',product.get('supplier_sku'))
            errors.append({'product_id':product['id'],'sku':product.get('supplier_sku'),'error':str(exc)})
    return {'success':not errors and not needs_review,'total':len(products),'synced':synced,'failed':len(errors),'needs_review':0,'images_pending':len(needs_review),'skipped':len(skipped),'errors':errors[:50],'image_pending_products':needs_review[:50],'skipped_products':skipped[:50]}


@router.get("/preprocessing/product/{product_id}/preview")
async def preview_product_for_odoo(product_id: str, user: dict = Depends(get_current_user)):
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings and settings['markup_percentage'] is not None else 40.0
        product = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
        if not product: raise HTTPException(404, "Product not found")
        product = row_to_dict(product)
        readiness=(await load_readiness(conn,[product]))[product_id]
        variants = readiness['variants']
        images = readiness['images']
        product=apply_category_policy(product,readiness['mapped_lightspeed_category_id'],await category_policies(conn))
        policy = pricing_policy(product, variants, markup)
        cost_price = policy['anchor_cost']; sale_price = price_for(cost_price, policy)
        preview = {
            "product_template": {
                "name": export_name(product.get('product_name'),product.get('supplier_sku')), "default_code": product.get('supplier_sku'),
                "description": product.get('description'), "list_price": sale_price, "standard_price": cost_price,
                "categ_id": readiness['mapped_lightspeed_category_id'],
                "category_name": readiness.get('mapped_category_name') or "Not Mapped",
                "type": "product", "sale_ok": True, "purchase_ok": True,
            },
            "attributes": {
                "colors": list(set(v['color'] for v in variants if v.get('color'))),
                "sizes": sorted(set(v['size'] for v in readiness['variants'] if v.get('size')),key=size_key),
            },
            "variants": [{"sku": v['variant_sku'], "color": v.get('color'), "size": v.get('size'), "price": float(v['price']), "retail_price": price_for(v['price'],policy), "inventory": v.get('inventory',0)} for v in variants],
            "images": [{"url": img['url'], "type": img.get('media_type','image'), "is_primary": img.get('is_primary',False)} for img in images],
            "validation": {"is_valid": bool(readiness['mapped_lightspeed_category_id'] and cost_price > 0), "errors": []}
        }
        preview['validation']={'is_valid':readiness['is_valid'],'errors':readiness['validation_errors']}
        return preview








@router.get('/preprocessing/categories')
async def preprocessing_categories(supplier_id: str=None,user=Depends(get_current_user)):
    """Real Lightspeed hierarchy choices; stale saved IDs are not category options."""
    await ensure_pricing_schema()
    async with deps.pool.acquire() as conn:
        products=await catalog(conn,supplier_id=supplier_id,lightweight=True)
        states=await load_readiness(conn,products,include_assets=False)
        snapshot=await conn.fetchval("""SELECT categories FROM lightspeed_category_snapshots
            WHERE LOWER(BTRIM(store_domain))=(SELECT LOWER(BTRIM(lightspeed_store_id))
            FROM settings WHERE id='system_settings') ORDER BY synced_at DESC NULLS LAST LIMIT 1""")
    from category_tree import category_choices
    return {'categories':category_choices(snapshot or [],products,states)}
