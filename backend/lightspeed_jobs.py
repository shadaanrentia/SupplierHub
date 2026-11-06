"""Persistent two-stage sync. POST only queues; one database-elected worker exports."""
import asyncio
import json
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
import deps
from deps import get_current_user, new_id
from sync_context import defer_images
from category_scope import in_category

router=APIRouter(prefix='/api/lightspeed-sync',tags=['Lightspeed sync'])
log=logging.getLogger(__name__)
_task=None
LOCK='supplierhub:lightspeed-batch-worker'


async def init_schema(conn):
    await conn.execute('''CREATE TABLE IF NOT EXISTS lightspeed_sync_batches (
        id VARCHAR(64) PRIMARY KEY,store_domain TEXT NOT NULL,request_key TEXT NOT NULL,
        selection JSONB NOT NULL,status TEXT NOT NULL DEFAULT 'queued',stage TEXT NOT NULL DEFAULT 'planning',
        total INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '',requested_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(store_domain,request_key));
        CREATE UNIQUE INDEX IF NOT EXISTS lightspeed_one_active_batch ON lightspeed_sync_batches(store_domain)
            WHERE status IN ('queued','running');
        CREATE TABLE IF NOT EXISTS lightspeed_sync_items (
        batch_id VARCHAR(64) NOT NULL REFERENCES lightspeed_sync_batches(id) ON DELETE CASCADE,
        product_id VARCHAR(64) NOT NULL,sku TEXT NOT NULL,product_name TEXT,position INTEGER NOT NULL,
        details_status TEXT NOT NULL DEFAULT 'queued',images_status TEXT NOT NULL DEFAULT 'waiting',
        details_result JSONB NOT NULL DEFAULT '{}'::jsonb,images_result JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(batch_id,product_id));
        CREATE INDEX IF NOT EXISTS lightspeed_sync_product_history ON lightspeed_sync_items(product_id,updated_at DESC);
    ''')


def decoded(value):
    return json.loads(value) if isinstance(value,str) else value


def public(row):
    data=dict(row)
    for key in ('selection','details_result','images_result','result'):
        if key in data:data[key]=decoded(data[key])
    return data


async def domain(conn):
    value=await conn.fetchval("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'")
    if not str(value or '').strip():raise HTTPException(400,'Configure Lightspeed first')
    return str(value).strip()


@router.post('/jobs',status_code=202)
async def enqueue(body:dict,user=Depends(get_current_user)):
    selected=body.get('product_ids') or []
    if not isinstance(selected,list) or any(not isinstance(x,str) for x in selected):raise HTTPException(400,'product_ids must be a list of product IDs')
    if not selected and not body.get('sync_all'):raise HTTPException(400,'Select products first')
    for name in ('supplier_id','category_id','search','status'):
        if body.get(name) is not None and not isinstance(body[name],str):raise HTTPException(400,name+' must be text')
    try:request_key=str(UUID(str(body.get('request_id') or new_id())))
    except ValueError:raise HTTPException(400,'Invalid request_id')
    selection={key:body.get(key) for key in ('supplier_id','category_id','search','status','sync_all')}
    selection['product_ids']=list(dict.fromkeys(selected))
    async with deps.pool.acquire() as conn:
        store=await domain(conn)
        async with conn.transaction():
            # Fail quickly rather than waiting behind another enqueue request.
            if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtext($1))','queue:'+store):
                raise HTTPException(409,'Another sync request is being queued; check progress before retrying')
            previous=await conn.fetchrow('SELECT * FROM lightspeed_sync_batches WHERE store_domain=$1 AND request_key=$2',store,request_key)
            if previous:return public(previous)
            existing=await conn.fetchval("SELECT id FROM lightspeed_sync_batches WHERE store_domain=$1 AND status IN ('queued','running')",store)
            if existing:raise HTTPException(409,{'message':'A Lightspeed batch is already active','job_id':existing})
            job_id=new_id()
            await conn.execute('INSERT INTO lightspeed_sync_batches(id,store_domain,request_key,selection,requested_by) VALUES($1,$2,$3,$4::jsonb,$5)',job_id,store,request_key,json.dumps(selection),str(user.get('id') or user.get('sub') or ''))
    return {'id':job_id,'status':'queued','stage':'planning','total':0}


@router.get('/jobs')
async def jobs(user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        store=await domain(conn)
        rows=await conn.fetch('SELECT * FROM lightspeed_sync_batches WHERE store_domain=$1 ORDER BY created_at DESC LIMIT 50',store)
    return [public(row) for row in rows]


@router.get('/jobs/{job_id}')
async def job(job_id:str,page:int=Query(1,ge=1),issues_only:bool=False,search:str='',user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        batch=await conn.fetchrow('SELECT * FROM lightspeed_sync_batches WHERE id=$1 AND store_domain=$2',job_id,await domain(conn))
        if not batch:raise HTTPException(404,'Sync batch not found')
        counts=dict(await conn.fetchrow('''SELECT
            COUNT(*) FILTER(WHERE details_status NOT IN ('queued','running')) AS details_processed,
            COUNT(*) FILTER(WHERE details_status='completed') AS details_completed,
            COUNT(*) FILTER(WHERE details_status IN ('failed','interrupted')) AS details_failed,
            COUNT(*) FILTER(WHERE images_status='completed') AS images_completed,
            COUNT(*) FILTER(WHERE images_status IN ('pending','interrupted')) AS images_pending,
            COUNT(*) FILTER(WHERE details_status NOT IN ('queued','running') AND images_status NOT IN ('waiting','queued','running')) AS finished
            FROM lightspeed_sync_items WHERE batch_id=$1''',job_id))
        current=await conn.fetchrow("SELECT sku,product_name FROM lightspeed_sync_items WHERE batch_id=$1 AND (details_status='running' OR images_status='running') ORDER BY position LIMIT 1",job_id)
        condition="batch_id=$1 AND (NOT $2::boolean OR details_status IN ('failed','interrupted') OR images_status IN ('pending','interrupted')) AND (sku ILIKE $3 OR product_name ILIKE $3)"
        args=(job_id,issues_only,'%'+search.strip()+'%')
        total=await conn.fetchval('SELECT COUNT(*) FROM lightspeed_sync_items WHERE '+condition,*args)
        rows=await conn.fetch('SELECT * FROM lightspeed_sync_items WHERE '+condition+' ORDER BY position LIMIT 50 OFFSET $4',*args,(page-1)*50)
    return {**public(batch),'counts':counts,'current':dict(current) if current else None,'items':[public(row) for row in rows],'filtered_total':total}


@router.get('/history')
async def history(product_id:str=None,page:int=Query(1,ge=1),search:str='',issues_only:bool=True,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        store=await domain(conn)
        batches=await conn.fetch('''SELECT i.*,b.status AS batch_status FROM lightspeed_sync_items i JOIN lightspeed_sync_batches b ON b.id=i.batch_id
            WHERE i.product_id=$1 AND b.store_domain=$2 ORDER BY i.updated_at DESC LIMIT 50''',product_id,store) if product_id else []
        condition="j.store_domain=$1 AND ($2::varchar IS NULL OR j.product_id=$2) AND (NOT $3::boolean OR j.status IN ('failed','images_pending','needs_review','interrupted')) AND (p.supplier_sku ILIKE $4 OR p.product_name ILIKE $4)"
        args=(store,product_id,issues_only if not product_id else False,'%'+search.strip()+'%')
        total=await conn.fetchval('SELECT COUNT(*) FROM lightspeed_review_jobs j JOIN products p ON p.id=j.product_id WHERE '+condition,*args)
        rows=await conn.fetch('SELECT j.*,p.supplier_sku AS sku,p.product_name FROM lightspeed_review_jobs j JOIN products p ON p.id=j.product_id WHERE '+condition+' ORDER BY j.updated_at DESC,j.id LIMIT 50 OFFSET $5',*args,(page-1)*50)
    return {'batches':[public(row) for row in batches],'earlier_jobs':[public(row) for row in rows],'total':total}


async def current_service(batch):
    from routes.lightspeed import _get_ls_service
    ls=await _get_ls_service()
    if ls.mock_mode or ls.domain_prefix!=batch['store_domain']:raise ValueError('Configured Lightspeed store changed or is unavailable')
    return ls


async def plan(batch):
    from routes.preprocessing import catalog,can_export_selected
    from product_readiness import load_readiness
    selection=decoded(batch['selection'])
    selected=selection.get('product_ids') or []
    async with deps.pool.acquire() as conn:
        products=await catalog(conn,search=selection.get('search') or '' if not selected else '',supplier_id=selection.get('supplier_id'),lightweight=True,product_ids=selected or None)
        states=await load_readiness(conn,products,include_assets=False)
        rows=[p for p in products if in_category(states[p['id']],selection.get('category_id')) and
              (bool(selected) or (can_export_selected(states[p['id']]) and (not selection.get('status') or selection['status']=='all' or states[p['id']]['status']==selection['status'])))]
        if selected and set(selected)-{p['id'] for p in rows}:raise ValueError('Selected products were removed or no longer match this supplier/category; reload Pre-processing')
        if not rows:raise ValueError('No eligible products in the selected supplier/category')
        async with conn.transaction():
            await conn.executemany('INSERT INTO lightspeed_sync_items(batch_id,product_id,sku,product_name,position) VALUES($1,$2,$3,$4,$5)',[(batch['id'],p['id'],p.get('supplier_sku') or '',p.get('product_name'),i) for i,p in enumerate(rows)])
            await conn.execute("UPDATE lightspeed_sync_batches SET total=$2,stage='details',updated_at=NOW() WHERE id=$1",batch['id'],len(rows))
    return rows


async def item_result(batch_id,product_id,stage,status,result):
    if stage not in ('details','images'):raise ValueError('Unknown sync stage')
    async with deps.pool.acquire() as conn:
        await conn.execute(f'UPDATE lightspeed_sync_items SET {stage}_status=$3,{stage}_result=$4::jsonb,updated_at=NOW() WHERE batch_id=$1 AND product_id=$2',batch_id,product_id,status,json.dumps(result,default=str))
        await conn.execute('UPDATE lightspeed_sync_batches SET updated_at=NOW() WHERE id=$1',batch_id)


async def details_stage(batch,item):
    from routes.preprocessing import sync_products_now
    selection=decoded(batch['selection'])
    token=defer_images.set(True)
    try:
        result=await sync_products_now({'product_ids':[item['product_id']],'supplier_id':selection.get('supplier_id'),'category_id':selection.get('category_id')},user={})
        ok=result.get('synced')==1 or result.get('images_pending')==1
        await item_result(batch['id'],item['product_id'],'details','completed' if ok else 'failed',result)
        await item_result(batch['id'],item['product_id'],'images','queued' if ok else 'not_started',{})
        if ok:
            async with deps.pool.acquire() as conn:await conn.execute("UPDATE products SET lightspeed_sync_status='images_pending' WHERE id=$1",item['product_id'])
    except Exception as exc:
        log.exception('Details failed for %s',item['sku'])
        await item_result(batch['id'],item['product_id'],'details','failed',{'error':str(exc)})
        await item_result(batch['id'],item['product_id'],'images','not_started',{})
    finally:defer_images.reset(token)


async def images_stage(batch,item):
    from routes.export_review import run_action
    ls=await current_service(batch)
    async with deps.pool.acquire() as conn:
        lock='export-review:'+item['product_id']
        if not await conn.fetchval('SELECT pg_try_advisory_lock(hashtext($1))',lock):raise ValueError('Another export or repair is active')
        try:
            review_id=new_id()
            await conn.execute("INSERT INTO lightspeed_review_jobs(id,product_id,store_domain,kind,status) VALUES($1,$2,$3,'repair-images','running')",review_id,item['product_id'],ls.domain_prefix)
            await run_action(review_id,item['product_id'],'repair-images',ls)
            result=public(await conn.fetchrow('SELECT status,result FROM lightspeed_review_jobs WHERE id=$1',review_id))
            await item_result(batch['id'],item['product_id'],'images','completed' if result['status']=='completed' else 'pending',result)
        finally:await conn.execute('SELECT pg_advisory_unlock(hashtext($1))',lock)


async def run_batch(batch,lease=None):
    async with deps.pool.acquire() as conn:await conn.execute("UPDATE lightspeed_sync_batches SET status='running',updated_at=NOW() WHERE id=$1",batch['id'])
    await plan(batch)
    async with deps.pool.acquire() as conn:items=[dict(row) for row in await conn.fetch('SELECT * FROM lightspeed_sync_items WHERE batch_id=$1 ORDER BY position',batch['id'])]
    for item in items:
        if lease is not None:await lease.fetchval('SELECT 1')
        await current_service(batch)
        await item_result(batch['id'],item['product_id'],'details','running',{})
        await details_stage(batch,item)
    async with deps.pool.acquire() as conn:
        await conn.execute("UPDATE lightspeed_sync_batches SET stage='images',updated_at=NOW() WHERE id=$1",batch['id'])
        images=await conn.fetch("SELECT * FROM lightspeed_sync_items WHERE batch_id=$1 AND details_status='completed' ORDER BY position",batch['id'])
    for row in images:
        if lease is not None:await lease.fetchval('SELECT 1')
        await current_service(batch)
        item=dict(row)
        await item_result(batch['id'],item['product_id'],'images','running',{})
        try:await images_stage(batch,item)
        except Exception as exc:
            log.exception('Images pending for %s',item['sku'])
            await item_result(batch['id'],item['product_id'],'images','pending',{'error':str(exc)})
        await asyncio.sleep(.2)
    async with deps.pool.acquire() as conn:
        count=await conn.fetchval("SELECT COUNT(*) FROM lightspeed_sync_items WHERE batch_id=$1 AND (details_status!='completed' OR images_status!='completed')",batch['id'])
        await conn.execute("UPDATE lightspeed_sync_batches SET status=$2,stage='finished',updated_at=NOW() WHERE id=$1",batch['id'],'completed_with_issues' if count else 'completed')


async def interrupted(conn,batch_id,message):
    await conn.execute("UPDATE lightspeed_sync_items SET details_status=CASE WHEN details_status IN ('queued','running') THEN 'interrupted' ELSE details_status END,images_status=CASE WHEN images_status IN ('waiting','queued','running') THEN 'interrupted' ELSE images_status END WHERE batch_id=$1",batch_id)
    await conn.execute("UPDATE lightspeed_sync_batches SET status='interrupted',message=$2,updated_at=NOW() WHERE id=$1",batch_id,message)


async def worker():
    while True:
        try:
            async with deps.pool.acquire() as leader:
                if not await leader.fetchval('SELECT pg_try_advisory_lock(hashtext($1))',LOCK):
                    await asyncio.sleep(3);continue
                try:
                    for row in await leader.fetch("SELECT id FROM lightspeed_sync_batches WHERE status='running'"):
                        await interrupted(leader,row['id'],'Worker restarted; inspect unfinished products before retrying')
                    while True:
                        row=await leader.fetchrow("SELECT * FROM lightspeed_sync_batches WHERE status='queued' ORDER BY created_at LIMIT 1")
                        if row:
                            try:await run_batch(dict(row),leader)
                            except Exception as exc:
                                log.exception('Batch interrupted')
                                await interrupted(leader,row['id'],str(exc))
                        else:await asyncio.sleep(2)
                finally:await leader.execute('SELECT pg_advisory_unlock(hashtext($1))',LOCK)
        except asyncio.CancelledError:raise
        except Exception:
            log.exception('Sync worker unavailable; retrying election')
            await asyncio.sleep(3)


async def start_worker():
    global _task
    if _task and not _task.done():return
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','lightspeed-queue-schema')
            await init_schema(conn)
    _task=asyncio.create_task(worker())


async def stop_worker():
    if _task:
        _task.cancel()
        try:await _task
        except asyncio.CancelledError:pass
