"""Supplier sync jobs with durable progress, cooperative stop and safe retries."""
import asyncio
import contextlib
import json
import logging
import math
import re
import threading
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Body
import deps
from deps import create_sync_log, update_sync_log, row_to_dict, new_id, utc_now, get_current_user, running_syncs
from promostandards import PromoStandardsConnector, request_context
from multi_supplier.connector import make_connector

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api')
ACTIVE = ('running', 'stopping')
METHODS = {'products':'get_product', 'inventory':'get_inventory', 'pricing':'get_pricing',
           'media':'get_media', 'enrich_categories':'get_product'}
FATAL = {'ACCESS_DENIED','ENDPOINT','TLS','RATE_LIMIT','SOAP_FAULT'}
NETWORK = {'CONNECTION_RESET','TIMEOUT','UNAVAILABLE','INVALID_RESPONSE'}

def parse_skus(value):
    skus = list(dict.fromkeys(v.strip() for v in re.split(r'[,\s]+', value or '') if v.strip()))
    if len(skus) > 200 or any(len(v) > 200 for v in skus):
        raise HTTPException(400, 'Enter at most 200 supplier SKUs, each at most 200 characters.')
    return skus



async def init_sync_schema(conn):
    from bulk_data import init_bulk_schema
    await init_bulk_schema(conn)
    await conn.execute("ALTER TABLE product_media ADD COLUMN IF NOT EXISTS source_color TEXT DEFAULT ''; ALTER TABLE product_media ADD COLUMN IF NOT EXISTS source_part_ids JSONB DEFAULT '[]'::jsonb")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS supplier_sync_details (
            log_id VARCHAR(64) PRIMARY KEY REFERENCES sync_logs(id) ON DELETE CASCADE,
            parent_log_id VARCHAR(64), item_limit INTEGER NOT NULL DEFAULT 1500,
            stage TEXT NOT NULL DEFAULT 'Preparing', current_sku TEXT NOT NULL DEFAULT '',
            succeeded INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0, retries INTEGER NOT NULL DEFAULT 0,
            stop_requested BOOLEAN NOT NULL DEFAULT FALSE,
            heartbeat TIMESTAMP NOT NULL DEFAULT NOW(), owner TEXT,
            last_error JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE TABLE IF NOT EXISTS supplier_sync_items (
            log_id VARCHAR(64) NOT NULL REFERENCES sync_logs(id) ON DELETE CASCADE,
            stage TEXT NOT NULL, sku TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            error_code TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(), PRIMARY KEY(log_id,stage,sku)
        );
        ALTER TABLE supplier_sync_details ADD COLUMN IF NOT EXISTS product_skus JSONB NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE products ADD COLUMN IF NOT EXISTS price_needs_review BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS supplier_sync_items_status ON supplier_sync_items(log_id,status);
    ''')


async def expire_jobs(conn):
    # Only jobs created by this implementation are eligible; do not terminate unrelated exports.
    await conn.execute('''UPDATE sync_logs l SET status='interrupted',
        message='Worker heartbeat expired. Review results, then retry unfinished items.', end_time=NOW()
        FROM supplier_sync_details d WHERE l.id=d.log_id AND l.status IN ('running','stopping')
        AND d.heartbeat < NOW()-INTERVAL '180 seconds' ''')


def decode(value):
    return json.loads(value) if isinstance(value,str) else value


async def log_rows(conn, supplier_id=None, sync_type=None, limit=50, offset=0):
    rows=await conn.fetch('''SELECT l.*,d.stage,d.current_sku,d.succeeded,d.failed,d.skipped,d.retries,
        d.stop_requested,d.heartbeat,d.parent_log_id,d.last_error,
        (d.log_id IS NOT NULL) AS managed,
        (SELECT COUNT(*) FROM supplier_sync_items i WHERE i.log_id=l.id AND i.status IN ('failed','pending','running')) unfinished
        FROM sync_logs l LEFT JOIN supplier_sync_details d ON d.log_id=l.id
        WHERE ($1::text IS NULL OR l.supplier_id=$1) AND ($2::text IS NULL OR l.sync_type=$2)
        ORDER BY l.start_time DESC,l.id LIMIT $3 OFFSET $4''',supplier_id,sync_type,limit,offset)
    output=[]
    for row in rows:
        value=row_to_dict(row)
        value['last_error']=decode(value.get('last_error')) or {}
        output.append(value)
    return output


@router.get('/sync/logs')
async def get_sync_logs(supplier_id:Optional[str]=None,sync_type:Optional[str]=None,
                        limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await expire_jobs(conn)
        logs=await log_rows(conn,supplier_id,sync_type,limit,offset)
        active=await conn.fetch("SELECT id,supplier_id,supplier_name,sync_type,status FROM sync_logs WHERE status IN ('running','stopping') ORDER BY start_time")
    return {'logs':logs,'active_jobs':[row_to_dict(r) for r in active]}


@router.get('/sync/log/{log_id}')
async def get_sync_log_detail(log_id:str,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await expire_jobs(conn)
        row=await conn.fetchrow('SELECT * FROM sync_logs WHERE id=$1',log_id)
        if not row:raise HTTPException(404,'Sync log not found')
        details=await conn.fetchrow('SELECT * FROM supplier_sync_details WHERE log_id=$1',log_id)
        failures=await conn.fetch("SELECT stage,sku,status,error_code,message FROM supplier_sync_items WHERE log_id=$1 AND status IN ('failed','skipped') ORDER BY updated_at DESC LIMIT 100",log_id)
        running_items=await conn.fetch("SELECT stage,sku FROM supplier_sync_items WHERE log_id=$1 AND status='running' ORDER BY stage,sku LIMIT 20",log_id)
        counts=await conn.fetch('SELECT status,COUNT(*) count FROM supplier_sync_items WHERE log_id=$1 GROUP BY status',log_id)
    result=row_to_dict(row)
    if details:result.update(row_to_dict(details));result['last_error']=decode(result['last_error'])
    result['managed']=details is not None
    result['running_items']=[dict(r) for r in running_items]
    result['items']=[dict(r) for r in failures]
    result['item_counts']={r['status']:r['count'] for r in counts}
    return result


@router.post('/sync/stop/{task_id}')
async def stop_sync(task_id:str,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row=await conn.fetchrow('SELECT id,status FROM sync_logs WHERE id=$1',task_id)
        if row:
            if row['status'] not in ACTIVE:return {'status':row['status'],'task_id':task_id}
            changed=await conn.fetchval('UPDATE supplier_sync_details SET stop_requested=TRUE WHERE log_id=$1 RETURNING log_id',task_id)
            if changed:
                await conn.execute("UPDATE sync_logs SET status='stopping',message='Stop requested; waiting for the current bounded supplier call to finish.' WHERE id=$1 AND status='running'",task_id)
                runtime=running_syncs.get(task_id)
                if runtime:runtime['event'].set()
                return {'status':'stopping','task_id':task_id}
            # Compatibility for old export tasks tracked by supplier/type rather than log ID.
            full=await conn.fetchrow('SELECT supplier_id,sync_type FROM sync_logs WHERE id=$1',task_id)
            aliases=[f"{full['sync_type']}_{full['supplier_id']}",f"lightspeed_{full['supplier_id']}",f"odoo_{full['supplier_id']}"]
            for alias in aliases:
                if alias in running_syncs:
                    running_syncs[alias]['should_stop']=True
                    return {'status':'stopping','task_id':task_id}
            raise HTTPException(409,'This older job has no managed worker. Verify its process before restarting it.')
    if task_id in running_syncs:
        running_syncs[task_id]['should_stop']=True
        if 'event' in running_syncs[task_id]:running_syncs[task_id]['event'].set()
        return {'status':'stopping','task_id':task_id}
    raise HTTPException(404,'Sync job not found')


@router.get('/sync/status/{task_id}')
async def get_sync_status(task_id:str,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row=await conn.fetchrow('SELECT status FROM sync_logs WHERE id=$1',task_id)
    return {'status':row['status'] if row else 'not_found','task_id':task_id}


INDEPENDENT_STAGES = frozenset(('pricing', 'inventory', 'media'))
_supplier_request_slots = {}
_global_request_slots = asyncio.Semaphore(6)


def job_stages(kind):
    if kind == 'full':
        return frozenset(('products', 'pricing', 'inventory', 'media'))
    if kind == 'refresh':
        return INDEPENDENT_STAGES
    if kind in METHODS:
        return frozenset((kind,))
    return frozenset(('*',))


def jobs_conflict(first, second):
    # Only different data-only stages can share a supplier. Imports, category
    # enrichment, Bulk Data and legacy/export jobs retain exclusive access.
    a, b = job_stages(first), job_stages(second)
    return not (a <= INDEPENDENT_STAGES and b <= INDEPENDENT_STAGES and a.isdisjoint(b))


async def supplier_read(supplier_id, connector, stage, sku, log_id, event):
    slots = _supplier_request_slots.setdefault(supplier_id, asyncio.Semaphore(3))
    async with slots:
        async with _global_request_slots:
            await check_stop(log_id, event)
            return await asyncio.to_thread(getattr(connector, METHODS[stage]), sku)


async def reserve_job(supplier_id,kind,limit=1500,parent=None,existing_log=None,product_skus=None,include_skipped=False):
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','supplier-sync:'+supplier_id)
            await expire_jobs(conn)
            supplier=await conn.fetchrow('SELECT supplier_name FROM suppliers WHERE id=$1',supplier_id)
            if not supplier:raise HTTPException(404,'Supplier not found')
            active=await conn.fetch("SELECT id,sync_type FROM sync_logs WHERE supplier_id=$1 AND status IN ('running','stopping') AND ($2::text IS NULL OR id!=$2) ORDER BY start_time",supplier_id,existing_log)
            conflict=next((job for job in active if jobs_conflict(kind, job['sync_type'])), None)
            if conflict:raise HTTPException(409,f"A {conflict['sync_type']} job overlaps this operation. Wait or stop it first; different pricing, inventory and media jobs may run together.")
            log_id=existing_log or new_id()
            if not existing_log:
                await conn.execute("INSERT INTO sync_logs(id,supplier_id,supplier_name,sync_type,status,message,start_time,created_at) VALUES($1,$2,$3,$4,'running','Preparing supplier job...',NOW(),NOW())",log_id,supplier_id,supplier['supplier_name'],kind)
            await conn.execute('INSERT INTO supplier_sync_details(log_id,item_limit,parent_log_id,product_skus) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT DO NOTHING',log_id,limit,parent,json.dumps(product_skus or []))
            if parent:
                await conn.execute("INSERT INTO supplier_sync_items(log_id,stage,sku) SELECT $1,stage,sku FROM supplier_sync_items WHERE log_id=$2 AND (status IN ('failed','pending','running') OR ($3::boolean AND status='skipped')) ON CONFLICT DO NOTHING",log_id,parent,include_skipped)
    return log_id


async def launch(supplier_id,kind,background_tasks,limit=1500,skus=None):
    product_skus=parse_skus(skus)
    if product_skus and kind=='bulk_data':raise HTTPException(400, 'Bulk Data does not support individual SKU filtering')
    log_id=await reserve_job(supplier_id,kind,limit,product_skus=product_skus)
    background_tasks.add_task(run_job,supplier_id,log_id)
    return {'status':'started','log_id':log_id,'task_id':log_id}


# Specific /products/bulk route must precede /products/{supplier_id}.
@router.post('/sync/products/bulk')
async def sync_products_bulk(product_ids:List[str],sync_type:str=Query(...,pattern='^(pricing|inventory|media)$'),user=Depends(get_current_user)):
    if not product_ids or len(product_ids)>200:raise HTTPException(400,'Select between 1 and 200 products')
    result={'success':0,'failed':0,'skipped':0,'errors':[]}
    for product_id in dict.fromkeys(product_ids):
        try:
            item=await sync_one(product_id,sync_type)
        except HTTPException as exc:
            item={'success':False,'message':str(exc.detail),'error_code':'JOB_CONFLICT' if exc.status_code==409 else 'LOCAL_ERROR'}
        key='success' if item.get('success') else ('skipped' if item.get('status')=='skipped' else 'failed')
        result[key]+=1
        if not item.get('success'):result['errors'].append({'product_id':product_id,'message':item.get('message'),'error_code':item.get('error_code')})
    return result


@router.post('/sync/products/{supplier_id}')
async def sync_products(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'products',background_tasks,limit,skus)


@router.post('/sync/inventory/{supplier_id}')
async def sync_inventory(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'inventory',background_tasks,limit,skus)


@router.post('/sync/pricing/{supplier_id}')
async def sync_pricing(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'pricing',background_tasks,limit,skus)


@router.post('/sync/refresh/{supplier_id}')
async def refresh_details(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    """Pricing, inventory and media in parallel for already imported products."""
    return await launch(supplier_id,'refresh',background_tasks,limit,skus)


@router.post('/sync/media/{supplier_id}')
async def sync_media(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'media',background_tasks,limit,skus)


@router.post('/sync/full/{supplier_id}')
async def sync_full(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'full',background_tasks,limit,skus)


@router.post('/sync/all/{supplier_id}')
async def sync_all(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'full',background_tasks,limit,skus)


@router.post('/sync/bulk-data/{supplier_id}')
async def sync_bulk_data(supplier_id:str,background_tasks:BackgroundTasks,cache_only:bool=False,user=Depends(get_current_user)):
    log_id=await reserve_job(supplier_id,'bulk_data',1500)
    if cache_only:
        async with deps.pool.acquire() as conn:
            await conn.execute("UPDATE supplier_sync_details SET stage='Cached BulkData' WHERE log_id=$1",log_id)
    background_tasks.add_task(run_job,supplier_id,log_id)
    return {'status':'started','log_id':log_id,'task_id':log_id}


@router.get('/sync/bulk-data/{supplier_id}/cache')
async def bulk_cache_status(supplier_id:str,user=Depends(get_current_user)):
    from bulk_data import account_key
    async with deps.pool.acquire() as conn:
        supplier=await conn.fetchrow('SELECT * FROM suppliers WHERE id=$1',supplier_id)
        if not supplier:raise HTTPException(404,'Supplier not found')
        connector=make_connector(row_to_dict(supplier))
        if supplier.get('bulk_data_url'):connector.services['bulk_data']=supplier['bulk_data_url'].split('?')[0]
        key=account_key(connector)
        cache=await conn.fetchrow("SELECT fetched_at,source,jsonb_array_length(payload->'products') AS variants FROM supplier_bulk_cache WHERE supplier_id=$1 AND account_key=$2",supplier_id,key)
        quota=await conn.fetchval('SELECT next_allowed_at FROM supplier_bulk_quota WHERE account_key=$1',key)
    return {'cache':row_to_dict(cache) if cache else None,'next_allowed_at':str(quota) if quota else None}


@router.post('/sync/bulk-data/{supplier_id}/import-cache')
async def import_bulk_cache(supplier_id:str,xml:str=Body(...,embed=True),user=Depends(get_current_user)):
    from bulk_data import import_snapshot
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','supplier-sync:'+supplier_id)
            supplier=await conn.fetchrow('SELECT * FROM suppliers WHERE id=$1',supplier_id)
            if not supplier:raise HTTPException(404,'Supplier not found')
            active=await conn.fetchval("SELECT COUNT(*) FROM sync_logs WHERE supplier_id=$1 AND status IN ('running','stopping')",supplier_id)
            if active:raise HTTPException(409,'Stop or finish supplier jobs before importing a saved BulkData response')
            connector=make_connector(row_to_dict(supplier))
            if supplier.get('bulk_data_url'):connector.services['bulk_data']=supplier['bulk_data_url'].split('?')[0]
            try: counts=await import_snapshot(conn,supplier_id,connector,xml)
            except (ValueError, __import__('lxml.etree',fromlist=['XMLSyntaxError']).XMLSyntaxError) as error:
                raise HTTPException(400,'Invalid/incomplete BulkData XML; existing cache retained. '+str(error)[:250])
    return {'success':True,**counts,'message':'Complete response cached. Run BulkData with cache_only=true to import it; no supplier request is made.'}



@router.post('/sync/enrich-categories/{supplier_id}')
async def enrich_categories(supplier_id:str,background_tasks:BackgroundTasks,limit:int=Query(1500,ge=0,le=10000),skus:Optional[str]=None,user=Depends(get_current_user)):
    return await launch(supplier_id,'enrich_categories',background_tasks,limit,skus)


@router.post('/sync/retry/{log_id}')
async def retry_sync(log_id:str,background_tasks:BackgroundTasks,include_skipped:bool=False,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row=await conn.fetchrow('SELECT l.*,d.item_limit FROM sync_logs l JOIN supplier_sync_details d ON d.log_id=l.id WHERE l.id=$1',log_id)
        if not row:raise HTTPException(400,'Retry is available for jobs created by the new supplier worker')
        if row['status'] in ACTIVE:raise HTTPException(409,'Wait for the job to finish stopping')
        count=await conn.fetchval("SELECT COUNT(*) FROM supplier_sync_items WHERE log_id=$1 AND (status IN ('failed','pending','running') OR ($2::boolean AND status='skipped'))",log_id,include_skipped)
        if not count:raise HTTPException(400,'No unfinished items. Start a new sync if discovery failed before items were created.')
        if row['sync_type']=='bulk_data':raise HTTPException(400,'BulkData may be account limited; start it manually when the supplier allows it')
    new_log=await reserve_job(row['supplier_id'],row['sync_type'],row['item_limit'],parent=log_id,include_skipped=include_skipped)
    background_tasks.add_task(run_job,row['supplier_id'],new_log)
    return {'status':'started','log_id':new_log,'task_id':new_log}


class StopRequested(Exception):pass


async def check_stop(log_id,event):
    if event.is_set():raise StopRequested()
    async with deps.pool.acquire() as conn:
        row=await conn.fetchrow('SELECT l.status,d.stop_requested FROM sync_logs l JOIN supplier_sync_details d ON d.log_id=l.id WHERE l.id=$1',log_id)
    if not row or row['status'] not in ACTIVE or row['stop_requested']:
        event.set();raise StopRequested()


async def heartbeat(log_id,owner,event,runtime):
    while not event.is_set():
        await asyncio.sleep(2)
        async with deps.pool.acquire() as conn:
            row=await conn.fetchrow('SELECT l.status,d.stop_requested FROM sync_logs l JOIN supplier_sync_details d ON d.log_id=l.id WHERE l.id=$1',log_id)
            if not row or row['status'] not in ACTIVE or row['stop_requested']:
                event.set();return
            await conn.execute('UPDATE supplier_sync_details SET heartbeat=NOW() WHERE log_id=$1 AND owner=$2',log_id,owner)
            while runtime['retry_events']:
                info=runtime['retry_events'].pop(0)
                await conn.execute('UPDATE supplier_sync_details SET retries=retries+1 WHERE log_id=$1',log_id)
                await conn.execute("UPDATE sync_logs SET message=$2 WHERE id=$1 AND status='running'",log_id,f"Retry attempt {info['attempt']}: {info['message']}")


async def publish(log_id,message='',stage=None,sku=None,error=None,terminal=None):
    async with deps.pool.acquire() as conn:
        counts=await conn.fetch('SELECT status,COUNT(*) n FROM supplier_sync_items WHERE log_id=$1 GROUP BY status',log_id)
        c={r['status']:r['n'] for r in counts}
        processed=sum(c.get(k,0) for k in ('succeeded','failed','skipped'));total=sum(c.values())
        pct=int(processed/total*100) if total else (100 if terminal=='completed' else 0)
        await conn.execute('''UPDATE supplier_sync_details SET succeeded=$2,failed=$3,skipped=$4,
            stage=COALESCE($5,stage),current_sku=COALESCE($6,current_sku),
            last_error=COALESCE($7::jsonb,last_error),heartbeat=NOW() WHERE log_id=$1''',log_id,c.get('succeeded',0),c.get('failed',0),c.get('skipped',0),stage,sku,json.dumps(error) if error else None)
        if terminal:
            await conn.execute('UPDATE sync_logs SET status=$2,message=$3,progress=$4,total_items=$5,processed_items=$6,end_time=NOW() WHERE id=$1 AND status IN (\'running\',\'stopping\')',log_id,terminal,message,pct,total,processed)
        else:
            await conn.execute("UPDATE sync_logs SET message=$2,progress=$3,total_items=$4,processed_items=$5 WHERE id=$1 AND status IN ('running','stopping')",log_id,message,pct,total,processed)
    return c


def positive(value):
    try:return value is not None and math.isfinite(float(value)) and float(value)>0
    except (ValueError,TypeError,OverflowError):return False


def valid_quantity(value):
    try:
        n=float(value)
        return math.isfinite(n) and n>=0 and n.is_integer()
    except (ValueError,TypeError,OverflowError):return False


async def save_product(conn,supplier_id,sku,product):
    existing=await conn.fetchrow('SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2',supplier_id,sku)
    product_id=existing['id'] if existing else new_id()
    bulk_time=datetime.fromisoformat(product['_bulk_fetched_at']) if product.get('_bulk_fetched_at') else None
    if existing:
        # Product Data commonly omits pricing. Do not send zero to the price guard for an omitted field.
        await conn.execute('UPDATE products SET product_name=$1,description=CASE WHEN description_source=\'bulk_data\' AND $6::boolean=FALSE THEN description ELSE COALESCE(NULLIF($2,\'\'),description) END,brand=COALESCE(NULLIF($3,\'\'),brand),category=COALESCE(NULLIF($4,\'\'),category),last_synced=NOW(),updated_at=NOW() WHERE id=$5',product.get('product_name') or sku,product.get('description',''),product.get('brand',''),product.get('category',''),product_id,bool(product.get('_bulk_source')))
        if 'price' in product:
            if positive(product['price']):
                await conn.execute('UPDATE products SET base_price=$2,updated_at=NOW() WHERE id=$1 AND ($3::timestamptz IS NULL OR pricing_synced_at IS NULL OR pricing_synced_at<=$3)',product_id,float(product['price']),bulk_time)
            else:
                await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',product_id)
    else:
        await conn.execute('INSERT INTO products(id,supplier_id,supplier_sku,product_name,description,brand,category,base_price,last_synced,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,NOW(),NOW(),NOW())',product_id,supplier_id,sku,product.get('product_name') or sku,product.get('description',''),product.get('brand',''),product.get('category',''),float(product.get('price')) if positive(product.get('price')) else 0)
    seen=set()
    for variant in product.get('variants',[]):
        key=str(variant.get('variant_sku') or '').strip()
        if not key or key in seen:raise ValueError('Missing or duplicate variant SKU in supplier response')
        seen.add(key)
        old=await conn.fetchrow('SELECT id FROM product_variants WHERE product_id=$1 AND variant_sku=$2',product_id,key)
        if old:
            await conn.execute('UPDATE product_variants SET color=$2,size=$3,updated_at=NOW() WHERE id=$1',old['id'],variant.get('color',''),variant.get('size',''))
            if 'price' in variant:
                if positive(variant['price']):await conn.execute('UPDATE product_variants SET price=$2 WHERE id=$1 AND ($3::timestamptz IS NULL OR pricing_synced_at IS NULL OR pricing_synced_at<=$3)',old['id'],float(variant['price']),bulk_time)
                else:await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',product_id)
            if 'inventory' in variant and valid_quantity(variant['inventory']):await conn.execute('UPDATE product_variants SET inventory=$2 WHERE id=$1 AND ($3::timestamptz IS NULL OR inventory_synced_at IS NULL OR inventory_synced_at<=$3)',old['id'],int(float(variant['inventory'])),bulk_time)
        else:
            await conn.execute('INSERT INTO product_variants(id,product_id,variant_sku,color,size,price,inventory,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,NOW(),NOW())',new_id(),product_id,key,variant.get('color',''),variant.get('size',''),float(variant.get('price')) if positive(variant.get('price')) else 0,int(float(variant['inventory'])) if valid_quantity(variant.get('inventory')) else 0)
    return product_id


async def _apply_result(supplier_id,sku,stage,result):
    if not result.get('success'):
        return 'failed',result.get('error_code','SUPPLIER_ERROR'),result.get('error','Supplier request failed')
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','supplier-product:'+supplier_id+':'+sku)
            if stage=='products':
                product=result.get('product')
                if not product or not product.get('product_name'):return 'failed','EMPTY_RESPONSE','No usable product details returned'
                pid=await save_product(conn,supplier_id,sku,product)
                if result.get('import_only'):await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',pid)
                return 'succeeded','','Product details saved'
            row=await conn.fetchrow('SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2',supplier_id,sku)
            if not row:return 'failed','PRODUCT_MISSING','Product details have not been imported; refresh products first'
            product_id=row['id']
            if stage=='enrich_categories':
                category=(result.get('product') or {}).get('category') or result.get('category')
                if not category:return 'skipped','NO_CATEGORY','Supplier returned no category'
                await conn.execute('UPDATE products SET category=$2,updated_at=NOW() WHERE id=$1',product_id,category)
                return 'succeeded','','Category saved'
            field={'inventory':'inventory','pricing':'pricing','media':'media'}[stage]
            rows=result.get(field) or []
            if not rows:return 'skipped','EMPTY_RESPONSE',f'No {stage} records returned; existing data retained'
            changed=0;invalid=0
            if stage=='inventory':
                for item in rows:
                    if not item.get('part_id') or not valid_quantity(item.get('quantity_available')):
                        invalid+=1;continue
                    action=await conn.execute('UPDATE product_variants SET inventory=$1,warehouse_inventory=$2,inventory_synced_at=NOW(),updated_at=NOW() WHERE product_id=$3 AND variant_sku=$4',int(float(item['quantity_available'])),json.dumps(item.get('warehouses',[])),product_id,item['part_id'])
                    changed+=int(action!='UPDATE 0')
            elif stage=='pricing':
                valid_costs=[]
                for item in rows:
                    tiers=item.get('prices') or []
                    if any(not valid_quantity(v.get('min_quantity') or 0) for v in tiers):
                        invalid+=1
                        continue
                    price_rows=sorted(tiers,key=lambda v:float(v.get('min_quantity') or 0))
                    cost=price_rows[0].get('price') if price_rows else None
                    valid=positive(cost)
                    if not valid:
                        invalid+=1
                        continue
                    action=await conn.execute('UPDATE product_variants SET price=$1,pricing_synced_at=NOW(),updated_at=NOW() WHERE product_id=$2 AND variant_sku=$3',float(cost) if valid else 0,product_id,item.get('part_id',''))
                    changed+=int(action!='UPDATE 0')
                    if valid and action!='UPDATE 0':valid_costs.append(float(cost))
                if valid_costs:await conn.execute('UPDATE products SET base_price=$2,pricing_synced_at=NOW(),updated_at=NOW() WHERE id=$1',product_id,min(valid_costs))
                if invalid or result.get('import_only'):await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',product_id)
            elif stage=='media':
                from media_links import resolved_links
                local_variants=[dict(v) for v in await conn.fetch('SELECT variant_sku,color FROM product_variants WHERE product_id=$1 AND is_active IS DISTINCT FROM FALSE',product_id)]
                linked=0
                for item in rows:
                    url=str(item.get('url') or '').strip()
                    if not url.startswith(('https://','http://')):invalid+=1;continue
                    old=await conn.fetchval('SELECT id FROM product_media WHERE product_id=$1 AND url=$2',product_id,url)
                    source_colour,parts,associated=resolved_links(item,local_variants)
                    linked+=int(associated)

                    if not old:
                        kind=str(item.get('type') or item.get('media_type') or 'image').lower()
                        await conn.execute('INSERT INTO product_media(id,product_id,media_type,url,description,is_primary,created_at) VALUES($1,$2,$3,$4,$5,$6,NOW())',new_id(),product_id,kind,url,item.get('description',''),bool(item.get('is_primary',False)))
                        changed+=1
                    if associated or not old:
                        await conn.execute("UPDATE product_media SET source_color=$3,source_part_ids=$4::jsonb WHERE product_id=$1 AND url=$2", product_id,url,source_colour,json.dumps(parts))
                if not invalid:return 'succeeded','',f'{changed} media records added; existing URLs refreshed; {linked}/{len(rows)} images linked to local variants'
            if invalid:return 'failed','INVALID_DATA',f'{changed} records updated; {invalid} invalid records retained for review'
            if not changed:return 'skipped','UNMATCHED_PARTS','No matching local variant SKUs; existing data retained'
            return 'succeeded','',f'{changed} records updated'


async def _apply_result_with_metadata(supplier_id,sku,stage,result):
    status,code,message=await _apply_result(supplier_id,sku,stage,result)
    if not result.get('success') or not result.get('import_only'):return status,code,message
    product=result.get('product') or {}
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow('SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2',supplier_id,sku)
            if not row:return status,code,message
            pid=row['id']
            # This phase imports supplier data only; reported prices need purchasing-price review.
            await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',pid)
            if stage=='products':
                source=product.get('_source_metadata') or {}
                await conn.execute("UPDATE products SET source_metadata=$2::jsonb,source_product_type=$3,description_source='supplier_api' WHERE id=$1",pid,json.dumps(source),product.get('_source_product_type'))
                quantity=source.get('qty')
                if valid_quantity(quantity):await conn.execute('UPDATE products SET standard_inventory=$2 WHERE id=$1',pid,int(float(quantity)))
            if 'standard_inventory' in result and valid_quantity(result['standard_inventory']):
                await conn.execute('UPDATE products SET standard_inventory=$2 WHERE id=$1',pid,int(float(result['standard_inventory'])))
                if status=='skipped' and code=='UNMATCHED_PARTS':status,code,message='succeeded','','Standard product inventory saved'
            if positive(result.get('standard_price')):
                await conn.execute('UPDATE products SET base_price=$2,price_needs_review=TRUE WHERE id=$1',pid,float(result['standard_price']))
                await conn.execute('UPDATE products SET price_needs_review=TRUE WHERE id=$1',pid)
                if status=='skipped' and code=='UNMATCHED_PARTS':status,code,message='succeeded','','Reported customer price saved for review'

    if stage=='products' and product.get('_import_media'):
        media_status,media_code,media_message=await _apply_result(supplier_id,sku,'media',dict(success=True,media=product['_import_media']))
        if media_status=='failed':return media_status,media_code,media_message
    return status,code,message


async def apply_result(supplier_id,sku,stage,result):
    status,code,message = await _apply_result_with_metadata(supplier_id,sku,stage,result)
    imported_media = stage=='products' and bool((result.get('product') or {}).get('_import_media'))
    if result.get('success') and (stage=='media' or imported_media):
        from routes.media import cache_product_images
        async with deps.pool.acquire() as conn:
            pid = await conn.fetchval('SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2',supplier_id,sku)
        if pid:
            images = await cache_product_images(pid)
            message += f"; images stored: {images['downloaded']} downloaded, {images['cached']} already saved, {images['failed']} failed"
            if images['failed']:
                status,code = 'failed','IMAGE_DOWNLOAD_FAILED'
                message += '; ' + '; '.join(images['errors'])
    return status,code,message


async def seed_items(log_id,supplier_id,kind,limit,connector,event):
    # Zero means all products; SQL LIMIT NULL and Python [:None] are unbounded.
    limit = None if limit == 0 else limit
    stages=['products','pricing','inventory','media'] if kind=='full' else (['pricing','inventory','media'] if kind=='refresh' else [kind])
    async with deps.pool.acquire() as conn:
        selected=decode(await conn.fetchval('SELECT product_skus FROM supplier_sync_details WHERE log_id=$1',log_id)) or []
    if selected:
        skus=selected[:limit]
        if kind not in ('products','full'):
            async with deps.pool.acquire() as conn:
                found=await conn.fetch('SELECT supplier_sku FROM products WHERE supplier_id=$1 AND supplier_sku=ANY($2::text[])',supplier_id,skus)
            local={r['supplier_sku'] for r in found}
            missing=[sku for sku in skus if sku not in local]
            if missing:raise JobFailure({'error_code':'PRODUCT_MISSING','error':'Not imported under this supplier: '+', '.join(missing)+'. Run a targeted Full sync first.'})
    elif kind in ('products','full'):
        await publish(log_id,'Fetching supplier product list...',stage='Discovery',sku='')
        result=await asyncio.to_thread(connector.get_sellable_products)
        await check_stop(log_id,event)
        if not result.get('success'):raise JobFailure(result)
        skus=sorted({str(p.get('product_id') or '').strip() for p in result.get('products',[]) if p.get('product_id')})[:limit]
    else:
        async with deps.pool.acquire() as conn:
            rows=await conn.fetch("SELECT supplier_sku FROM products WHERE supplier_id=$1 AND ($2::boolean=FALSE OR category IS NULL OR category='') ORDER BY supplier_sku LIMIT $3",supplier_id,kind=='enrich_categories',limit)
        skus=[r['supplier_sku'] for r in rows]
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany('INSERT INTO supplier_sync_items(log_id,stage,sku) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',[(log_id,stage,sku) for stage in stages for sku in skus])
    return stages


class JobFailure(Exception):
    def __init__(self,result):self.result=result;super().__init__(result.get('error','Supplier request failed'))


async def execute_plan(supplier_id, log_id, connector, event, items):
    """Import barrier first, then independent stages concurrently; drain on stop."""
    progress_lock = asyncio.Lock()

    async def progress(*args, **kwargs):
        async with progress_lock:
            return await publish(*args, **kwargs)

    async def run_stage(stage_items):
        consecutive = 0
        for item in stage_items:
            await check_stop(log_id, event)
            stage, sku = item['stage'], item['sku']
            async with deps.pool.acquire() as conn:
                await conn.execute("UPDATE supplier_sync_items SET status='running',updated_at=NOW() WHERE log_id=$1 AND stage=$2 AND sku=$3", log_id, stage, sku)
            await progress(log_id, f'Fetching {stage}: {sku}', stage=stage, sku=sku)
            try:
                async with deps.pool.acquire() as conn:
                    product_state = await conn.fetchval("SELECT status FROM supplier_sync_items WHERE log_id=$1 AND stage='products' AND sku=$2", log_id, sku)
                if stage != 'products' and product_state in ('failed', 'skipped', 'pending', 'running'):
                    status, code, message = 'skipped', 'PRODUCT_STAGE_FAILED', 'Product import is unfinished or failed; dependent request deferred.'
                else:
                    result = await supplier_read(supplier_id, connector, stage, sku, log_id, event)
                    await check_stop(log_id, event)
                    status, code, message = await apply_result(supplier_id, sku, stage, result)
                await check_stop(log_id, event)
            except StopRequested:
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Local supplier sync processing failed for job %s', log_id)
                status, code, message = 'failed', 'LOCAL_ERROR', 'Local processing failed; check the backend log using this job ID.'
            async with deps.pool.acquire() as conn:
                await conn.execute('UPDATE supplier_sync_items SET status=$4,error_code=$5,message=$6,updated_at=NOW() WHERE log_id=$1 AND stage=$2 AND sku=$3', log_id, stage, sku, status, code, message[:1500])
            error = {'stage':stage, 'sku':sku, 'code':code, 'message':message} if status == 'failed' else None
            await progress(log_id, message, error=error)
            consecutive = consecutive + 1 if code in NETWORK else 0
            if code in FATAL or consecutive >= 3:
                event.set()
                raise JobFailure({'error_code':code, 'error':message+' Job halted; unfinished items are saved.'})

    imports = [item for item in items if item['stage'] not in INDEPENDENT_STAGES]
    await run_stage(imports)

    async def guarded_stage(stage_items):
        try:
            await run_stage(stage_items)
        except BaseException:
            event.set()
            raise

    tasks = [asyncio.create_task(guarded_stage([item for item in items if item['stage'] == stage]))
             for stage in ('pricing', 'inventory', 'media')
             if any(item['stage'] == stage for item in items)]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    # Preserve the originating failure instead of a sibling's stop signal.
    for result in results:
        if isinstance(result, JobFailure):
            raise result
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def run_job(supplier_id,log_id):
    event=threading.Event();owner=new_id();runtime={'event':event,'should_stop':False,'retry_events':[]}
    running_syncs[log_id]=runtime
    task=None;token=None
    try:
        async with deps.pool.acquire() as conn:
            claimed=await conn.fetchrow('UPDATE supplier_sync_details SET owner=$2,heartbeat=NOW() WHERE log_id=$1 AND owner IS NULL RETURNING *',log_id,owner)
            if not claimed:return
            log=await conn.fetchrow('SELECT * FROM sync_logs WHERE id=$1',log_id)
            supplier=await conn.fetchrow('SELECT * FROM suppliers WHERE id=$1',supplier_id)
        if not supplier:raise ValueError('Supplier no longer exists')
        connector=make_connector(row_to_dict(supplier))
        if getattr(connector,'import_only',False):
            # Existing connectors use integer comparisons/slices during pagination.
            # sys.maxsize removes the user cap while preserving that interface.
            import sys
            connector.discovery_limit=claimed['item_limit'] or sys.maxsize
            if log['sync_type'] in ('bulk_data','enrich_categories'):raise JobFailure({'error_code':'UNSUPPORTED','error':'Use Products or Full sync for this supplier; SanMar BulkData and CSV enrichment do not apply'})
        if supplier.get('bulk_data_url'):
            connector.services['bulk_data']=supplier['bulk_data_url'].split('?')[0]
        token=request_context.set({'stop':event,'on_retry':lambda info:runtime['retry_events'].append(info)})
        task=asyncio.create_task(heartbeat(log_id,owner,event,runtime))
        await check_stop(log_id,event)
        if log['sync_type']=='bulk_data':
            await run_bulk(log_id,supplier_id,connector,event,cache_only=claimed['stage']=='Cached BulkData')
            return
        async with deps.pool.acquire() as conn:
            has_plan=await conn.fetchval('SELECT COUNT(*) FROM supplier_sync_items WHERE log_id=$1',log_id)
        if not claimed['parent_log_id'] and not has_plan:
            await seed_items(log_id,supplier_id,log['sync_type'],claimed['item_limit'],connector,event)
        async with deps.pool.acquire() as conn:
            items=await conn.fetch("SELECT stage,sku FROM supplier_sync_items WHERE log_id=$1 AND status='pending' ORDER BY CASE stage WHEN 'products' THEN 1 WHEN 'pricing' THEN 2 WHEN 'inventory' THEN 3 WHEN 'media' THEN 4 ELSE 5 END,sku",log_id)
        await execute_plan(supplier_id, log_id, connector, event, items)
        counts=await publish(log_id)
        state='completed_with_errors' if counts.get('failed') or counts.get('skipped') else 'completed'
        await publish(log_id,f"Finished: {counts.get('succeeded',0)} successful, {counts.get('failed',0)} failed, {counts.get('skipped',0)} skipped.",stage='Finished',sku='',terminal=state)
        if counts.get('succeeded'):
            async with deps.pool.acquire() as conn:await conn.execute('UPDATE suppliers SET last_sync=NOW() WHERE id=$1',supplier_id)
    except StopRequested:
        await publish(log_id,'Stopped after the current request. Saved changes remain; unfinished items can be retried.',terminal='stopped')
    except JobFailure as exc:
        await publish(log_id,str(exc),error={'code':exc.result.get('error_code','SUPPLIER_ERROR'),'message':str(exc)},terminal='failed')
    except asyncio.CancelledError:
        event.set()
        with contextlib.suppress(Exception):await publish(log_id,'Worker interrupted; unfinished items can be retried.',terminal='interrupted')
        raise
    except Exception:
        logger.exception('Supplier job %s failed',log_id)
        with contextlib.suppress(Exception):await publish(log_id,'Local job error. Check the backend log for this job ID.',error={'code':'LOCAL_ERROR','message':'Backend processing error'},terminal='failed')
    finally:
        event.set()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError,Exception):await task
        if token is not None:request_context.reset(token)
        if running_syncs.get(log_id) is runtime:running_syncs.pop(log_id,None)


async def run_bulk(log_id,supplier_id,connector,event,cache_only=False):
    from bulk_data import get_snapshot
    await publish(log_id,'Reading cached BulkData or reserving one daily supplier request; no request retry.',stage='BulkData')
    result=await get_snapshot(deps.pool,supplier_id,connector,cache_only)
    # Snapshot is already durable if cancellation happens during local processing.
    await check_stop(log_id,event)
    await publish(log_id,'Using saved BulkData; no supplier call.' if result.get('cache_used') else 'Complete supplier response saved before product import.')
    grouped={}
    for row in result.get('products',[]):
        sku=str(row.get('style') or '').strip()
        if not sku:continue
        product=grouped.setdefault(sku,{'product_name':row.get('product_name') or sku,'description':row.get('description',''),'brand':row.get('brand',''),'variants':[],'rows':[],'_bulk_source':True,'_bulk_fetched_at':result.get('fetched_at')})
        if not product['description'] and row.get('description'):product['description']=row['description']
        product['rows'].append(row)
        product['variants'].append({'variant_sku':row.get('product_id'),'color':row.get('color',''),'size':row.get('size',''),'price':row.get('price'),'inventory':row.get('quantity')})
    async with deps.pool.acquire() as conn:
        await conn.executemany("INSERT INTO supplier_sync_items(log_id,stage,sku) VALUES($1,'bulk_data',$2) ON CONFLICT DO NOTHING",[(log_id,k) for k in grouped])
    for sku,product in sorted(grouped.items()):
        await check_stop(log_id,event)
        await publish(log_id,f'Importing saved BulkData: {sku}',sku=sku)
        try:
            costs=[float(v['price']) for v in product['variants'] if positive(v.get('price'))]
            product['price']=min(costs) if costs else 0
            images={}
            for row in product['rows']:
                # The association comes from the SAME supplier record as its exact variant SKU.
                for url in str(row.get('image_url') or '').splitlines():
                    url=url.strip()
                    if not url.startswith(('https://','http://')):continue
                    image=images.setdefault(url,{'parts':set(),'colours':set()})
                    image['parts'].add(row['product_id'])
                    if row.get('color'):image['colours'].add(row['color'])
            async with deps.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','supplier-product:'+supplier_id+':'+sku)
                    product_id=await save_product(conn,supplier_id,sku,product)
                    metadata={k:v for k,v in product['rows'][0].items() if k not in ('product_id','size','color','fr_color','quantity','price','sale_price','raw_fields')}
                    metadata['source']='bulk_data'
                    metadata['description']=product['description']
                    await conn.execute("UPDATE products SET bulk_metadata=$2::jsonb,description_source=CASE WHEN $3<>'' THEN 'bulk_data' ELSE description_source END WHERE id=$1",product_id,json.dumps(metadata),product['description'])
                    for row in product['rows']:
                        await conn.execute('UPDATE product_variants SET bulk_metadata=$3::jsonb WHERE product_id=$1 AND variant_sku=$2',product_id,row['product_id'],json.dumps(row))
                    for url,image in images.items():
                        old=await conn.fetchval('SELECT id FROM product_media WHERE product_id=$1 AND url=$2',product_id,url)
                        colour=next(iter(image['colours'])) if len(image['colours'])==1 else ''
                        if not old:
                            await conn.execute("INSERT INTO product_media(id,product_id,media_type,url,description,is_primary,created_at) VALUES($1,$2,'image',$3,'BulkData variant image',TRUE,NOW())",new_id(),product_id,url)
                        await conn.execute("UPDATE product_media SET source_color=$3,source_part_ids=$4::jsonb WHERE product_id=$1 AND url=$2",product_id,url,colour,json.dumps(sorted(image['parts'])))
                    await conn.execute("UPDATE products SET price_needs_review=FALSE WHERE id=$1 AND NOT EXISTS(SELECT 1 FROM product_variants WHERE product_id=$1 AND is_active IS DISTINCT FROM FALSE AND (price IS NULL OR price<=0))",product_id)
            from routes.media import cache_product_images
            cached_images = await cache_product_images(product_id)
            status,code,message='succeeded','',f"BulkData saved; images: {cached_images['downloaded']} downloaded, {cached_images['cached']} already saved, {cached_images['failed']} failed"
            if cached_images['failed']:
                status,code='failed','IMAGE_DOWNLOAD_FAILED'
                message += '; ' + '; '.join(cached_images['errors'])
            if any(not positive(v.get('price')) or not valid_quantity(v.get('inventory')) for v in product['variants']):
                status,code,message='failed','INVALID_DATA','BulkData saved; missing/invalid prices or inventory retained for review. Existing valid values preserved.'
        except StopRequested:raise
        except Exception:
            logger.exception('BulkData import failed for job %s',log_id)
            status,code,message='failed','LOCAL_ERROR','Saved snapshot retained; retry local import with cache_only=true. Check backend log.'
        async with deps.pool.acquire() as conn:
            await conn.execute('UPDATE supplier_sync_items SET status=$3,error_code=$4,message=$5,updated_at=NOW() WHERE log_id=$1 AND sku=$2',log_id,sku,status,code,message)
        await publish(log_id,message,error={'code':code,'sku':sku,'message':message} if code else None)
    counts=await publish(log_id)
    await publish(log_id,f"BulkData finished: {counts.get('succeeded',0)} successful, {counts.get('failed',0)} need attention. Snapshot can be reprocessed without a supplier request.",stage='Finished',sku='',terminal='completed_with_errors' if counts.get('failed') else 'completed')


async def legacy_task(supplier_id,log_id,kind):
    # Scheduled calls keep their public function names but enter the same reservation path.
    try:
        await reserve_job(supplier_id,kind,existing_log=log_id)
    except HTTPException as exc:
        async with deps.pool.acquire() as conn:await conn.execute("UPDATE sync_logs SET status='failed',message=$2,end_time=NOW() WHERE id=$1",log_id,str(exc.detail))
        return
    await run_job(supplier_id,log_id)


async def sync_products_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'products')
async def sync_inventory_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'inventory')
async def sync_pricing_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'pricing')
async def sync_media_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'media')
async def sync_bulk_data_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'bulk_data')
async def enrich_categories_task(supplier_id,log_id):await legacy_task(supplier_id,log_id,'enrich_categories')


async def sync_one(product_id,stage):
    async with deps.pool.acquire() as conn:
        row=await conn.fetchrow('SELECT p.supplier_id,p.supplier_sku FROM products p JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=$1',product_id)
    if not row:return {'success':False,'message':'Product or supplier not found'}
    # Individual refreshes reserve the supplier as well, avoiding overlap with bulk jobs.
    log_id=await reserve_job(row['supplier_id'],stage,1)
    async with deps.pool.acquire() as conn:await conn.execute('INSERT INTO supplier_sync_items(log_id,stage,sku) VALUES($1,$2,$3)',log_id,stage,row['supplier_sku'])
    await run_job(row['supplier_id'],log_id)
    async with deps.pool.acquire() as conn:
        item=await conn.fetchrow('SELECT status,error_code,message FROM supplier_sync_items WHERE log_id=$1',log_id)
    return {'success':bool(item and item['status']=='succeeded'),'status':item['status'] if item else 'failed','message':item['message'] if item else 'Job failed before processing','error_code':item['error_code'] if item else 'LOCAL_ERROR','log_id':log_id}


@router.post('/sync/product/{product_id}/inventory')
async def sync_product_inventory(product_id:str,user=Depends(get_current_user)):return await sync_one(product_id,'inventory')
@router.post('/sync/product/{product_id}/pricing')
async def sync_product_pricing(product_id:str,user=Depends(get_current_user)):return await sync_one(product_id,'pricing')
@router.post('/sync/product/{product_id}/media')
async def sync_product_media(product_id:str,user=Depends(get_current_user)):return await sync_one(product_id,'media')

async def _sync_product_inventory_internal(product_id):return await sync_one(product_id,'inventory')
async def _sync_product_pricing_internal(product_id):return await sync_one(product_id,'pricing')
async def _sync_product_media_internal(product_id):return await sync_one(product_id,'media')


async def auto_push_to_odoo_if_enabled(supplier_id: str):
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT auto_push_to_odoo, odoo_url, odoo_db, odoo_username, odoo_api_key, markup_percentage FROM settings WHERE id = 'system_settings'")
            if not settings_row or not settings_row.get('auto_push_to_odoo'): return
            if not settings_row.get('odoo_url'):
                logger.info("Auto-push: Odoo not configured, skipping"); return
            pending_count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE AND odoo_sync_status = 'pending' AND supplier_id = $1", supplier_id)
            if pending_count == 0: return
        logger.info("Auto-push: %d products pending for Odoo", pending_count)
        push_log_id = await create_sync_log(supplier_id, "Auto", "odoo_push", f"Auto-pushing {pending_count} products to Odoo...")
        await odoo_push_task(supplier_id, push_log_id)
    except Exception as e:
        logger.error("Auto-push to Odoo error: %s", e)


async def odoo_push_task(supplier_id: str, log_id: str):
    from odoo_service import OdooService
    from deps import calculate_sale_price
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings.get('markup_percentage') or 40)
            products = await conn.fetch('''
                SELECT p.*, cm.odoo_category_id FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending' AND p.supplier_id = $1
            ''', supplier_id)
        if not products:
            await update_sync_log(log_id, 'completed', 'No pending products', progress=100); return
        odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
        conn_test = await asyncio.to_thread(odoo.test_connection)
        if not conn_test.get('connected'):
            await update_sync_log(log_id, 'failed', f"Odoo connection failed: {conn_test.get('message')}"); return
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
            result = await asyncio.to_thread(odoo.create_or_update_product,odoo_data)
            if result.get('success'):
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                        str(result.get('odoo_id', '')), utc_now(), product['id'])
                synced += 1
            else:
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET odoo_sync_status = 'failed', updated_at = $1 WHERE id = $2", utc_now(), product['id'])
                failed += 1
        msg = f"Auto-push complete: {synced} synced, {failed} failed out of {len(products)}"
        await update_sync_log(log_id, 'completed', msg, progress=100, total=len(products), processed=synced)
        logger.info("Auto-push: %s", msg)
    except Exception as e:
        logger.error("Odoo push task error: %s", e)
        await update_sync_log(log_id, 'failed', f'Error: {str(e)}')
